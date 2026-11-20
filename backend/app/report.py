"""Report assembly (Wave 3): deterministic numbers + AI qualitative text.

Implements plan §8 (AI report & number anti-forgery) and the evidence-chain
half of §9A:

  1. Backend computes first. The audit and stats engines produce the
     structured JSON — the single source of truth for every number.
  2. AI only writes explanations. Gemini receives ONLY the StatsSummary
     JSON and is told to output qualitative paragraphs with no numbers.
  3. The backend fills every number slot. render_markdown() formats each
     figure from the JSON originals; the AI paragraph is embedded verbatim
     and never participates in number rendering.
  4. Safety-net check. check_numbers() scans the AI paragraph for numbers
     and compares them against the JSON values (2-decimal rounding
     tolerated, plus 1-decimal because the rule-based template formats the
     quality score to 1 decimal). Mismatches are listed in
     report["number_check"]["unmatched"] as a hint only — generation is
     never blocked by this check (the structural isolation in steps 1–3
     is the real defence).

Every conclusion carries evidence {dataset_id, analysis_ids, analysis,
statistic, method, params, value}; a conclusion without evidence is never
emitted. analysis_ids are filled by the report router after the audit /
stats runs are stored; assemble_report() accepts them optionally.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone

from .ai_adapter import (
    ColumnSummary,
    GeminiProvider,
    StatsSummary,
    make_send_manifest,
    rule_based_summarize,
)
from .ai_adapter import summarize as ai_summarize
from .audit import ENGINE_VERSION as AUDIT_ENGINE_VERSION  # noqa: F401  (re-exported for routers)
from .audit import run_audit
from .charts import regression as chart_regression
from .stats import ENGINE_VERSION as STATS_ENGINE_VERSION  # noqa: F401  (re-exported for routers)
from .stats import compute_stats

ENGINE_VERSION = "0.4.0"

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Keys whose values change on every run and must not count as differences
# when comparing an original analysis with its rerun.
_VOLATILE_KEYS = {
    "generated_at",
    "tokens",
    "send_manifest",
    "analysis_ids",
    "audit_analysis_id",
    "stats_analysis_id",
    "rerun_note",
}


# ---------------------------------------------------------------------------
# StatsSummary construction (privacy boundary: aggregates only, no raw rows)
# ---------------------------------------------------------------------------

def build_stats_summary(dataset_rec: dict, df, audit_result: dict, stats_result: dict) -> StatsSummary:
    columns = []
    for name, s in stats_result["columns"].items():
        columns.append(
            ColumnSummary(
                name=name,
                dtype=str(df[name].dtype),
                count=s["count"],
                missing=s["missing"],
                mean=s.get("mean"),
                median=s.get("median"),
                std=s.get("std"),
                minimum=s.get("min"),
                maximum=s.get("max"),
            )
        )
    findings: list[str] = []
    for d in audit_result["score"]["deductions"]:
        if d["deduction"] > 0:
            findings.append(f"{d['label']}：扣 {d['deduction']} 分（{d['rate_basis']}）")
    for p in audit_result.get("pending_outliers", []):
        findings.append(f"{p['column']} 列有 {p['count']} 个待确认异常值")
    return StatsSummary(
        dataset_name=dataset_rec["name"],
        rows=int(len(df)),
        cols=int(len(df.columns)),
        file_hash=dataset_rec["file_hash"],
        columns=tuple(columns),
        quality_score=audit_result["score"]["total"],
        findings=tuple(findings),
        parameters={
            "audit_profile": audit_result["score"]["profile"]["name"],
            "correlation_method": "pearson",
            "algorithms": audit_result["params"]["algorithms"],
        },
    )


# ---------------------------------------------------------------------------
# Correlation / regression
# ---------------------------------------------------------------------------

def _is_id_column(name: str) -> bool:
    """Identifier columns (id / *_id) are row labels, not analysis variables:
    sample_id trivially "correlates" with anything ordered by row, so it
    must never drive the strongest-pair / regression choice."""
    n = name.lower()
    return n == "id" or n.endswith("_id")


def strongest_pair(stats_result: dict) -> tuple[str, str, float] | None:
    """Off-diagonal pair with the largest |Pearson r| (None if no matrix).

    Identifier columns are excluded (see _is_id_column).
    """
    matrix = stats_result.get("correlation", {}).get("matrix", {}) or {}
    best: tuple[str, str, float] | None = None
    for a, row in matrix.items():
        if _is_id_column(a):
            continue
        for b, v in row.items():
            if a == b or v is None or _is_id_column(b):
                continue
            if best is None or abs(v) > abs(best[2]):
                best = (a, b, float(v))
    return best


def compute_regression(df, stats_result: dict) -> dict:
    """Regression on the strongest-correlation pair; graceful when impossible."""
    pair = strongest_pair(stats_result)
    if pair is None:
        return {"available": False, "note": "数值列不足 2 列，未计算回归"}
    x, y, _r = pair
    try:
        reg = chart_regression(df, x, y)
    except ValueError as exc:
        return {"available": False, "note": str(exc), "x_column": x, "y_column": y}
    return {"available": True, **reg}


# ---------------------------------------------------------------------------
# Conclusions with evidence chains (plan §9A: no evidence, no conclusion)
# ---------------------------------------------------------------------------

def build_conclusions(
    dataset_id: int,
    audit_result: dict,
    stats_result: dict,
    regression_result: dict,
    analysis_ids: dict[str, list[int]] | None = None,
) -> list[dict]:
    def evidence(statistic: str, method: str, params: dict, value, engine: str) -> dict:
        ids = list((analysis_ids or {}).get(engine, []))
        return {
            "dataset_id": dataset_id,
            "analysis_ids": ids,
            "analysis": engine,
            "statistic": statistic,
            "method": method,
            "params": params,
            "value": value,
        }

    conclusions: list[dict] = []
    score = audit_result["score"]["total"]
    conclusions.append(
        {
            "id": "E1",
            "text": (
                f"数据质量评分为 {score} 分（满分 100），"
                f"扣分合计 {audit_result['score']['total_deduction']} 分。"
            ),
            "evidence": evidence(
                "quality_score", "audit", audit_result["params"], score, "audit"
            ),
        }
    )

    missing_total = audit_result["missing"]["total"]
    dup_count = audit_result["duplicates"]["count"]
    if missing_total or dup_count:
        conclusions.append(
            {
                "id": "E2",
                "text": (
                    f"数据存在 {missing_total} 个缺失值与 {dup_count} 个重复行，"
                    "需在分析前处理并记录处理方式。"
                ),
                "evidence": evidence(
                    "missing_and_duplicates",
                    "audit",
                    audit_result["params"],
                    {"missing": missing_total, "duplicates": dup_count},
                    "audit",
                ),
            }
        )

    pair = strongest_pair(stats_result)
    if pair is not None:
        a, b, r = pair
        direction = "正相关" if r >= 0 else "负相关"
        strength = "强" if abs(r) >= 0.7 else ("中等" if abs(r) >= 0.3 else "弱")
        conclusions.append(
            {
                "id": "E3",
                "text": (
                    f"{a} 与 {b} 呈{strength}{direction}"
                    f"（Pearson 相关系数 {r}），相关不等于因果。"
                ),
                "evidence": evidence(
                    "pearson_correlation",
                    "pearson",
                    {"method": "pearson", "x": a, "y": b},
                    r,
                    "stats",
                ),
            }
        )

    if regression_result.get("available"):
        conclusions.append(
            {
                "id": "E4",
                "text": (
                    f"线性回归：{regression_result['equation']}，"
                    f"R²={regression_result['r_squared']}，"
                    f"样本量 n={regression_result['n']}。"
                ),
                "evidence": evidence(
                    "r_squared",
                    "ols_regression",
                    {
                        "x": regression_result["x_column"],
                        "y": regression_result["y_column"],
                        "method": "ols",
                    },
                    regression_result["r_squared"],
                    "stats",
                ),
            }
        )

    pending = audit_result.get("pending_outliers", [])
    if pending:
        n_cols = len(pending)
        n_pts = sum(p["count"] for p in pending)
        conclusions.append(
            {
                "id": "E5",
                "text": (
                    f"有 {n_cols} 列共 {n_pts} 个统计异常值处于待确认状态，"
                    "未计入扣分、未自动删除，需人工复核后决策。"
                ),
                "evidence": evidence(
                    "pending_outliers",
                    "iqr/zscore",
                    audit_result["params"],
                    n_pts,
                    "audit",
                ),
            }
        )

    # Renumber sequentially (E1..En) in emission order.
    for i, c in enumerate(conclusions, start=1):
        c["id"] = f"E{i}"
    return conclusions


# ---------------------------------------------------------------------------
# Safety-net number check (§8: hint only, never blocks generation)
# ---------------------------------------------------------------------------

def _collect_numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)


def check_numbers(ai_text: str, report: dict) -> dict:
    """Scan numbers in the AI paragraph against the report JSON values.

    A number matches when it equals some JSON value rounded to 2 decimals
    (or to 1 decimal, since the rule-based template prints the quality
    score with 1 decimal). Unmatched numbers are listed for human review.
    """
    known: set[float] = set()
    for section in ("audit", "stats", "correlation", "regression"):
        _collect_numbers(report.get(section), known)
    known.update({0.0, 100.0})  # scale constants of the 0–100 quality score
    known_2dp = {round(v, 2) for v in known}
    known_1dp = {round(v, 1) for v in known}
    found = _NUMBER_RE.findall(ai_text or "")
    unmatched: list[dict] = []
    seen: set[str] = set()
    for raw in found:
        if raw in seen:
            continue
        seen.add(raw)
        val = float(raw)
        if round(val, 2) not in known_2dp and round(val, 1) not in known_1dp:
            unmatched.append({"value": raw, "rounded_2dp": round(val, 2)})
    return {"checked": len(found), "unmatched": unmatched}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_report(
    dataset_rec: dict,
    df,
    include_ai: bool = True,
    audit_params: dict | None = None,
    analysis_ids: dict[str, list[int]] | None = None,
) -> dict:
    """Assemble the full report JSON for one dataset.

    Runs the audit + stats engines, the strongest-pair regression, builds
    evidence-backed conclusions, then adds the AI (or rule-based) paragraph.
    AI failure / timeout / unavailability degrades to the rule-based text
    with source="rule-based" — the deterministic sections are identical.
    """
    audit_result = run_audit(df, **(audit_params or {}))
    stats_result = compute_stats(df)
    regression_result = compute_regression(df, stats_result)
    conclusions = build_conclusions(
        dataset_rec["id"], audit_result, stats_result, regression_result, analysis_ids
    )

    summary = build_stats_summary(dataset_rec, df, audit_result, stats_result)
    if include_ai:
        try:
            ai_text, manifest = ai_summarize(summary, provider=GeminiProvider())
        except Exception:
            ai_text = rule_based_summarize(summary)
            manifest = make_send_manifest("rule-based-fallback", summary)
        source = "ai" if manifest.model.startswith("gemini") else "rule-based"
        tokens = manifest.tokens if source == "ai" else None
    else:
        ai_text = rule_based_summarize(summary)
        manifest = make_send_manifest("rule-based-fallback", summary)
        source, tokens = "rule-based", None

    pair = strongest_pair(stats_result)
    report = {
        "engine": "report",
        "engine_version": ENGINE_VERSION,
        "dataset": {
            "id": dataset_rec["id"],
            "name": dataset_rec["name"],
            "filename": dataset_rec.get("filename"),
            "rows": int(len(df)),
            "cols": int(len(df.columns)),
            "file_hash": dataset_rec["file_hash"],
            "columns": [
                {"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns
            ],
        },
        "audit": audit_result,
        "stats": stats_result,
        "correlation": stats_result["correlation"],
        "regression": regression_result,
        "conclusions": conclusions,
        "ai_text": ai_text,
        "source": source,
        "send_manifest": asdict(manifest),
        "tokens": tokens,
        "params": {
            "include_ai": include_ai,
            "audit": audit_result["params"],
            "stats": {"method": "pearson", "std_ddof": 1},
            "regression": {"x": pair[0], "y": pair[1]} if pair else None,
            "model": manifest.model,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report["number_check"] = check_numbers(ai_text, report)
    return report


# ---------------------------------------------------------------------------
# Markdown rendering: every number is filled from the JSON originals.
# The AI paragraph is embedded verbatim and never feeds number rendering.
# ---------------------------------------------------------------------------

def _fmt(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def render_markdown(report: dict) -> str:
    d = report["dataset"]
    audit = report["audit"]
    score = audit["score"]
    stats = report["stats"]
    lines: list[str] = []
    lines.append(f"# 数据分析报告：{d['name']}")
    lines.append("")
    lines.append("## 数据集概览")
    lines.append(f"- 名称：{d['name']}")
    lines.append(f"- 文件：{d.get('filename') or ''}")
    lines.append(f"- 行数：{_fmt(d['rows'])}，列数：{_fmt(d['cols'])}")
    lines.append(f"- SHA-256：`{d['file_hash']}`")
    lines.append(
        "- 字段："
        + "、".join(f"{c['name']}（{c['dtype']}）" for c in d["columns"])
    )
    lines.append("")
    lines.append("## 数据质量审计")
    lines.append(f"- 总分：{_fmt(score['total'])} 分（满分 100）")
    lines.append(f"- 公式：{score['formula']}")
    lines.append(f"- 总扣分：{_fmt(score['total_deduction'])} 分")
    lines.append(f"- 规则画像：{score['profile']['label']}（{score['profile']['name']}）")
    lines.append("")
    lines.append("| 扣分项 | 权重 | 比率 | 扣分 | 依据 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for ded in score["deductions"]:
        lines.append(
            f"| {ded['label']} | {_fmt(ded['weight'])} | {_fmt(ded['rate'])} "
            f"| {_fmt(ded['deduction'])} | {ded['rate_basis']} |"
        )
    lines.append("")
    lines.append("## 描述统计")
    lines.append("| 列 | 计数 | 缺失 | 均值 | 中位数 | 标准差 | 最小值 | 最大值 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for col, s in stats["columns"].items():
        lines.append(
            f"| {col} | {_fmt(s['count'])} | {_fmt(s['missing'])} "
            f"| {_fmt(s['mean']) if s.get('mean') is not None else '—'} "
            f"| {_fmt(s['median']) if s.get('median') is not None else '—'} "
            f"| {_fmt(s['std']) if s.get('std') is not None else '—'} "
            f"| {_fmt(s['min']) if s.get('min') is not None else '—'} "
            f"| {_fmt(s['max']) if s.get('max') is not None else '—'} |"
        )
    for skipped in stats.get("skipped_columns", []):
        lines.append(f"- 跳过列 {skipped['column']}：{skipped['reason']}")
    lines.append("")
    lines.append("## 相关性")
    corr = report["correlation"]
    matrix = corr.get("matrix", {}) or {}
    if matrix:
        cols = list(matrix.keys())
        lines.append("|  | " + " | ".join(cols) + " |")
        lines.append("| --- | " + " | ".join(["---"] * len(cols)) + " |")
        for a in cols:
            cells = [
                _fmt(matrix[a][b]) if matrix[a][b] is not None else "—"
                for b in cols
            ]
            lines.append(f"| {a} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("相关系数为 Pearson 相关系数，相关不等于因果。")
    else:
        lines.append(f"- {corr.get('note') or '未计算相关性'}")
    for u in corr.get("unavailable", []):
        lines.append(f"- {u['columns'][0]} × {u['columns'][1]}：{u['reason']}")
    lines.append("")
    lines.append("## 回归")
    reg = report["regression"]
    if reg.get("available"):
        lines.append(f"- 方程：{reg['equation']}")
        lines.append(f"- R²：{_fmt(reg['r_squared'])}")
        lines.append(f"- 相关系数 r：{_fmt(reg['r'])}")
        lines.append(f"- 样本量 n：{_fmt(reg['n'])}")
        lines.append(f"- 斜率：{_fmt(reg['slope'])}，截距：{_fmt(reg['intercept'])}")
    else:
        lines.append(f"- {reg.get('note') or '未计算回归'}")
    lines.append("")
    lines.append("## 结论（带证据链）")
    for c in report["conclusions"]:
        ev = c["evidence"]
        lines.append(
            f"- [{c['id']}] {c['text']}（证据：{ev['statistic']}="
            f"{_fmt(ev['value']) if not isinstance(ev['value'], dict) else ev['value']}，"
            f"方法 {ev['method']}，数据集 {ev['dataset_id']}，"
            f"分析记录 {ev['analysis_ids']}）"
        )
    lines.append("")
    lines.append("## AI 解读")
    lines.append(
        "来源："
        + ("AI 生成（Gemini）" if report["source"] == "ai" else "规则版（未调用 AI 模型）")
    )
    lines.append("")
    lines.append(report["ai_text"])
    lines.append("")
    lines.append("## 数字校验")
    nc = report.get("number_check", {})
    if nc.get("unmatched"):
        lines.append(
            "- 以下数字出现在 AI 段落中，但在报告 JSON 数值中找不到对应值，"
            "仅作人工复核提示，不拦截报告生成："
        )
        for u in nc["unmatched"]:
            lines.append(f"  - {u['value']}")
    else:
        lines.append(f"- 已扫描 AI 段落中的 {nc.get('checked', 0)} 个数字，未发现与 JSON 不符的数字。")
    lines.append("")
    lines.append("## 复现信息")
    lines.append(f"- 数据集 SHA-256：`{d['file_hash']}`")
    lines.append(
        f"- 引擎版本：审计 {audit.get('engine_version')}、"
        f"统计 {stats.get('engine_version')}、报告 {report.get('engine_version')}"
    )
    lines.append(f"- 生成时间：{report.get('generated_at')}")
    lines.append(f"- 模型：{report['params'].get('model')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rerun comparison: recursive diff, numeric values within rel. tol. 1e-9.
# ---------------------------------------------------------------------------

def _numbers_close(a: float, b: float) -> bool:
    if a == b:
        return True
    tol = 1e-9 * max(1.0, abs(a), abs(b))
    return abs(a - b) <= tol


def diff_results(old, new, path: str = "") -> list[dict]:
    """Leaf-level differences between two analysis results.

    Volatile keys (timestamps, token usage, manifests, analysis ids) are
    skipped. Returns [{key, old, new}]; empty means the rerun is consistent.
    """
    diffs: list[dict] = []
    key = path.rstrip(".")
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            if k in _VOLATILE_KEYS:
                continue
            if k not in old:
                diffs.append({"key": f"{path}{k}", "old": None, "new": new[k]})
            elif k not in new:
                diffs.append({"key": f"{path}{k}", "old": old[k], "new": None})
            else:
                diffs.extend(diff_results(old[k], new[k], f"{path}{k}."))
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            diffs.append(
                {"key": key, "old": f"list[{len(old)}]", "new": f"list[{len(new)}]"}
            )
        else:
            for i, (a, b) in enumerate(zip(old, new)):
                diffs.extend(diff_results(a, b, f"{path}[{i}]."))
    elif isinstance(old, bool) or isinstance(new, bool):
        if old is not new:
            diffs.append({"key": key, "old": old, "new": new})
    elif isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if not _numbers_close(float(old), float(new)):
            diffs.append({"key": key, "old": old, "new": new})
    else:
        if old != new:
            diffs.append({"key": key, "old": old, "new": new})
    return diffs

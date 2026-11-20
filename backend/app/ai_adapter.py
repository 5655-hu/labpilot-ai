"""AI adapter layer — privacy boundary is a type contract, not a promise.

The ONLY input any model may receive is a StatsSummary: dataset metadata,
per-column aggregate statistics, audit findings and parameters. There is no
field for raw rows anywhere in this module, so raw data cannot reach a
third-party model even by accident. Every call also produces a send manifest
(what was sent, to which model, when) for the UI and the archive.

Wave 1: only the rule-based fallback is implemented. It builds its text from
the real numbers inside the StatsSummary — no model, no key, no network,
zero tokens, zero cost. Provider classes below are interface stubs; they are
NOT wired to any live API in Wave 1 (that is a Wave 4 job, after the user
confirms keys and routing).

Wave 3: GeminiProvider IS wired — it shells out to the custom.gemini
connector helper (gemini.py chat) with ONLY the StatsSummary JSON. Raw rows
still cannot reach the model: the StatsSummary type has no raw-row field.
A failed / timed-out / empty Gemini call raises, and the caller (report
assembly) falls back to the rule-based text.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GEMINI_HELPER_DEFAULT = (
    Path.home() / "workspace" / "custom-connectors" / "custom.gemini" / "bin" / "gemini.py"
)
# Deployment override: the helper lives outside this repository, so any
# machine / container can point at its own copy instead of the author's home.
# Empty / unset keeps the original default path.
GEMINI_HELPER = Path(
    os.environ.get("GEMINI_HELPER_PATH", "").strip() or GEMINI_HELPER_DEFAULT
).expanduser()
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MAX_TOKENS = 800
GEMINI_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ColumnSummary:
    """Aggregate statistics for ONE column. No raw values, no samples."""

    name: str
    dtype: str
    count: int
    missing: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class StatsSummary:
    """Everything a model is allowed to see. Deliberately row-free."""

    dataset_name: str
    rows: int
    cols: int
    file_hash: str
    columns: tuple[ColumnSummary, ...] = ()
    quality_score: float | None = None
    findings: tuple[str, ...] = ()
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SendManifest:
    """Audit record of one AI call: what left the system, and where it went."""

    model: str
    sent_fields: tuple[str, ...]
    summary_rows: int
    raw_rows_sent: int  # always 0 by construction; asserted in tests
    created_at: str
    tokens: dict | None = None  # usageMetadata counts, only for real model calls
    elapsed_seconds: float | None = None


def rule_based_summarize(summary: StatsSummary) -> str:
    """Deterministic explanation built ONLY from numbers in the summary.

    This is the Wave 1 fallback and the no-key behaviour: the text is
    assembled from real statistics, so it can never invent a number.
    """
    lines = [
        f"数据集「{summary.dataset_name}」共 {summary.rows} 行、{summary.cols} 列。",
    ]
    if summary.quality_score is not None:
        lines.append(f"数据质量评分 {summary.quality_score:.1f} 分（满分 100）。")
    for col in summary.columns:
        if col.mean is None:
            lines.append(
                f"列 {col.name}（{col.dtype}）：{col.count} 个非空值，缺失 {col.missing} 个。"
            )
        else:
            lines.append(
                f"列 {col.name}：均值 {col.mean:.4g}，中位数 {col.median:.4g}，"
                f"标准差 {col.std:.4g}，范围 {col.minimum:.4g} ~ {col.maximum:.4g}，"
                f"缺失 {col.missing} 个。"
            )
    if summary.findings:
        lines.append("审计发现：")
        lines.extend(f"- {f}" for f in summary.findings)
    else:
        lines.append("审计未发现明显问题。")
    lines.append("以上为规则版解读（未调用任何 AI 模型），数字全部来自后端真实计算。")
    return "\n".join(lines)


def make_send_manifest(
    model: str,
    summary: StatsSummary,
    tokens: dict | None = None,
    elapsed_seconds: float | None = None,
) -> SendManifest:
    """Record exactly what would be sent to a model (Wave 1: nothing is sent)."""
    return SendManifest(
        model=model,
        sent_fields=tuple(["dataset_name", "rows", "cols", "file_hash", "columns", "quality_score", "findings", "parameters"]),
        summary_rows=summary.rows,
        raw_rows_sent=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        tokens=tokens,
        elapsed_seconds=elapsed_seconds,
    )


def summary_to_dict(summary: StatsSummary) -> dict:
    """The ONLY payload a model ever receives: aggregates, never raw rows."""
    return {
        "dataset_name": summary.dataset_name,
        "rows": summary.rows,
        "cols": summary.cols,
        "file_hash": summary.file_hash,
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "count": c.count,
                "missing": c.missing,
                "mean": c.mean,
                "median": c.median,
                "std": c.std,
                "min": c.minimum,
                "max": c.maximum,
            }
            for c in summary.columns
        ],
        "quality_score": summary.quality_score,
        "findings": list(summary.findings),
        "parameters": dict(summary.parameters),
    }


def build_gemini_prompt(summary: StatsSummary) -> str:
    """Prompt for the model: qualitative paragraphs only, no numbers allowed.

    The model is explicitly forbidden from outputting, repeating, computing
    or rewriting any statistic — numbers in the report come from the backend
    JSON only (plan §8: structural isolation, not post-hoc text comparison).
    """
    payload = json.dumps(summary_to_dict(summary), ensure_ascii=False)
    return (
        "你是一名科研数据分析助手。以下是某数据集的统计摘要 JSON"
        "（仅含聚合统计量，无原始行数据）：\n"
        + payload
        + "\n请只产出定性段落：结果解读、异常与风险解释、结论表述、后续实验建议。"
        "严格要求：不许输出、复述、计算或改写任何统计数字（包括均值、标准差、"
        "相关系数、回归系数、质量分、行列数、缺失数）；不要出现任何阿拉伯数字"
        "或带单位的数值；用文字定性描述即可。段落控制在 300 字以内。"
    )


class ProviderStub:
    """Base for real providers (Gemini / DeepSeek / DashScope).

    Wave 1 intentionally leaves these unimplemented: no key is read, no
    request is made. Wave 4 wires them behind the same summarize() signature.
    """

    name = "stub"

    def available(self) -> bool:
        return False

    def summarize(self, summary: StatsSummary) -> str:
        raise NotImplementedError(
            f"{self.name} provider is not wired in Wave 1 — use rule_based_summarize()."
        )


class GeminiProvider(ProviderStub):
    """Wired in Wave 3: shells out to the custom.gemini connector helper.

    summarize() returns (text, tokens_dict, elapsed_seconds). Any failure —
    helper missing, non-zero exit, timeout, empty reply — raises
    RuntimeError so the caller can fall back to the rule-based text.
    Only the StatsSummary JSON is sent; raw rows never leave the system.
    """

    name = GEMINI_MODEL

    def available(self) -> bool:
        return GEMINI_HELPER.is_file()

    def summarize(self, summary: StatsSummary) -> tuple[str, dict, float]:
        if not self.available():
            raise RuntimeError(f"Gemini helper 不存在: {GEMINI_HELPER}")
        prompt = build_gemini_prompt(summary)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(GEMINI_HELPER),
                    "chat",
                    "--model",
                    self.name,
                    "--message",
                    prompt,
                    "--max-tokens",
                    str(GEMINI_MAX_TOKENS),
                ],
                capture_output=True,
                text=True,
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Gemini 调用超时（{GEMINI_TIMEOUT_SECONDS} 秒）: {exc}"
            ) from exc
        elapsed = round(time.monotonic() - started, 2)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Gemini 调用失败（exit {proc.returncode}）: "
                f"{(proc.stderr or '').strip()[:300]}"
            )
        stdout = proc.stdout or ""
        if "---usage---" in stdout:
            text_part, usage_part = stdout.split("---usage---", 1)
            try:
                usage = json.loads(usage_part.strip())
            except json.JSONDecodeError:
                usage = {}
        else:
            text_part, usage = stdout, {}
        text = text_part.strip()
        if not text:
            raise RuntimeError("Gemini 返回空回复")
        tokens = {
            "promptTokenCount": usage.get("promptTokenCount"),
            "candidatesTokenCount": usage.get("candidatesTokenCount"),
            "totalTokenCount": usage.get("totalTokenCount"),
        }
        return text, tokens, elapsed


class DeepSeekProvider(ProviderStub):
    name = "deepseek-v4-flash"


class DashScopeProvider(ProviderStub):
    name = "qwen-flash"


def summarize(summary: StatsSummary, provider: ProviderStub | None = None) -> tuple[str, SendManifest]:
    """Public entry: rule-based fallback unless a wired provider is given.

    A wired provider returns (text, tokens, elapsed); the manifest records
    the token usage. Any provider failure propagates to the caller, which
    decides the fallback — this function itself never silently swaps text.
    """
    if provider is not None and provider.available():
        result = provider.summarize(summary)
        if isinstance(result, tuple) and len(result) == 3:
            text, tokens, elapsed = result
            manifest = make_send_manifest(
                provider.name, summary, tokens=tokens, elapsed_seconds=elapsed
            )
        else:
            text = result
            manifest = make_send_manifest(provider.name, summary)
    else:
        text = rule_based_summarize(summary)
        manifest = make_send_manifest("rule-based-fallback", summary)
    assert manifest.raw_rows_sent == 0, "privacy invariant violated: raw rows must never be sent"
    return text, manifest

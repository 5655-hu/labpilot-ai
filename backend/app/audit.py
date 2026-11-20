"""Data quality audit engine (Wave 2).

Deterministic: the same dataframe + the same parameters always produce the
same result. No model is called anywhere in this module.

Public scoring rule (also returned in every audit result, never hidden):

    score = 100 - (missing_deduction + duplicate_deduction
                   + type_error_deduction + definite_error_deduction)
    missing_deduction       = w_missing  * effective_missing_rate
    duplicate_deduction     = w_duplicate * duplicate_row_rate
    type_error_deduction    = w_type_error * type_error_rate
    definite_error_deduction = w_definite_error * definite_error_rate

Rates (all in [0, 1]):
    effective_missing_rate = effective missing cells / effective total cells
        ("effective" excludes columns the user marked as allowed-missing)
    duplicate_row_rate     = duplicate rows / total rows
    type_error_rate        = type-error cells / total cells
    definite_error_rate    = definite-error cells / total cells

Statistical outliers (IQR / Z-score) NEVER deduct points and are NEVER
deleted: they are reported as "待确认" with a handling suggestion only.
Two tiers are kept strictly apart:
    definite errors: type errors, duplicate rows, impossible values
        (sentinel missing-codes, or values outside a configured range rule)
    statistical anomalies: IQR / Z-score outliers, flagged "待确认" only.

Row numbers in evidence are the 0-based DataFrame index (matching pandas
and golden_manifest.json); each example also carries row_number (1-based
data-row number) for display.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

ENGINE_VERSION = "0.2.0"

# Rule profiles by data type. Weights are defaults, shown in the UI and the
# archive, and adjustable per audit request.
PROFILES: dict[str, dict] = {
    "measurement": {
        "label": "测量型",
        "description": "实验室测量数据：缺失与类型错误从严，重复行同样计分。",
        "weights": {"missing": 30.0, "duplicate": 20.0, "type_error": 25.0, "definite_error": 25.0},
    },
    "survey": {
        "label": "问卷型",
        "description": "问卷调查数据：跳题缺失较常见，缺失权重放宽；重复提交与类型错误从严。",
        "weights": {"missing": 15.0, "duplicate": 25.0, "type_error": 30.0, "definite_error": 30.0},
    },
    "timeseries": {
        "label": "时序型",
        "description": "时序 / 传感器数据：重复时间戳危害最大，缺失次之。",
        "weights": {"missing": 25.0, "duplicate": 30.0, "type_error": 20.0, "definite_error": 25.0},
    },
}

DEFAULT_PROFILE = "measurement"
DEFAULT_ALGORITHMS = ("iqr",)
DEFAULT_IQR_K = 1.5
DEFAULT_Z_THRESHOLD = 3.0

# Numeric values commonly used as missing-value placeholders. A real
# measurement is essentially never exactly -999 / -9999 / 999999, so these
# are flagged as definite errors (with evidence) instead of being silently
# treated as data.
SENTINEL_VALUES = {-999.0, -9999.0, -99999.0, 999999.0}

# A string value that is a number followed by a unit, e.g. "25.3C" or
# "0.52 mol/L". Used for the unit-inconsistency risk check.
_UNIT_RE = re.compile(r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)\s*([A-Za-z%°µ/]+)\s*$")

# A column is "numeric-expected" when at least half of its non-null values
# coerce to numbers (and at least one does). Pure text columns (e.g. a
# control/treatment group label) are categorical, never type errors.
_NUMERIC_EXPECTED_MIN_FRACTION = 0.5

_EXAMPLE_LIMIT = 3


def _round(x: float) -> float:
    return round(float(x), 6)


def _examples(rows: list[dict]) -> list[dict]:
    return rows[:_EXAMPLE_LIMIT]


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _is_numeric_expected(series: pd.Series) -> bool:
    """True when a column is meant to be numeric (so stray text is a type error)."""
    if pd.api.types.is_numeric_dtype(series):
        return True
    non_null = series[series.notna()]
    if len(non_null) == 0:
        return False
    numeric = _coerce_numeric(series)
    return int(numeric.notna().sum()) >= 1 and float(numeric.notna().sum() / len(non_null)) >= _NUMERIC_EXPECTED_MIN_FRACTION


def _outliers_iqr(values: pd.Series, k: float) -> tuple[list[int], dict]:
    """Return (row indices, bounds) of IQR outliers. Needs >= 4 values."""
    v = values.dropna()
    if len(v) < 4:
        return [], {"skipped": "样本量不足（需要至少 4 个有效值）"}
    q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    idx = [int(i) for i in v[(v < lo) | (v > hi)].index]
    return idx, {"q1": _round(q1), "q3": _round(q3), "iqr": _round(iqr), "lower": _round(lo), "upper": _round(hi), "k": k}


def _outliers_zscore(values: pd.Series, threshold: float) -> tuple[list[int], dict]:
    """Return (row indices, stats) of |z| > threshold points. Needs >= 3 values."""
    v = values.dropna()
    if len(v) < 3:
        return [], {"skipped": "样本量不足（需要至少 3 个有效值）"}
    mean, std = float(v.mean()), float(v.std(ddof=1))
    if std == 0:
        return [], {"skipped": "常量列（标准差为 0），无法计算 Z-score"}
    z = (v - mean) / std
    idx = [int(i) for i in v[z.abs() > threshold].index]
    return idx, {"mean": _round(mean), "std": _round(std), "threshold": threshold}


def run_audit(
    df: pd.DataFrame,
    *,
    algorithms: tuple[str, ...] | list[str] = DEFAULT_ALGORITHMS,
    iqr_k: float = DEFAULT_IQR_K,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    profile: str = DEFAULT_PROFILE,
    weights: dict[str, float] | None = None,
    allowed_missing_columns: tuple[str, ...] | list[str] = (),
    range_rules: dict[str, dict[str, float]] | None = None,
    per_column_algorithms: dict[str, list[str]] | None = None,
) -> dict:
    """Audit one dataframe. Raises ValueError on empty input."""
    if df is None or len(df) == 0 or len(df.columns) == 0:
        raise ValueError("数据为空，无法审计（需要至少 1 行、1 列）")
    algos = [a.lower() for a in algorithms]
    for a in algos:
        if a not in ("iqr", "zscore"):
            raise ValueError(f"不支持的异常值算法: {a}（可用 iqr / zscore）")
    if not algos:
        raise ValueError("至少选择一种异常值检测算法")
    if iqr_k <= 0:
        raise ValueError("IQR 倍数 k 必须大于 0")
    if z_threshold <= 0:
        raise ValueError("Z-score 阈值必须大于 0")
    if profile not in PROFILES:
        raise ValueError(f"不支持的规则画像: {profile}（可用 {sorted(PROFILES)}）")
    w = dict(PROFILES[profile]["weights"])
    if weights:
        for key in ("missing", "duplicate", "type_error", "definite_error"):
            if key in weights:
                if not (0 <= float(weights[key]) <= 100):
                    raise ValueError(f"权重 {key} 必须在 0~100 之间")
                w[key] = float(weights[key])
    allowed = {c for c in allowed_missing_columns if c in df.columns}
    range_rules = range_rules or {}
    per_col = {c: [a.lower() for a in v] for c, v in (per_column_algorithms or {}).items()}

    n_rows, n_cols = int(len(df)), int(len(df.columns))
    total_cells = n_rows * n_cols
    allowed_cells = sum(n_rows for c in allowed)
    effective_cells = total_cells - allowed_cells

    # ---- missing values ----
    missing_by_col: dict[str, dict] = {}
    missing_cells = 0
    for col in df.columns:
        miss_idx = [int(i) for i in df.index[df[col].isna()]]
        missing_by_col[str(col)] = {
            "count": len(miss_idx),
            "rate": _round(len(miss_idx) / n_rows) if n_rows else 0.0,
            "row_indices": miss_idx,
            "allowed_missing": str(col) in allowed,
        }
        if str(col) not in allowed:
            missing_cells += len(miss_idx)
    effective_missing_rate = (missing_cells / effective_cells) if effective_cells else 0.0

    # ---- duplicate rows ----
    dup_mask = df.duplicated(keep="first")
    dup_idx = [int(i) for i in df.index[dup_mask]]
    duplicate_rate = len(dup_idx) / n_rows if n_rows else 0.0

    # ---- type errors, definite errors, unit risks, outliers ----
    type_error_cells = 0
    definite_error_cells = 0
    type_errors: dict[str, dict] = {}
    definite_errors: dict[str, dict] = {}
    unit_risks: list[dict] = []
    outliers: dict[str, dict] = {}
    column_summaries: list[dict] = []

    for col in df.columns:
        col = str(col)
        series = df[col]
        numeric = _coerce_numeric(series)
        numeric_expected = _is_numeric_expected(series)
        col_summary: dict = {
            "name": col,
            "dtype": str(series.dtype),
            "missing": missing_by_col[col]["count"],
            "numeric_expected": numeric_expected,
        }

        # type errors: non-null values that fail numeric coercion in a
        # numeric-expected column (e.g. "25.3C", "high", "0.52 mol/L").
        if numeric_expected:
            bad = series[numeric.isna() & series.notna()]
            bad_idx = [int(i) for i in bad.index]
            type_error_cells += len(bad_idx)
            type_errors[col] = {
                "count": len(bad_idx),
                "row_indices": bad_idx,
                "examples": _examples([
                    {"row_index": int(i), "row_number": int(i) + 1, "value": str(v)}
                    for i, v in bad.items()
                ]),
            }
        else:
            type_errors[col] = {"count": 0, "row_indices": [], "examples": []}

        # definite errors: sentinel missing-codes + configured range rules.
        def_idx: list[int] = []
        def_examples: list[dict] = []
        if numeric_expected:
            num_vals = numeric.dropna()
            for i, v in num_vals.items():
                if float(v) in SENTINEL_VALUES:
                    def_idx.append(int(i))
                    def_examples.append({
                        "row_index": int(i), "row_number": int(i) + 1,
                        "value": float(v), "reason": "疑似缺失占位码（如 -999）",
                    })
            rule = range_rules.get(col, {})
            lo_r, hi_r = rule.get("min"), rule.get("max")
            if lo_r is not None or hi_r is not None:
                for i, v in num_vals.items():
                    if (lo_r is not None and float(v) < lo_r) or (hi_r is not None and float(v) > hi_r):
                        if int(i) not in def_idx:
                            def_idx.append(int(i))
                            def_examples.append({
                                "row_index": int(i), "row_number": int(i) + 1,
                                "value": float(v),
                                "reason": f"超出设定范围 [{lo_r}, {hi_r}]",
                            })
        definite_error_cells += len(def_idx)
        definite_errors[col] = {
            "count": len(def_idx),
            "row_indices": sorted(def_idx),
            "examples": _examples(def_examples),
        }

        # unit-inconsistency risk: same column mixes plain numbers and
        # number+unit strings (e.g. 25.3 and "25.3C").
        if numeric_expected:
            units: dict[str, list[int]] = {}
            for i, v in series[series.notna()].items():
                m = _UNIT_RE.match(str(v))
                if m:
                    units.setdefault(m.group(1), []).append(int(i))
            if units:
                unit_risks.append({
                    "column": col,
                    "units": sorted(units),
                    "examples": _examples([
                        {"row_index": idx, "row_number": idx + 1, "value": str(series.iloc[idx])}
                        for unit in sorted(units) for idx in units[unit]
                    ]),
                    "suggestion": "同一列混有带单位与不带单位的数值，建议统一去除单位、单独记录单位列后再分析。",
                })

        # outliers (statistical anomalies only — never errors, never deleted).
        col_algos = per_col.get(col, algos)
        for a in col_algos:
            if a not in ("iqr", "zscore"):
                raise ValueError(f"不支持的异常值算法: {a}")
        numeric_vals = numeric.dropna()
        col_out: dict = {"algorithms": col_algos, "points": [], "by_algorithm": {}, "disagreement": []}
        flagged: dict[str, set[int]] = {}
        for a in col_algos:
            if not numeric_expected:
                col_out["by_algorithm"][a] = {"skipped": "非数值列，不做异常值检测"}
                flagged[a] = set()
                continue
            if a == "iqr":
                idx, info = _outliers_iqr(numeric_vals, iqr_k)
            else:
                idx, info = _outliers_zscore(numeric_vals, z_threshold)
            flagged[a] = set(idx)
            entry = {"indices": sorted(idx), **info}
            entry["examples"] = _examples([
                {"row_index": i, "row_number": i + 1, "value": _round(float(numeric.loc[i]))}
                for i in sorted(idx)
            ])
            col_out["by_algorithm"][a] = entry
        if len(col_algos) > 1:
            only_iqr = sorted(flagged.get("iqr", set()) - flagged.get("zscore", set()))
            only_z = sorted(flagged.get("zscore", set()) - flagged.get("iqr", set()))
            col_out["disagreement"] = [
                {"algorithm": "iqr", "row_indices": only_iqr,
                 "note": "仅 IQR 检出，Z-score 未检出（IQR 对偏态更敏感）"},
                {"algorithm": "zscore", "row_indices": only_z,
                 "note": "仅 Z-score 检出，IQR 未检出"},
            ]
        all_flagged = sorted(set().union(*flagged.values())) if flagged else []
        col_out["points"] = [
            {"row_index": i, "row_number": i + 1, "value": _round(float(numeric.loc[i])),
             "algorithms": [a for a in col_algos if i in flagged.get(a, set())]}
            for i in all_flagged
        ]
        col_out["count"] = len(all_flagged)
        outliers[col] = col_out
        col_summary["outlier_count"] = len(all_flagged)
        column_summaries.append(col_summary)

    type_error_rate = type_error_cells / total_cells if total_cells else 0.0
    definite_error_rate = definite_error_cells / total_cells if total_cells else 0.0

    # ---- score ----
    def _deduction(weight: float, rate: float) -> float:
        return round(weight * rate, 2)

    deductions = [
        {
            "category": "missing",
            "label": "缺失值",
            "weight": w["missing"],
            "rate": _round(effective_missing_rate),
            "rate_basis": f"有效缺失单元格 {missing_cells} / 有效单元格总数 {effective_cells}",
            "deduction": _deduction(w["missing"], effective_missing_rate),
            "reason": "单元格缺失会影响统计功效与结论可信度；缺失集中在少数列时更需注意。",
            "suggestion": "检查缺失是随机发生还是集中在某批样本；可按列设置允许缺失后重算，或补测、插补并记录方法。",
            "evidence": [
                {
                    "column": c,
                    "count": info["count"],
                    "rate": info["rate"],
                    "allowed_missing": info["allowed_missing"],
                    "example_rows": _examples([
                        {"row_index": i, "row_number": i + 1, "value": None}
                        for i in info["row_indices"]
                    ]),
                }
                for c, info in missing_by_col.items() if info["count"] > 0
            ],
        },
        {
            "category": "duplicate",
            "label": "重复值",
            "weight": w["duplicate"],
            "rate": _round(duplicate_rate),
            "rate_basis": f"重复行 {len(dup_idx)} / 总行数 {n_rows}",
            "deduction": _deduction(w["duplicate"], duplicate_rate),
            "reason": "重复行会虚增样本量、扭曲均值与相关性。",
            "suggestion": "核查重复是录入失误还是真实重复测量；确认后去重并记录去重规则。",
            "evidence": [
                {
                    "column": "(整行)",
                    "count": len(dup_idx),
                    "rate": _round(duplicate_rate),
                    "example_rows": _examples([
                        {"row_index": i, "row_number": i + 1,
                         "value": {str(c): str(df.iloc[i][c]) for c in df.columns}}
                        for i in dup_idx
                    ]),
                }
            ] if dup_idx else [],
        },
        {
            "category": "type_error",
            "label": "字段类型错误",
            "weight": w["type_error"],
            "rate": _round(type_error_rate),
            "rate_basis": f"类型错误单元格 {type_error_cells} / 全部单元格 {total_cells}",
            "deduction": _deduction(w["type_error"], type_error_rate),
            "reason": "数值列中混入文字（如带单位的数值、占位文字），会导致整列无法参与计算。",
            "suggestion": "清洗为纯数值并把单位单独成列；无法清洗的单元格按缺失处理并记录。",
            "evidence": [
                {
                    "column": c,
                    "count": info["count"],
                    "rate": _round(info["count"] / total_cells) if total_cells else 0.0,
                    "example_rows": info["examples"],
                }
                for c, info in type_errors.items() if info["count"] > 0
            ],
        },
        {
            "category": "definite_error",
            "label": "确定错误（不可能的值）",
            "weight": w["definite_error"],
            "rate": _round(definite_error_rate),
            "rate_basis": f"确定错误单元格 {definite_error_cells} / 全部单元格 {total_cells}",
            "deduction": _deduction(w["definite_error"], definite_error_rate),
            "reason": "占位码（如 -999）或超出设定范围的值不是真实测量值，参与计算会直接带偏结果。",
            "suggestion": "按缺失处理并记录原因，或修正为真实值；占位码的含义应写入数据说明。",
            "evidence": [
                {
                    "column": c,
                    "count": info["count"],
                    "rate": _round(info["count"] / total_cells) if total_cells else 0.0,
                    "example_rows": info["examples"],
                }
                for c, info in definite_errors.items() if info["count"] > 0
            ],
        },
    ]
    total_deduction = round(sum(d["deduction"] for d in deductions), 2)
    score = round(max(0.0, 100.0 - total_deduction), 2)
    formula = (
        f"质量分 = 100 − ({w['missing']:g}×有效缺失率 + {w['duplicate']:g}×重复行率"
        f" + {w['type_error']:g}×类型错误率 + {w['definite_error']:g}×确定错误率)"
    )

    pending = [
        {
            "column": col,
            "count": out["count"],
            "algorithms": out["algorithms"],
            "points": out["points"],
            "disagreement": out["disagreement"],
            "status": "待确认",
            "suggestion": "统计异常不一定是错误：先复核原始记录，确认是真实极端值则保留，是录入错误则修正；剔除须经人工决策并记录。",
        }
        for col, out in outliers.items() if out["count"] > 0
    ]

    return {
        "engine": "audit",
        "engine_version": ENGINE_VERSION,
        "rows": n_rows,
        "cols": n_cols,
        "total_cells": total_cells,
        "score": {
            "total": score,
            "formula": formula,
            "profile": {
                "name": profile,
                "label": PROFILES[profile]["label"],
                "description": PROFILES[profile]["description"],
                "weights": w,
            },
            "total_deduction": total_deduction,
            "deductions": deductions,
            "outliers_do_not_deduct": True,
        },
        "missing": {
            "total": sum(info["count"] for info in missing_by_col.values()),
            "effective_total": missing_cells,
            "by_column": missing_by_col,
        },
        "duplicates": {
            "count": len(dup_idx),
            "row_indices": dup_idx,
            "rate": _round(duplicate_rate),
        },
        "type_errors": type_errors,
        "definite_errors": definite_errors,
        "unit_risks": unit_risks,
        "outliers": outliers,
        "pending_outliers": pending,
        "columns": column_summaries,
        "params": {
            "algorithms": algos,
            "iqr_k": iqr_k,
            "z_threshold": z_threshold,
            "profile": profile,
            "weights": w,
            "allowed_missing_columns": sorted(allowed),
            "range_rules": range_rules,
            "per_column_algorithms": per_col,
        },
    }

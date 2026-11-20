"""Descriptive statistics + Pearson correlation (Wave 2).

Deterministic: same dataframe -> same numbers. No model is called here.

Edge cases are handled explicitly and reported, never silently dropped:
  - empty data (0 rows or 0 columns) -> ValueError (API maps to 400);
  - non-numeric columns are skipped with a reason, not forced into numbers;
  - a constant column (std == 0) reports std/variance 0 and is excluded
    from correlation with a reason;
  - correlation needs at least 2 numeric columns and at least 3 paired
    observations per pair, otherwise the cell is null with a reason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ENGINE_VERSION = "0.2.0"

_MIN_CORR_PAIRS = 3


def _round(x: float) -> float:
    return round(float(x), 6)


def _numeric_series(df: pd.DataFrame, col: str) -> tuple[pd.Series | None, str | None]:
    """Return (numeric values, skip-reason). Numeric dtype columns are used
    as-is; object columns are coerced when at least half of the non-null
    values are numeric (the rest are excluded and counted)."""
    s = df[col]
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce"), None
    non_null = s[s.notna()]
    if len(non_null) == 0:
        return None, "全为空值，无法计算"
    coerced = pd.to_numeric(s, errors="coerce")
    n_ok = int(coerced.notna().sum())
    if n_ok == 0:
        return None, "非数值列，已跳过"
    if n_ok / len(non_null) < 0.5:
        return None, "数值占比不足一半，按非数值列跳过"
    return coerced, None


def compute_stats(df: pd.DataFrame) -> dict:
    """Descriptive stats + Pearson correlation for one dataframe."""
    if df is None or len(df) == 0 or len(df.columns) == 0:
        raise ValueError("数据为空，无法计算统计量（需要至少 1 行、1 列）")
    n_rows = int(len(df))
    columns: dict[str, dict] = {}
    skipped: list[dict] = []
    numeric_cols: list[str] = []
    notes: list[str] = []

    for col in df.columns:
        col = str(col)
        values, reason = _numeric_series(df, col)
        if values is None:
            skipped.append({"column": col, "reason": reason or "已跳过"})
            continue
        v = values.dropna()
        n = int(len(v))
        if n == 0:
            skipped.append({"column": col, "reason": "有效数值为空，无法计算"})
            continue
        numeric_cols.append(col)
        if n == 1:
            entry = {
                "count": 1, "missing": int(df[col].isna().sum()),
                "mean": _round(v.iloc[0]), "median": _round(v.iloc[0]),
                "std": None, "variance": None, "min": _round(v.iloc[0]), "max": _round(v.iloc[0]),
                "constant": False, "note": "仅 1 个有效值，标准差与方差无法计算",
            }
        else:
            std = float(v.std(ddof=1))
            entry = {
                "count": n, "missing": int(df[col].isna().sum()),
                "mean": _round(v.mean()), "median": _round(v.median()),
                "std": _round(std), "variance": _round(float(v.var(ddof=1))),
                "min": _round(v.min()), "max": _round(v.max()),
                "constant": std == 0.0,
                "note": "常量列（标准差为 0），不参与相关性计算" if std == 0.0 else None,
            }
        # count values excluded as non-numeric in coerced object columns
        non_numeric_excluded = int((pd.to_numeric(df[col], errors="coerce").isna() & df[col].notna()).sum()) \
            if not pd.api.types.is_numeric_dtype(df[col]) else 0
        if non_numeric_excluded:
            entry["non_numeric_excluded"] = non_numeric_excluded
            notes.append(f"{col} 列剔除了 {non_numeric_excluded} 个非数值后计算")
        columns[col] = entry

    # ---- Pearson correlation matrix (pairwise complete observations) ----
    correlation: dict = {"method": "pearson", "matrix": {}, "unavailable": [], "note": None}
    corr_cols = [c for c in numeric_cols if not columns[c]["constant"]]
    if n_rows < _MIN_CORR_PAIRS:
        correlation["note"] = f"样本量不足（n={n_rows}，需要至少 {_MIN_CORR_PAIRS} 行），未计算相关性"
    elif len(numeric_cols) < 2:
        correlation["note"] = "数值列不足 2 列，未计算相关性"
    elif len(corr_cols) < 2:
        correlation["note"] = "可参与相关性的数值列不足 2 列（其余为常量列），未计算相关性"
    else:
        sub = df[corr_cols].apply(pd.to_numeric, errors="coerce")
        matrix: dict[str, dict[str, float | None]] = {}
        for a in corr_cols:
            matrix[a] = {}
            for b in corr_cols:
                if a == b:
                    matrix[a][b] = 1.0
                    continue
                pair = sub[[a, b]].dropna()
                if len(pair) < _MIN_CORR_PAIRS:
                    matrix[a][b] = None
                    correlation["unavailable"].append({
                        "columns": [a, b],
                        "reason": f"成对有效样本仅 {len(pair)} 个，需要至少 {_MIN_CORR_PAIRS} 个",
                    })
                else:
                    matrix[a][b] = _round(float(pair[a].corr(pair[b], method="pearson")))
        correlation["matrix"] = matrix

    return {
        "engine": "stats",
        "engine_version": ENGINE_VERSION,
        "rows": n_rows,
        "cols": int(len(df.columns)),
        "columns": columns,
        "skipped_columns": skipped,
        "correlation": correlation,
        "notes": notes,
        "method_notes": {
            "std": "样本标准差（ddof=1）",
            "correlation": "Pearson 相关系数，成对删除缺失值，每对至少 3 个有效样本",
        },
    }

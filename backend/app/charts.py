"""Chart data engine (Wave 3 in the plan / user Wave 2: charts).

Deterministic: the same dataframe + the same parameters always produce the
same numbers. No model is called anywhere in this module.

This module computes chart-ready data; it does NOT render images. The
frontend draws interactive Plotly.js charts from these payloads, so every
number on screen is a real computation on the selected dataset.

Reuse, not reinvention:
  - numeric-column detection comes from stats._numeric_series (same rule as
    the stats engine: a column is numeric when it is a numeric dtype, or at
    least half of its non-null values coerce to numbers);
  - Pearson correlation comes from stats.compute_stats (same pairwise
    deletion, same >= 3 paired observations rule);
  - boxplot outliers come from audit._outliers_iqr, so the boxplot shows
    exactly the same points the audit page lists as "待确认" (IQR, k=1.5).

Missing values are always excluded pairwise / per column and the excluded
count is reported in the payload (never silently dropped).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .audit import _outliers_iqr
from .stats import _numeric_series, compute_stats

ENGINE_VERSION = "0.3.0"

_DEFAULT_IQR_K = 1.5
_MIN_REGRESSION_PAIRS = 3


def _round(x: float) -> float:
    return round(float(x), 6)


def _require_column(df: pd.DataFrame, col: str) -> str:
    if col not in df.columns:
        raise ValueError(f"列不存在: {col}（可用列：{', '.join(str(c) for c in df.columns)}）")
    return col


def _numeric_values(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric values of a column, or raise ValueError if not numeric."""
    _require_column(df, col)
    values, reason = _numeric_series(df, col)
    if values is None:
        raise ValueError(f"列 {col} 不是数值列，无法作图（{reason or '已跳过'}）")
    return values


def list_columns(df: pd.DataFrame) -> list[dict]:
    """Per-column chart usability (drives the frontend field dropdowns)."""
    out = []
    for col in df.columns:
        col = str(col)
        values, reason = _numeric_series(df, col)
        out.append({
            "name": col,
            "dtype": str(df[col].dtype),
            "numeric": values is not None,
            "reason": None if values is not None else (reason or "非数值列"),
            "valid_count": int(values.dropna().shape[0]) if values is not None else 0,
            "missing": int(df[col].isna().sum()),
        })
    return out


def histogram(df: pd.DataFrame, col: str, bins: int | None = None) -> dict:
    """Histogram: bin edges + counts. Default binning is Freedman-Diaconis
    (falls back to Sturges when IQR == 0); bin count is capped to [1, 100]."""
    if df is None or len(df) == 0:
        raise ValueError("数据为空，无法绘图（需要至少 1 行）")
    values = _numeric_values(df, col).dropna()
    n = int(len(values))
    if n == 0:
        raise ValueError(f"列 {col} 没有有效数值，无法绘直方图")
    if bins is not None:
        if not isinstance(bins, int) or bins < 1 or bins > 100:
            raise ValueError("分箱数 bins 必须是 1~100 的整数")
        method = "manual"
        n_bins = bins
    else:
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        if iqr > 0:
            width = 2 * iqr / (n ** (1 / 3))
            n_bins = int(np.ceil((float(values.max()) - float(values.min())) / width)) if width > 0 else 1
            method = "freedman-diaconis"
        else:
            n_bins = int(np.ceil(np.log2(n))) + 1
            method = "sturges"
        n_bins = max(1, min(100, n_bins))
    counts, edges = np.histogram(values.to_numpy(dtype=float), bins=n_bins)
    return {
        "type": "histogram",
        "column": col,
        "bins": n_bins,
        "method": method,
        "bin_edges": [_round(float(e)) for e in edges],
        "counts": [int(c) for c in counts],
        "n": n,
        "missing": int(df[col].isna().sum()),
        "min": _round(float(values.min())),
        "max": _round(float(values.max())),
    }


def boxplot(df: pd.DataFrame, columns: list[str] | None = None) -> dict:
    """Boxplot stats per numeric column. Outliers use audit._outliers_iqr
    (k=1.5), so they are identical to the audit engine's pending list."""
    if df is None or len(df) == 0:
        raise ValueError("数据为空，无法绘图（需要至少 1 行）")
    if columns is not None:
        for c in columns:
            _require_column(df, c)
        wanted = [str(c) for c in columns]
    else:
        wanted = [str(c) for c in df.columns]
    boxes: list[dict] = []
    skipped: list[dict] = []
    for col in wanted:
        values, reason = _numeric_series(df, col)
        if values is None:
            if columns is not None:
                raise ValueError(f"列 {col} 不是数值列，无法画箱线图（{reason or '已跳过'}）")
            skipped.append({"column": col, "reason": reason or "非数值列，已跳过"})
            continue
        v = values.dropna()
        n = int(len(v))
        if n < 4:
            skipped.append({"column": col, "reason": f"有效值仅 {n} 个，需要至少 4 个才能画箱线图"})
            continue
        idx, info = _outliers_iqr(v, _DEFAULT_IQR_K)
        q1, q3 = info["q1"], info["q3"]
        median = _round(float(v.median()))
        boxes.append({
            "column": col,
            "q1": q1,
            "median": median,
            "q3": q3,
            "lower": info["lower"],
            "upper": info["upper"],
            "iqr": info["iqr"],
            "k": _DEFAULT_IQR_K,
            "n": n,
            "missing": int(df[col].isna().sum()),
            "outliers": [
                {"row_index": i, "row_number": i + 1, "value": _round(float(values.loc[i]))}
                for i in idx
            ],
            "outlier_count": len(idx),
        })
    if not boxes:
        raise ValueError("没有可画箱线图的数值列（需要至少 4 个有效值的数值列）")
    return {"type": "boxplot", "boxes": boxes, "skipped_columns": skipped}


def _paired_points(df: pd.DataFrame, x: str, y: str) -> tuple[pd.DataFrame, int]:
    """Pairwise-complete (x, y) rows. Returns (points df, excluded count)."""
    xs = _numeric_values(df, x)
    ys = _numeric_values(df, y)
    paired = pd.DataFrame({"x": xs, "y": ys}).dropna()
    excluded = int(len(df) - len(paired))
    return paired, excluded


def scatter(df: pd.DataFrame, x: str, y: str) -> dict:
    """Scatter points (x, y) in original row order, pairwise deletion."""
    if df is None or len(df) == 0:
        raise ValueError("数据为空，无法绘图（需要至少 1 行）")
    paired, excluded = _paired_points(df, x, y)
    return {
        "type": "scatter",
        "x_column": x,
        "y_column": y,
        "points": [
            {"row_index": int(i), "row_number": int(i) + 1,
             "x": _round(float(r.x)), "y": _round(float(r.y))}
            for i, r in paired.iterrows()
        ],
        "n": int(len(paired)),
        "excluded": excluded,
    }


def line(df: pd.DataFrame, x: str, y: str) -> dict:
    """Line chart: same paired points as scatter, sorted by x ascending
    (stable: ties keep original row order)."""
    result = scatter(df, x, y)
    result["type"] = "line"
    result["points"] = sorted(result["points"], key=lambda p: (p["x"], p["row_index"]))
    result["sorted_by"] = x
    return result


def heatmap(df: pd.DataFrame) -> dict:
    """Pearson correlation matrix, reusing stats.compute_stats so the
    heatmap can never disagree with the stats page."""
    if df is None or len(df) == 0:
        raise ValueError("数据为空，无法绘图（需要至少 1 行）")
    stats = compute_stats(df)
    corr = stats["correlation"]
    columns = list(corr["matrix"].keys())
    matrix = [[corr["matrix"][a][b] for b in columns] for a in columns]
    return {
        "type": "heatmap",
        "method": corr["method"],
        "columns": columns,
        "matrix": matrix,
        "unavailable": corr["unavailable"],
        "note": corr["note"],
        "skipped_columns": stats["skipped_columns"],
    }


def regression(df: pd.DataFrame, x: str, y: str) -> dict:
    """Ordinary least squares regression of y on x (pairwise deletion).

    Returns slope, intercept, R², n, the equation string, the fitted-line
    endpoints for drawing, and the scatter points so the frontend can draw
    points + fit line on the same axes.
    """
    if df is None or len(df) == 0:
        raise ValueError("数据为空，无法绘图（需要至少 1 行）")
    paired, excluded = _paired_points(df, x, y)
    n = int(len(paired))
    if n < _MIN_REGRESSION_PAIRS:
        raise ValueError(f"成对有效样本仅 {n} 个，需要至少 {_MIN_REGRESSION_PAIRS} 个才能做线性回归")
    xv = paired["x"].to_numpy(dtype=float)
    yv = paired["y"].to_numpy(dtype=float)
    if float(np.std(xv, ddof=1)) == 0:
        raise ValueError(f"列 {x} 是常量列，无法做线性回归")
    slope, intercept = np.polyfit(xv, yv, 1)
    slope, intercept = float(slope), float(intercept)
    y_pred = slope * xv + intercept
    ss_res = float(np.sum((yv - y_pred) ** 2))
    ss_tot = float(np.sum((yv - float(np.mean(yv))) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    r = float(np.corrcoef(xv, yv)[0, 1])
    x_min, x_max = float(np.min(xv)), float(np.max(xv))
    sign = "+" if intercept >= 0 else "−"
    equation = f"{y} = {slope:.4f}·{x} {sign} {abs(intercept):.4f}"
    return {
        "type": "regression",
        "x_column": x,
        "y_column": y,
        "slope": _round(slope),
        "intercept": _round(intercept),
        "r_squared": _round(r2),
        "r": _round(r),
        "n": n,
        "excluded": excluded,
        "equation": equation,
        "fit_line": {
            "x": [_round(x_min), _round(x_max)],
            "y": [_round(slope * x_min + intercept), _round(slope * x_max + intercept)],
        },
        "points": [
            {"row_index": int(i), "row_number": int(i) + 1,
             "x": _round(float(r.x)), "y": _round(float(r.y))}
            for i, r in paired.iterrows()
        ],
    }

"""Two-group comparison engine (Wave 3): control vs treatment.

Deterministic: the same dataframe + parameters always produce the same
numbers. No model is called here.

Fixed flow (plan §7A): check assumptions first, then auto-select the test,
and explain the choice all the way through:
  1. Shapiro-Wilk normality per group (unreliable when n < 8, impossible
     when n < 3 — the latter is rejected as a 400 before any test runs);
  2. Levene homogeneity of variance (centre = median);
  3. both groups approximately normal (p > 0.05) and variances equal
     -> independent-samples t test;
     approximately normal but variances unequal -> Welch t test;
     either group clearly non-normal -> Mann-Whitney U test, with a note
     that it compares distributions / ranks, not the means themselves.
  4. Effect size is mandatory: Cohen's d for parametric tests,
     rank-biserial correlation for Mann-Whitney U.

Missing values are excluded per group (pairwise with the group column)
and the excluded count is reported, never silently dropped. Numeric
detection reuses stats._numeric_series, the same rule as the stats and
charts engines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as _scipy_stats

from .stats import _numeric_series

ENGINE_VERSION = "0.4.0"

ALPHA = 0.05
_MIN_GROUP_N = 3
_SHAPIRO_RELIABLE_N = 8
_SHAPIRO_MAX_N = 5000

TEST_NAMES = {
    "t": "独立样本 t 检验",
    "welch": "Welch t 检验",
    "mannwhitney": "Mann-Whitney U 检验",
}
_VALID_TESTS = tuple(TEST_NAMES)

def _round(x: float) -> float:
    return round(float(x), 6)


def _fmt_p(p: float) -> str:
    """Human-readable p-value: never display a tiny p as 0.0."""
    return "p<0.000001" if float(p) < 0.000001 else f"p={round(float(p), 6)}"


def _jsonable(v):
    """Convert a group label to a plain JSON-safe Python value."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v




def _clamp_p(p: float) -> float:
    """Keep a p-value inside [0, 1] against float error."""
    return min(1.0, max(0.0, float(p)))


def _descriptive(values: pd.Series) -> dict:
    v = values.dropna()
    n = int(len(v))
    std = float(v.std(ddof=1)) if n > 1 else None
    return {
        "n": n,
        "mean": _round(float(v.mean())),
        "median": _round(float(v.median())),
        "std": _round(std) if std is not None else None,
        "min": _round(float(v.min())),
        "max": _round(float(v.max())),
    }


def _shapiro(values: pd.Series) -> dict:
    """Shapiro-Wilk normality for one group.

    Returns statistic W and p; judgement text notes when the test is
    unreliable (n < 8). n < 3 cannot be tested and is reported as unknown
    (the engine rejects n < 3 before reaching here, so this is defensive).
    """
    v = values.dropna().to_numpy(dtype=float)
    n = int(len(v))
    if n < _MIN_GROUP_N:
        return {
            "statistic": None, "p_value": None, "normal": None,
            "reliable": False,
            "judgement": f"样本量 n={n} 小于 3，无法做 Shapiro-Wilk 检验，正态性未知",
        }
    if n > _SHAPIRO_MAX_N:
        return {
            "statistic": None, "p_value": None, "normal": None,
            "reliable": False,
            "judgement": f"样本量 n={n} 超过 {_SHAPIRO_MAX_N}，Shapiro-Wilk 检验不适用，正态性未知",
        }
    if float(np.std(v, ddof=1)) == 0.0:
        return {
            "statistic": None, "p_value": None, "normal": None,
            "reliable": False,
            "judgement": "该组为常量（标准差为 0），Shapiro-Wilk 检验不适用，正态性未知",
        }
    try:
        w, p = _scipy_stats.shapiro(v)
    except Exception:
        return {
            "statistic": None, "p_value": None, "normal": None,
            "reliable": False,
            "judgement": "Shapiro-Wilk 检验计算失败，正态性未知",
        }
    p = _clamp_p(p)
    normal = bool(p > ALPHA)
    base = (
        f"W={_round(w)}，{_fmt_p(p)}，p>0.05，近似服从正态分布"
        if normal
        else f"W={_round(w)}，{_fmt_p(p)}，p≤0.05，明显偏离正态分布"
    )
    if n < _SHAPIRO_RELIABLE_N:
        base += f"（样本量 n={n} 小于 {_SHAPIRO_RELIABLE_N}，该检验结果不可靠，仅供参考）"
    return {
        "statistic": _round(w), "p_value": p, "normal": normal,
        "reliable": bool(n >= _SHAPIRO_RELIABLE_N), "judgement": base,
    }


def _levene(a: np.ndarray, b: np.ndarray) -> dict:
    """Levene homogeneity of variance (centre = median, robust variant)."""
    if float(np.std(a, ddof=1)) == 0.0 and float(np.std(b, ddof=1)) == 0.0:
        return {
            "statistic": None, "p_value": None, "equal_variance": None,
            "judgement": "两组均为常量（标准差为 0），Levene 检验不适用，方差齐性未知",
        }
    try:
        stat, p = _scipy_stats.levene(a, b, center="median")
    except Exception:
        return {
            "statistic": None, "p_value": None, "equal_variance": None,
            "judgement": "Levene 检验计算失败，方差齐性未知",
        }
    p = _clamp_p(p)
    equal = bool(p > ALPHA)
    return {
        "statistic": _round(stat), "p_value": p, "equal_variance": equal,
        "judgement": (
            f"统计量={_round(stat)}，{_fmt_p(p)}，p>0.05，两组方差齐"
            if equal
            else f"统计量={_round(stat)}，{_fmt_p(p)}，p≤0.05，两组方差不齐"
        ),
    }


def _cohens_d(a: np.ndarray, b: np.ndarray) -> tuple[float | None, str]:
    """Cohen's d with pooled standard deviation (ddof=1 per group)."""
    n1, n2 = len(a), len(b)
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    s1 = float(np.std(a, ddof=1)) if n1 > 1 else 0.0
    s2 = float(np.std(b, ddof=1)) if n2 > 1 else 0.0
    pooled_var = ((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / max(n1 + n2 - 2, 1)
    pooled = float(np.sqrt(pooled_var)) if pooled_var > 0 else 0.0
    if pooled == 0.0:
        if m1 == m2:
            return 0.0, "两组均为常量且均值相同，Cohen's d = 0"
        return None, "两组均为常量但均值不同，合并标准差为 0，Cohen's d 无定义（效应无限大）"
    d = (m1 - m2) / pooled
    return _round(d), "Cohen's d = (均值1 − 均值2) / 合并标准差"


def _rank_biserial(u: float, n1: int, n2: int) -> float:
    """Rank-biserial correlation from Mann-Whitney U (first group)."""
    return _round(1.0 - 2.0 * float(u) / (n1 * n2))


def _effect_interpretation(method: str, value: float | None) -> str:
    if value is None:
        return "效应量无法计算"
    mag = abs(value)
    if method == "cohens_d":
        if mag < 0.2:
            return "效应量很小（|d| < 0.2）"
        if mag < 0.5:
            return "效应量较小（0.2 ≤ |d| < 0.5）"
        if mag < 0.8:
            return "效应量中等（0.5 ≤ |d| < 0.8）"
        return "效应量较大（|d| ≥ 0.8）"
    if mag < 0.1:
        return "效应量很小（|r| < 0.1）"
    if mag < 0.3:
        return "效应量较小（0.1 ≤ |r| < 0.3）"
    if mag < 0.5:
        return "效应量中等（0.3 ≤ |r| < 0.5）"
    return "效应量较大（|r| ≥ 0.5）"


def compare_groups(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    groups: list | None = None,
    override_test: str | None = None,
) -> dict:
    """Compare `value_col` between exactly two groups of `group_col`.

    Raises ValueError for every boundary condition (the API maps it to 400):
    missing columns, fewer than 2 group values, more than 2 values without
    an explicit `groups` selection, an invalid `groups` selection, any
    group with fewer than 3 valid values, a non-numeric value column, or
    an unknown `override_test`.
    """
    if df is None or len(df) == 0 or len(df.columns) == 0:
        raise ValueError("数据为空，无法做分组比较（需要至少 1 行、1 列）")
    if group_col not in df.columns:
        raise ValueError(
            f"分组列不存在: {group_col}（可用列：{', '.join(str(c) for c in df.columns)}）"
        )
    if value_col not in df.columns:
        raise ValueError(
            f"数值列不存在: {value_col}（可用列：{', '.join(str(c) for c in df.columns)}）"
        )
    if override_test is not None and override_test not in _VALID_TESTS:
        raise ValueError(
            f"不支持的检验 override_test={override_test}，可选：{', '.join(_VALID_TESTS)}"
        )

    # ---- resolve the two groups ----
    distinct = [_jsonable(v) for v in pd.unique(df[group_col].dropna())]
    if groups is not None:
        if len(groups) != 2:
            raise ValueError(
                f"groups 必须恰好指定 2 个分组，实际指定了 {len(groups)} 个：{groups}"
            )
        missing = [g for g in groups if g not in distinct]
        if missing:
            raise ValueError(
                f"groups 中 {missing} 不在分组列 {group_col} 的取值内"
                f"（全部取值：{distinct}）"
            )
        selected = list(groups)
    else:
        if len(distinct) < 2:
            raise ValueError(
                f"分组列 {group_col} 只有 {len(distinct)} 个取值"
                f"（{distinct}），需要至少 2 组才能比较"
            )
        if len(distinct) > 2:
            raise ValueError(
                f"分组列 {group_col} 有 {len(distinct)} 个取值（{distinct}），"
                "超过 2 组，请用 groups 参数明确指定要比较的 2 组"
            )
        selected = list(distinct)
    g1, g2 = selected

    # ---- numeric values, per group (missing excluded, counted) ----
    values, reason = _numeric_series(df, value_col)
    if values is None:
        raise ValueError(f"列 {value_col} 不是数值列，无法做分组比较（{reason or '已跳过'}）")
    frame = pd.DataFrame({"group": df[group_col], "value": values})
    group_values: dict = {}
    excluded: dict = {}
    for g in selected:
        sub = frame[frame["group"] == g]["value"]
        valid = sub.dropna()
        excluded[str(g)] = int(sub.isna().sum())
        if len(valid) == 0:
            raise ValueError(f"分组 {g} 在列 {value_col} 上没有有效数值，无法比较")
        group_values[g] = valid
    for g in selected:
        if len(group_values[g]) < _MIN_GROUP_N:
            raise ValueError(
                f"分组 {g} 的有效样本量仅 {len(group_values[g])} 个，"
                f"需要至少 {_MIN_GROUP_N} 个才能做分组比较"
            )

    a = group_values[g1].to_numpy(dtype=float)
    b = group_values[g2].to_numpy(dtype=float)
    n1, n2 = int(len(a)), int(len(b))

    # ---- step 1: normality per group ----
    shapiro = {str(g): _shapiro(group_values[g]) for g in selected}
    normal_flags = [shapiro[str(g)]["normal"] for g in selected]
    both_normal = all(flag is True for flag in normal_flags)

    # ---- step 2: homogeneity of variance ----
    levene = _levene(a, b)
    equal_var = levene["equal_variance"]

    # ---- step 3: auto-select the test ----
    if both_normal and equal_var is True:
        auto_test = "t"
        selection_reason = (
            "两组均近似正态（Shapiro-Wilk p>0.05）且方差齐（Levene p>0.05），"
            "满足独立样本 t 检验的前提，选用独立样本 t 检验。"
        )
    elif both_normal and equal_var is False:
        auto_test = "welch"
        selection_reason = (
            "两组均近似正态（Shapiro-Wilk p>0.05）但方差不齐（Levene p≤0.05），"
            "不满足等方差前提，选用不假设等方差的 Welch t 检验。"
        )
    else:
        auto_test = "mannwhitney"
        if any(flag is False for flag in normal_flags):
            non_normal = [str(g) for g in selected if shapiro[str(g)]["normal"] is False]
            selection_reason = (
                f"分组 {non_normal} 明显偏离正态分布（Shapiro-Wilk p≤0.05），"
                "不满足 t 检验的正态性前提，选用非参数 Mann-Whitney U 检验。"
                "该检验比较的是两组数据的分布与秩次，而非均值本身。"
            )
        else:
            selection_reason = (
                "正态性或方差齐性前提无法确认（检验结果未知），为稳健起见选用"
                "非参数 Mann-Whitney U 检验。该检验比较的是两组数据的分布与"
                "秩次，而非均值本身。"
            )

    # ---- step 4: run the (possibly overridden) test ----
    selected_test = override_test if override_test is not None else auto_test
    overridden = override_test is not None and override_test != auto_test
    if selected_test in ("t", "welch"):
        stat, p = _scipy_stats.ttest_ind(
            a, b, equal_var=(selected_test == "t")
        )
        effect_value, effect_note = _cohens_d(a, b)
        effect_method = "cohens_d"
        effect_name = "Cohen's d"
    else:
        stat, p = _scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
        effect_value = _rank_biserial(stat, n1, n2)
        effect_note = (
            "秩二列相关 r = 1 − 2U/(n1·n2)，U 为第一组的 Mann-Whitney U 统计量；"
            "比较的是分布与秩次，而非均值本身"
        )
        effect_method = "rank_biserial"
        effect_name = "秩二列相关"
    p = _clamp_p(p)
    significant = bool(p < ALPHA)
    if not np.isfinite(float(stat)):
        raise ValueError(f"检验统计量计算失败（{TEST_NAMES[selected_test]}返回了非有限值）")

    effect = {
        "method": effect_method,
        "name": effect_name,
        "value": effect_value,
        "interpretation": _effect_interpretation(effect_method, effect_value),
        "note": effect_note,
    }

    # ---- conclusion (no causal overclaim) ----
    diff = float(np.mean(a) - np.mean(b))
    conclusion = (
        f"在显著性水平 α={ALPHA} 下，{g1} 组（n={n1}，均值={_round(float(np.mean(a)))}）"
        f"与 {g2} 组（n={n2}，均值={_round(float(np.mean(b)))}）的 {value_col} "
        f"差异{'具有统计学显著性' if significant else '不具有统计学显著性'}"
        f"（{TEST_NAMES[selected_test]}，{_fmt_p(p)}），"
        f"效应量{effect_name}={effect_value}（{effect['interpretation']}）。"
        "组间差异不等于因果：本比较仅说明两组观测值存在或不存在统计学差异，"
        "不能据此推断分组导致了该差异。"
    )
    if selected_test == "mannwhitney":
        conclusion += (
            "注意：Mann-Whitney U 检验比较的是两组数据的分布与秩次，而非均值本身；"
            "上面列出的均值仅作描述参考。"
        )

    # ---- warnings ----
    warnings: list[str] = []
    for g in selected:
        n = len(group_values[g])
        if n < _SHAPIRO_RELIABLE_N:
            warnings.append(
                f"分组 {g} 样本量 n={n} 小于 {_SHAPIRO_RELIABLE_N}，"
                "Shapiro-Wilk 正态性检验结果不可靠，检验选择仅供参考"
            )
        if n < 30:
            warnings.append(
                f"分组 {g} 样本量 n={n} 小于 30，统计功效有限，小效应可能检不出来"
            )
    if shapiro[str(g1)]["normal"] is None or shapiro[str(g2)]["normal"] is None:
        warnings.append("至少一组正态性未知，已按稳健原则选用非参数检验")
    if overridden:
        warnings.append(
            f"用户改选了检验：自动建议为{TEST_NAMES[auto_test]}，"
            f"实际使用{TEST_NAMES[selected_test]}，结论按改选后的检验给出"
        )

    return {
        "engine": "groups",
        "engine_version": ENGINE_VERSION,
        "group_col": group_col,
        "value_col": value_col,
        "groups": selected,
        "alpha": ALPHA,
        "descriptive": {str(g): _descriptive(group_values[g]) for g in selected},
        "assumptions": {
            "shapiro": shapiro,
            "levene": levene,
            "judgement": (
                "正态性："
                + "；".join(f"{g} 组{shapiro[str(g)]['judgement']}" for g in selected)
                + "。方差齐性：" + levene["judgement"] + "。"
            ),
        },
        "auto_suggestion": auto_test,
        "auto_suggestion_name": TEST_NAMES[auto_test],
        "selected_test": selected_test,
        "selected_test_name": TEST_NAMES[selected_test],
        "selection_reason": selection_reason,
        "overridden": overridden,
        "test_result": {
            "test": selected_test,
            "test_name": TEST_NAMES[selected_test],
            "statistic": _round(float(stat)),
            "p_value": p,
            "significant": significant,
            "alpha": ALPHA,
        },
        "effect_size": effect,
        "conclusion": conclusion,
        "warnings": warnings,
        "missing_excluded": excluded,
        "n_total": n1 + n2,
        "method": "compare_groups",
        "params": {
            "group_col": group_col,
            "value_col": value_col,
            "groups": selected,
            "override_test": override_test,
            "auto_test": auto_test,
            "selected_test": selected_test,
            "overridden": overridden,
            "alpha": ALPHA,
            "levene_center": "median",
            "normality_method": "shapiro-wilk",
            "variance_method": "levene",
            "effect_method": effect_method,
        },
    }

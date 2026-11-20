"""Group-comparison tests (Wave 3): test selection, effect sizes, golden
data, boundaries, override, and the compare router (mounted alone on a
temporary FastAPI app — main.py is untouched).

No p-value expectation is hard-coded: golden assertions check structure
and self-consistency only.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import connect, init_db
from app.groups import compare_groups
from app.routers import compare as compare_router
from app.routers.datasets import get_conn
from app.stats import compute_stats
from app import store

BACKEND_DIR = Path(__file__).resolve().parent.parent
GOLDEN_DIR = BACKEND_DIR / "data" / "golden"

_rng = np.random.default_rng(0)


def _two_group(a, b):
    return pd.DataFrame(
        {"g": ["A"] * len(a) + ["B"] * len(b), "v": list(a) + list(b)}
    )


# ---------------------------------------------------------------- engine: selection
def test_selects_t_for_normal_equal_variance():
    df = _two_group(_rng.normal(10, 1, 60), _rng.normal(10.5, 1, 60))
    r = compare_groups(df, "g", "v")
    assert r["auto_suggestion"] == "t"
    assert r["selected_test"] == "t"
    assert r["assumptions"]["shapiro"]["A"]["normal"] is True
    assert r["assumptions"]["shapiro"]["B"]["normal"] is True
    assert r["assumptions"]["levene"]["equal_variance"] is True
    assert "t 检验" in r["selection_reason"]


def test_selects_welch_for_normal_unequal_variance():
    df = _two_group(_rng.normal(10, 1, 60), _rng.normal(10.5, 5, 60))
    r = compare_groups(df, "g", "v")
    assert r["auto_suggestion"] == "welch"
    assert r["selected_test"] == "welch"
    assert r["assumptions"]["shapiro"]["A"]["normal"] is True
    assert r["assumptions"]["shapiro"]["B"]["normal"] is True
    assert r["assumptions"]["levene"]["equal_variance"] is False
    assert "Welch" in r["selection_reason"]


def test_selects_mannwhitney_for_skewed_data():
    df = _two_group(_rng.exponential(1.0, 40), _rng.exponential(1.5, 40))
    r = compare_groups(df, "g", "v")
    assert r["auto_suggestion"] == "mannwhitney"
    assert r["selected_test"] == "mannwhitney"
    assert r["assumptions"]["shapiro"]["A"]["normal"] is False
    assert "秩次" in r["selection_reason"]
    assert "秩次" in r["conclusion"]
    assert r["effect_size"]["method"] == "rank_biserial"


# ---------------------------------------------------------------- engine: effect size
def test_cohens_d_matches_hand_calculation():
    a = _rng.normal(10, 1, 50)
    b = _rng.normal(12, 1, 50)
    r = compare_groups(_two_group(a, b), "g", "v")
    assert r["selected_test"] in ("t", "welch")
    n1, n2 = len(a), len(b)
    pooled = np.sqrt(
        ((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2)
    )
    expected = (a.mean() - b.mean()) / pooled
    assert r["effect_size"]["method"] == "cohens_d"
    assert np.isfinite(r["effect_size"]["value"])
    assert abs(r["effect_size"]["value"] - expected) < 1e-5


def test_effect_sizes_are_finite():
    for df in (
        _two_group(_rng.normal(10, 1, 30), _rng.normal(11, 1, 30)),
        _two_group(_rng.exponential(1.0, 30), _rng.exponential(2.0, 30)),
    ):
        r = compare_groups(df, "g", "v")
        assert np.isfinite(r["effect_size"]["value"])
        assert 0.0 <= r["test_result"]["p_value"] <= 1.0


# ---------------------------------------------------------------- engine: golden corr
def test_corr_golden_structure_and_consistency():
    df = pd.read_csv(GOLDEN_DIR / "corr.csv")
    r = compare_groups(df, "group", "response")
    assert r["groups"] == ["control", "treatment"]
    assert r["descriptive"]["control"]["n"] == 75
    assert r["descriptive"]["treatment"]["n"] == 75
    assert r["auto_suggestion"] == "t"
    assert r["selected_test"] == "t"
    assert 0.0 <= r["test_result"]["p_value"] <= 1.0
    assert r["test_result"]["significant"] is True
    assert np.isfinite(r["effect_size"]["value"])
    assert r["effect_size"]["method"] == "cohens_d"
    assert "组间差异不等于因果" in r["conclusion"]
    # group means agree with compute_stats run on each group subset
    for g in ("control", "treatment"):
        sub = compute_stats(df[df["group"] == g])
        assert abs(
            r["descriptive"][g]["mean"] - sub["columns"]["response"]["mean"]
        ) < 1e-6
        assert abs(
            r["descriptive"][g]["std"] - sub["columns"]["response"]["std"]
        ) < 1e-6


def test_small_n_flags_shapiro_unreliable():
    df = _two_group(_rng.normal(10, 1, 5), _rng.normal(11, 1, 5))
    r = compare_groups(df, "g", "v")
    assert r["assumptions"]["shapiro"]["A"]["reliable"] is False
    assert any("不可靠" in w for w in r["warnings"])


# ---------------------------------------------------------------- engine: boundaries
def test_missing_group_column():
    with pytest.raises(ValueError, match="分组列不存在"):
        compare_groups(pd.DataFrame({"v": [1, 2, 3]}), "nope", "v")


def test_missing_value_column():
    with pytest.raises(ValueError, match="数值列不存在"):
        compare_groups(pd.DataFrame({"g": ["A", "B", "A", "B"]}), "g", "nope")


def test_fewer_than_two_groups():
    df = pd.DataFrame({"g": ["A"] * 10, "v": range(10)})
    with pytest.raises(ValueError, match="需要至少 2 组"):
        compare_groups(df, "g", "v")


def test_more_than_two_groups_without_groups_param():
    df = pd.DataFrame(
        {"g": ["A"] * 5 + ["B"] * 5 + ["C"] * 5, "v": range(15)}
    )
    with pytest.raises(ValueError, match="超过 2 组"):
        compare_groups(df, "g", "v")


def test_more_than_two_groups_with_groups_param_ok():
    df = pd.DataFrame(
        {"g": ["A"] * 10 + ["B"] * 10 + ["C"] * 10, "v": list(range(30))}
    )
    r = compare_groups(df, "g", "v", groups=["A", "C"])
    assert r["groups"] == ["A", "C"]


def test_groups_param_must_be_two_and_in_values():
    df = pd.DataFrame({"g": ["A"] * 10 + ["B"] * 10, "v": range(20)})
    with pytest.raises(ValueError, match="恰好指定 2 个"):
        compare_groups(df, "g", "v", groups=["A"])
    with pytest.raises(ValueError, match="不在分组列"):
        compare_groups(df, "g", "v", groups=["A", "Z"])


def test_group_sample_too_small():
    df = pd.DataFrame({"g": ["A"] * 2 + ["B"] * 10, "v": range(12)})
    with pytest.raises(ValueError, match="至少 3"):
        compare_groups(df, "g", "v")


def test_non_numeric_value_column():
    df = pd.DataFrame(
        {"g": ["A"] * 5 + ["B"] * 5, "v": ["x"] * 10}
    )
    with pytest.raises(ValueError, match="不是数值列"):
        compare_groups(df, "g", "v")


def test_value_column_no_valid_values():
    df = pd.DataFrame(
        {"g": ["A"] * 5 + ["B"] * 5, "v": [None] * 10}
    )
    with pytest.raises(ValueError, match="不是数值列|没有有效数值"):
        compare_groups(df, "g", "v")


def test_invalid_override_test():
    df = _two_group(_rng.normal(10, 1, 10), _rng.normal(11, 1, 10))
    with pytest.raises(ValueError, match="不支持的检验"):
        compare_groups(df, "g", "v", override_test="anova")


def test_override_keeps_auto_suggestion_and_records_override():
    df = _two_group(_rng.normal(10, 1, 40), _rng.normal(11, 1, 40))
    r = compare_groups(df, "g", "v", override_test="mannwhitney")
    assert r["auto_suggestion"] == "t"
    assert r["selected_test"] == "mannwhitney"
    assert r["overridden"] is True
    assert r["params"]["override_test"] == "mannwhitney"
    assert r["params"]["auto_test"] == "t"
    assert r["params"]["selected_test"] == "mannwhitney"
    assert r["effect_size"]["method"] == "rank_biserial"
    assert any("改选" in w for w in r["warnings"])


# ---------------------------------------------------------------- router (temp app only)
@pytest.fixture()
def compare_client(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(f"sqlite:///{db_path}")
    try:
        seeded = store.seed_golden(conn)
    finally:
        conn.close()
    corr_id = next(s["id"] for s in seeded if s["filename"] == "corr.csv")

    app = FastAPI()
    app.include_router(compare_router.router)

    def _override_conn():
        c = connect(f"sqlite:///{db_path}")
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_conn] = _override_conn
    with TestClient(app) as client:
        yield client, corr_id


def test_router_post_and_get_compare(compare_client):
    client, corr_id = compare_client
    resp = client.post(
        f"/api/datasets/{corr_id}/compare",
        json={"group_col": "group", "value_col": "response"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cmp_ = body["compare"]
    assert cmp_["selected_test"] == "t"
    assert 0.0 <= cmp_["test_result"]["p_value"] <= 1.0
    assert cmp_["descriptive"]["control"]["mean"] == pytest.approx(4.501413)
    assert cmp_["descriptive"]["treatment"]["mean"] == pytest.approx(10.75636)
    assert cmp_["effect_size"]["value"] == pytest.approx(-3.299204)

    got = client.get(f"/api/datasets/{corr_id}/compare")
    assert got.status_code == 200
    assert got.json()["compare"]["selected_test"] == "t"
    assert got.json()["analysis_id"] == body["analysis_id"]


def test_router_dataset_not_found(compare_client):
    client, _ = compare_client
    assert client.post(
        "/api/datasets/99999/compare",
        json={"group_col": "group", "value_col": "response"},
    ).status_code == 404
    assert client.get("/api/datasets/99999/compare").status_code == 404


def test_router_bad_params_are_400(compare_client):
    client, corr_id = compare_client
    assert client.post(
        f"/api/datasets/{corr_id}/compare",
        json={"group_col": "nope", "value_col": "response"},
    ).status_code == 400
    assert client.post(
        f"/api/datasets/{corr_id}/compare",
        json={"group_col": "group", "value_col": "group"},
    ).status_code == 400
    assert client.post(
        f"/api/datasets/{corr_id}/compare",
        json={"group_col": "group", "value_col": "response",
              "override_test": "anova"},
    ).status_code == 400


def test_router_get_without_result_is_404(tmp_path):
    db_path = tmp_path / "empty.db"
    conn = init_db(f"sqlite:///{db_path}")
    try:
        seeded = store.seed_golden(conn)
    finally:
        conn.close()
    corr_id = next(s["id"] for s in seeded if s["filename"] == "corr.csv")
    app = FastAPI()
    app.include_router(compare_router.router)

    def _override_conn():
        c = connect(f"sqlite:///{db_path}")
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_conn] = _override_conn
    with TestClient(app) as client:
        assert client.get(f"/api/datasets/{corr_id}/compare").status_code == 404

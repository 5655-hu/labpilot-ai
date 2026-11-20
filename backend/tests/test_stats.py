"""Stats engine + stats API tests (Wave 2).

Correlation expectation comes from golden_manifest.json (0.98506 for
dose-response in corr.csv). Edge cases are asserted, not assumed: constant
columns, non-numeric columns, small samples, empty data.
"""
import io

import pandas as pd
import pytest


def _golden_id(client, keyword):
    ds = client.get("/api/datasets").json()["datasets"]
    return next(d["id"] for d in ds if keyword in d["name"])


def _stats(client, dataset_id):
    r = client.post(f"/api/datasets/{dataset_id}/stats")
    assert r.status_code == 200, r.text
    return r.json()["stats"]


def _upload(client, df, name="t.csv"):
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    r = client.post("/api/datasets/upload", files={"file": (name, buf.getvalue(), "text/csv")})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_corr_pearson_matches_manifest(client):
    corr = _golden_id(client, "相关性")
    s = _stats(client, corr)
    assert s["correlation"]["method"] == "pearson"
    value = s["correlation"]["matrix"]["dose"]["response"]
    assert abs(value - 0.98506) < 0.001
    assert s["columns"]["dose"]["mean"] == 2.54446
    # the categorical group column is skipped, with a reason
    assert any(sk["column"] == "group" for sk in s["skipped_columns"])


def test_clean_stats_match_manifest(client):
    clean = _golden_id(client, "干净实验数据")
    s = _stats(client, clean)
    t = s["columns"]["temperature"]
    assert t["mean"] == 24.95465
    assert t["median"] == 24.925
    assert abs(t["std"] - 1.322891) < 1e-5
    assert abs(t["variance"] - 1.322891 ** 2) < 1e-4
    assert t["min"] == 21.8 and t["max"] == 29.37
    assert t["count"] == 200 and t["missing"] == 0


def test_dirty_stats_excludes_type_errors(client):
    dirty = _golden_id(client, "脏数据")
    s = _stats(client, dirty)
    # temperature column is object dtype with 1 non-numeric cell ("25.3C");
    # stats use the 116 coerced numeric values (117 non-null minus 1) and say so.
    assert s["columns"]["temperature"]["non_numeric_excluded"] == 1
    assert s["columns"]["temperature"]["count"] == 116


def test_constant_column_correlation_null(client):
    df = pd.DataFrame({"x": [5, 5, 5, 5], "y": [1.0, 2.0, 3.0, 4.0]})
    did = _upload(client, df, "const.csv")
    try:
        s = _stats(client, did)
        assert s["columns"]["x"]["std"] == 0.0
        assert s["columns"]["x"]["variance"] == 0.0
        assert s["columns"]["x"]["constant"] is True
        # x cannot correlate: matrix is empty and the reason is stated
        assert s["correlation"]["matrix"] == {}
        assert "常量列" in s["correlation"]["note"]
    finally:
        client.delete(f"/api/datasets/{did}")


def test_small_sample_no_correlation(client):
    df = pd.DataFrame({"a": [1.0, 3.0], "b": [2.0, 4.0]})
    did = _upload(client, df, "small.csv")
    try:
        s = _stats(client, did)
        assert s["columns"]["a"]["mean"] == 2.0
        assert s["correlation"]["matrix"] == {}
        assert "样本量不足" in s["correlation"]["note"]
    finally:
        client.delete(f"/api/datasets/{did}")


def test_non_numeric_column_skipped(client):
    df = pd.DataFrame({"name": ["alice", "bob", "carol"], "score": [90, 80, 70]})
    did = _upload(client, df, "names.csv")
    try:
        s = _stats(client, did)
        assert any(sk["column"] == "name" for sk in s["skipped_columns"])
        assert s["columns"]["score"]["mean"] == 80.0
        assert s["correlation"]["matrix"] == {}
    finally:
        client.delete(f"/api/datasets/{did}")


def test_stats_engine_empty_data_raises():
    from app.stats import compute_stats

    with pytest.raises(ValueError):
        compute_stats(pd.DataFrame())
    with pytest.raises(ValueError):
        compute_stats(pd.DataFrame({"a": []}))


def test_stats_persists_and_latest(client):
    corr = _golden_id(client, "相关性")
    before = client.get("/api/analyses").json()["total"]
    r = client.post(f"/api/datasets/{corr}/stats")
    assert r.status_code == 200
    analysis_id = r.json()["analysis_id"]
    latest = client.get(f"/api/datasets/{corr}/stats")
    assert latest.status_code == 200
    assert latest.json()["analysis_id"] == analysis_id
    assert abs(latest.json()["stats"]["correlation"]["matrix"]["dose"]["response"] - 0.98506) < 0.001
    assert client.get("/api/analyses").json()["total"] == before + 1


def test_stats_404(client):
    assert client.post("/api/datasets/999999/stats").status_code == 404
    df = pd.DataFrame({"a": [1, 2, 3]})
    did = _upload(client, df)
    try:
        assert client.get(f"/api/datasets/{did}/stats").status_code == 404
    finally:
        client.delete(f"/api/datasets/{did}")

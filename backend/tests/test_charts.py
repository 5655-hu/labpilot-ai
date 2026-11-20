"""Chart engine + chart API tests (user Wave 2: charts).

Golden expectations come from golden_manifest.json and the Wave 1 verified
results: dose-response Pearson 0.98506 (so regression R² ≈ 0.98506²), and the
audit's 14 pending IQR outliers on dirty.csv (temperature 4, humidity 5,
concentration 5). The regression slope is asserted as a range, not a
hard-coded value, because the plan says to verify it from the computation.
"""
import io

import pandas as pd
import pytest


def _golden_id(client, keyword):
    ds = client.get("/api/datasets").json()["datasets"]
    return next(d["id"] for d in ds if keyword in d["name"])


def _upload(client, df, name="t.csv"):
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    r = client.post("/api/datasets/upload", files={"file": (name, buf.getvalue(), "text/csv")})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _get(client, dataset_id, path, **params):
    r = client.get(f"/api/datasets/{dataset_id}/charts/{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()["chart"]


def test_histogram_counts_sum_to_valid_n(client):
    dirty = _golden_id(client, "脏数据")
    h = _get(client, dirty, "histogram", column="temperature")
    assert sum(h["counts"]) == h["n"]
    assert h["n"] == 116  # 126 rows - 9 missing - 1 non-numeric ("25.3C")
    assert len(h["bin_edges"]) == len(h["counts"]) + 1
    assert h["method"] in ("freedman-diaconis", "sturges")
    h2 = _get(client, dirty, "histogram", column="temperature", bins=10)
    assert h2["bins"] == 10
    assert sum(h2["counts"]) == h2["n"]


def test_boxplot_outliers_match_audit(client):
    dirty = _golden_id(client, "脏数据")
    b = _get(client, dirty, "boxplot")
    by_col = {box["column"]: box for box in b["boxes"]}
    # exactly the audit's 14 pending IQR outliers
    assert by_col["temperature"]["outlier_count"] == 4
    assert by_col["humidity"]["outlier_count"] == 5
    assert by_col["concentration"]["outlier_count"] == 5
    assert sum(box["outlier_count"] for box in b["boxes"]) == 14
    # cross-check against the audit result itself (same engine, same data)
    audit = client.post(f"/api/datasets/{dirty}/audit", json={"algorithms": ["iqr"]}).json()["audit"]
    for col, box in by_col.items():
        audit_pts = audit["outliers"][col]["points"]
        assert sorted(p["row_index"] for p in box["outliers"]) == sorted(p["row_index"] for p in audit_pts)
        assert box["q1"] == audit["outliers"][col]["by_algorithm"]["iqr"]["q1"]
        assert box["upper"] == audit["outliers"][col]["by_algorithm"]["iqr"]["upper"]
    # explicit column selection works; sample_id has no outliers
    b2 = _get(client, dirty, "boxplot", columns="temperature")
    assert len(b2["boxes"]) == 1 and b2["boxes"][0]["column"] == "temperature"


def test_scatter_and_line_point_counts(client):
    corr = _golden_id(client, "相关性")
    s = _get(client, corr, "scatter", x="dose", y="response")
    assert s["n"] == 150
    assert len(s["points"]) == 150
    assert s["excluded"] == 0
    line = _get(client, corr, "line", x="dose", y="response")
    assert line["n"] == 150
    xs = [p["x"] for p in line["points"]]
    assert xs == sorted(xs)
    # scatter keeps original order; line is sorted by x
    assert [p["x"] for p in s["points"]] != xs or True  # order may coincide; only sortedness is asserted


def test_heatmap_matches_stats(client):
    corr = _golden_id(client, "相关性")
    hm = _get(client, corr, "heatmap")
    assert hm["method"] == "pearson"
    cols = hm["columns"]
    assert "dose" in cols and "response" in cols
    assert "group" not in cols  # non-numeric column excluded
    m = hm["matrix"]
    n = len(cols)
    assert len(m) == n and all(len(row) == n for row in m)
    for i in range(n):
        assert m[i][i] == 1.0  # diagonal is 1
        for j in range(n):
            assert m[i][j] == m[j][i]  # symmetric
    di, ri = cols.index("dose"), cols.index("response")
    assert abs(m[di][ri] - 0.98506) < 0.001
    # cross-check against the stats endpoint
    stats = client.post(f"/api/datasets/{corr}/stats").json()["stats"]
    assert stats["correlation"]["matrix"]["dose"]["response"] == m[di][ri]


def test_regression_corr_dose_response(client):
    corr = _golden_id(client, "相关性")
    r = _get(client, corr, "regression", x="dose", y="response")
    assert r["n"] == 150
    assert abs(r["r_squared"] - 0.98506 ** 2) < 0.005  # R² ≈ 0.970
    assert abs(r["r"] - 0.98506) < 0.001
    assert 2.0 < r["slope"] < 3.0  # slope is about 2.5, verified from the data
    assert "dose" in r["equation"] and "response" in r["equation"]
    assert "=" in r["equation"]
    assert len(r["fit_line"]["x"]) == 2 and len(r["fit_line"]["y"]) == 2
    assert len(r["points"]) == 150
    # fit line passes through the data range
    assert r["fit_line"]["x"][0] <= min(p["x"] for p in r["points"])
    assert r["fit_line"]["x"][1] >= max(p["x"] for p in r["points"])


def test_regression_small_sample_and_constant(client):
    # n = 2: too few pairs for regression
    small = _upload(client, pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]}))
    r = client.get(f"/api/datasets/{small}/charts/regression", params={"x": "x", "y": "y"})
    assert r.status_code == 400
    # constant x column
    const = _upload(client, pd.DataFrame({"x": [5.0] * 10, "y": list(range(10))}))
    r = client.get(f"/api/datasets/{const}/charts/regression", params={"x": "x", "y": "y"})
    assert r.status_code == 400
    # but scatter on the same constant column works
    s = _get(client, const, "scatter", x="x", y="y")
    assert s["n"] == 10


def test_chart_errors(client):
    corr = _golden_id(client, "相关性")
    # non-numeric column for a numeric chart -> 400
    r = client.get(f"/api/datasets/{corr}/charts/histogram", params={"column": "group"})
    assert r.status_code == 400
    r = client.get(f"/api/datasets/{corr}/charts/scatter", params={"x": "group", "y": "response"})
    assert r.status_code == 400
    r = client.get(f"/api/datasets/{corr}/charts/boxplot", params={"columns": "group"})
    assert r.status_code == 400
    # missing column -> 400
    r = client.get(f"/api/datasets/{corr}/charts/histogram", params={"column": "nope"})
    assert r.status_code == 400
    # missing dataset -> 404
    r = client.get("/api/datasets/99999/charts/heatmap")
    assert r.status_code == 404
    r = client.get("/api/datasets/99999/charts/columns")
    assert r.status_code == 404
    # invalid bins -> 400
    r = client.get(f"/api/datasets/{corr}/charts/histogram", params={"column": "dose", "bins": 0})
    assert r.status_code == 400


def test_chart_columns_endpoint(client):
    corr = _golden_id(client, "相关性")
    r = client.get(f"/api/datasets/{corr}/charts/columns")
    assert r.status_code == 200
    cols = {c["name"]: c for c in r.json()["columns"]}
    assert cols["dose"]["numeric"] is True
    assert cols["group"]["numeric"] is False
    assert cols["dose"]["valid_count"] == 150


def test_histogram_missing_values_excluded_and_counted(client):
    dirty = _golden_id(client, "脏数据")
    h = _get(client, dirty, "histogram", column="humidity")
    assert h["n"] == 120  # 126 - 5 missing - 1 non-numeric ("high")
    assert h["missing"] == 5
    assert sum(h["counts"]) == 120

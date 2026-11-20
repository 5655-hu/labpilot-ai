"""Audit engine + audit API tests (Wave 2).

Expected values come from golden_manifest.json (computed from the files by
generate_golden.py), never hand-typed from memory: dirty.csv has 16 missing
cells, 6 duplicate rows, 3 type-error cells, and injected outliers at
temperature rows 3/71 and concentration row 50.
"""
import io
import json
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((BACKEND_DIR / "data" / "golden" / "golden_manifest.json").read_text(encoding="utf-8"))


def _golden_id(client, keyword):
    ds = client.get("/api/datasets").json()["datasets"]
    return next(d["id"] for d in ds if keyword in d["name"])


def _audit(client, dataset_id, body=None):
    r = client.post(f"/api/datasets/{dataset_id}/audit", json=body or {})
    assert r.status_code == 200, r.text
    return r.json()["audit"]


def test_dirty_audit_counts(client):
    dirty = _golden_id(client, "脏数据")
    a = _audit(client, dirty)
    assert a["rows"] == 126 and a["cols"] == 4
    assert a["missing"]["total"] == MANIFEST["datasets"]["dirty"]["total_missing"] == 16
    assert a["duplicates"]["count"] == MANIFEST["datasets"]["dirty"]["duplicate_rows"] == 6
    assert a["type_errors"]["temperature"]["count"] == 1
    assert a["type_errors"]["humidity"]["count"] == 1
    assert a["type_errors"]["concentration"]["count"] == 1
    assert a["type_errors"]["temperature"]["examples"][0]["value"] == "25.3C"
    # unit-inconsistency risks: "25.3C" vs plain numbers, "0.52 mol/L" vs plain
    risks = {u["column"]: u["units"] for u in a["unit_risks"]}
    assert risks["temperature"] == ["C"]
    assert risks["concentration"] == ["mol/L"]


def test_dirty_score_public_formula(client):
    dirty = _golden_id(client, "脏数据")
    a = _audit(client, dirty)
    s = a["score"]
    assert s["formula"].startswith("质量分 = 100")
    by_cat = {d["category"]: d for d in s["deductions"]}
    # 30*16/504 = 0.95, 20*6/126 = 0.95, 25*3/504 = 0.15, definite 0
    assert by_cat["missing"]["deduction"] == 0.95
    assert by_cat["duplicate"]["deduction"] == 0.95
    assert by_cat["type_error"]["deduction"] == 0.15
    assert by_cat["definite_error"]["deduction"] == 0.0
    assert s["total"] == 97.95
    # every deduction carries evidence: column, count, rate, example rows
    for d in s["deductions"]:
        if d["deduction"] > 0:
            assert d["evidence"], d["category"]
            for ev in d["evidence"]:
                assert "column" in ev and "count" in ev and "rate" in ev
                assert ev["example_rows"]


def test_dirty_outliers_iqr_and_zscore(client):
    dirty = _golden_id(client, "脏数据")
    a = _audit(client, dirty, {"algorithms": ["iqr"]})
    assert a["outliers"]["temperature"]["by_algorithm"]["iqr"]["indices"] == [3, 29, 46, 71]
    assert 3 in a["outliers"]["temperature"]["by_algorithm"]["iqr"]["indices"]
    assert 71 in a["outliers"]["temperature"]["by_algorithm"]["iqr"]["indices"]
    assert 50 in a["outliers"]["concentration"]["by_algorithm"]["iqr"]["indices"]
    assert a["pending_outliers"][0]["status"] == "待确认"

    z = _audit(client, dirty, {"algorithms": ["zscore"]})
    assert z["outliers"]["temperature"]["by_algorithm"]["zscore"]["indices"] == [3, 71]
    assert z["outliers"]["concentration"]["by_algorithm"]["zscore"]["indices"] == [50]
    # outliers never deduct points: same score under either algorithm
    assert z["score"]["total"] == a["score"]["total"] == 97.95

    both = _audit(client, dirty, {"algorithms": ["iqr", "zscore"]})
    assert both["score"]["total"] == 97.95
    dis = {d["algorithm"]: d["row_indices"] for d in both["outliers"]["temperature"]["disagreement"]}
    assert dis["iqr"] == [29, 46]  # IQR-only points, flagged not judged
    assert dis["zscore"] == []


def test_clean_and_corr_audit_high_score(client):
    clean = _golden_id(client, "干净实验数据")
    a = _audit(client, clean)
    assert a["score"]["total"] == 100.0
    assert a["missing"]["total"] == 0
    assert a["duplicates"]["count"] == 0
    assert all(v["count"] == 0 for v in a["type_errors"].values())
    corr = _golden_id(client, "相关性")
    b = _audit(client, corr)
    assert b["score"]["total"] == 100.0
    assert b["missing"]["total"] == 0
    assert b["duplicates"]["count"] == 0


def test_profile_survey_changes_weights_and_score(client):
    dirty = _golden_id(client, "脏数据")
    a = _audit(client, dirty, {"profile": "survey"})
    assert a["score"]["profile"]["name"] == "survey"
    assert a["score"]["profile"]["weights"]["missing"] == 15.0
    # 15*16/504 + 25*6/126 + 30*3/504 = 0.48 + 1.19 + 0.18 = 1.85 -> 98.15
    assert a["score"]["total"] == 98.15


def test_audit_persists_and_latest(client):
    dirty = _golden_id(client, "脏数据")
    before = client.get("/api/analyses").json()["total"]
    r = client.post(f"/api/datasets/{dirty}/audit", json={})
    assert r.status_code == 200
    analysis_id = r.json()["analysis_id"]
    latest = client.get(f"/api/datasets/{dirty}/audit")
    assert latest.status_code == 200
    assert latest.json()["analysis_id"] == analysis_id
    assert latest.json()["audit"]["score"]["total"] == 97.95
    after = client.get("/api/analyses").json()["total"]
    assert after == before + 1  # Dashboard "已完成分析次数" grows for real


def test_audit_404_and_invalid_params(client):
    assert client.post("/api/datasets/999999/audit", json={}).status_code == 404
    dirty = _golden_id(client, "脏数据")
    assert client.post(f"/api/datasets/{dirty}/audit", json={"algorithms": ["foo"]}).status_code == 422
    assert client.post(f"/api/datasets/{dirty}/audit", json={"profile": "nope"}).status_code == 422
    # a dataset with no audit yet -> latest returns 404
    df = pd.DataFrame({"a": [1, 2, 3]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    up = client.post("/api/datasets/upload", files={"file": ("t.csv", buf.getvalue(), "text/csv")})
    new_id = up.json()["id"]
    try:
        assert client.get(f"/api/datasets/{new_id}/audit").status_code == 404
    finally:
        client.delete(f"/api/datasets/{new_id}")


def test_audit_engine_empty_data_raises():
    from app.audit import run_audit

    with pytest.raises(ValueError):
        run_audit(pd.DataFrame())
    with pytest.raises(ValueError):
        run_audit(pd.DataFrame({"a": []}))


def test_rule_based_fallback_unchanged():
    """Wave 1 fallback still builds its text from real numbers, not the audit."""
    from app.ai_adapter import ColumnSummary, StatsSummary, summarize

    summary = StatsSummary(
        dataset_name="dirty.csv",
        rows=126,
        cols=4,
        file_hash="x" * 64,
        columns=(
            ColumnSummary(name="temperature", dtype="object", count=117, missing=9,
                          mean=25.0, median=25.0, std=1.5, minimum=-4.2, maximum=48.6),
        ),
        quality_score=97.95,
        findings=(),
    )
    text, manifest = summarize(summary)
    assert "98.0" in text  # fallback renders quality_score 97.95 with one decimal
    assert manifest.raw_rows_sent == 0
    assert manifest.model == "rule-based-fallback"

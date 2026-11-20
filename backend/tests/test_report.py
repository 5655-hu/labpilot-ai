"""Wave 3 report + rerun tests.

No test here calls a real model: subprocess is mocked at the ai_adapter
call site. Routing is verified with a TestClient mounted on a temporary
FastAPI app that only includes the report and analyses routers (main.py
is untouched — the parent registers the report router centrally).
"""
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
GOLDEN_DIR = BACKEND_DIR / "data" / "golden"

FAKE_AI_TEXT = "本数据集的变量之间存在定性关联，数据质量良好，建议后续扩大样本并复核异常值。"
TAMPERED_AI_TEXT = "本段解读含有一个错误数字 999.999 与真实无关，请注意核查。"
FAKE_USAGE = {"promptTokenCount": 100, "candidatesTokenCount": 50, "totalTokenCount": 150}


class _FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _fake_run_ok(*args, **kwargs):
    return _FakeProc(FAKE_AI_TEXT + "\n---usage---\n" + json.dumps(FAKE_USAGE))


def _fake_run_tampered(*args, **kwargs):
    return _FakeProc(TAMPERED_AI_TEXT + "\n---usage---\n" + json.dumps(FAKE_USAGE))


def _fake_run_timeout(*args, **kwargs):
    raise subprocess.TimeoutExpired(cmd="gemini.py", timeout=60)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from app import store
    from app.db import connect, init_db

    init_db()
    conn = connect()
    datasets = {}
    try:
        for key in ("corr", "dirty"):
            src = GOLDEN_DIR / f"{key}.csv"
            dest = tmp_path / f"{key}.csv"
            shutil.copyfile(src, dest)
            df = pd.read_csv(dest)
            datasets[key] = store.insert_dataset(
                conn, name=key, filename=f"{key}.csv", df=df,
                source="golden", stored_path=dest,
            )
        single = tmp_path / "single.csv"
        pd.DataFrame(
            {
                "group": ["a", "b", "a", "b", "a", "b", "a", "b"],
                "value": [1.0, 2.0, 1.5, 2.5, 1.2, 2.2, 1.8, 2.8],
            }
        ).to_csv(single, index=False)
        df = pd.read_csv(single)
        datasets["single"] = store.insert_dataset(
            conn, name="single", filename="single.csv", df=df,
            source="upload", stored_path=single,
        )
    finally:
        conn.close()

    from app.routers import analyses, report

    app = FastAPI()
    app.include_router(report.router)
    app.include_router(analyses.router)
    with TestClient(app) as client:
        yield {"client": client, "datasets": datasets}


def _db_conn():
    from app.db import connect

    return connect()


def _insert_analysis(dataset_id, name, params, result, engine_version="0.2.0"):
    from app.routers._helpers import insert_analysis

    conn = _db_conn()
    try:
        return insert_analysis(
            conn, dataset_id=dataset_id, name=name, params=params,
            result=result, engine_version=engine_version,
        )
    finally:
        conn.close()


def assert_evidence_complete(conclusions):
    assert conclusions, "报告至少要有一条结论"
    for c in conclusions:
        ev = c["evidence"]
        for k in ("dataset_id", "analysis_ids", "statistic", "method", "params", "value"):
            assert k in ev, f"{c['id']} 的 evidence 缺少字段 {k}"
        assert ev["analysis_ids"], f"{c['id']} 的 evidence 没有指向任何分析记录"


# ---------------------------------------------------------------------------
# 1. Gemini provider (mocked subprocess)
# ---------------------------------------------------------------------------

def test_gemini_provider_mocked_returns_tokens_and_elapsed(env, gemini_helper):
    from app.ai_adapter import GeminiProvider, StatsSummary, summarize

    summary = StatsSummary(dataset_name="t", rows=10, cols=2, file_hash="x" * 64)
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_ok):
        assert GeminiProvider().available() is True
        text, tokens, elapsed = GeminiProvider().summarize(summary)
    assert text == FAKE_AI_TEXT
    assert tokens["totalTokenCount"] == 150
    assert tokens["promptTokenCount"] == 100
    assert tokens["candidatesTokenCount"] == 50
    assert elapsed >= 0
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_ok):
        text2, manifest = summarize(summary, provider=GeminiProvider())
    assert text2 == FAKE_AI_TEXT
    assert manifest.raw_rows_sent == 0
    assert manifest.tokens["totalTokenCount"] == 150
    assert manifest.model == "gemini-3.5-flash-lite"


# ---------------------------------------------------------------------------
# 2. Report endpoints
# ---------------------------------------------------------------------------

def test_report_ai_path(env, gemini_helper):
    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_ok):
        resp = client.post(f"/api/datasets/{corr_id}/report", json={"include_ai": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    report = body["report"]
    assert report["source"] == "ai"
    assert report["ai_text"] == FAKE_AI_TEXT
    assert report["tokens"]["totalTokenCount"] == 150
    assert report["send_manifest"]["raw_rows_sent"] == 0
    assert report["send_manifest"]["model"] == "gemini-3.5-flash-lite"
    assert report["dataset"]["rows"] == 150
    assert report["regression"]["available"] is True
    assert abs(report["regression"]["r"] - 0.98506) < 1e-4
    assert report["regression"]["equation"].startswith("response = ")
    assert_evidence_complete(report["conclusions"])
    # Latest-report GET returns the same report.
    got = client.get(f"/api/datasets/{corr_id}/report")
    assert got.status_code == 200
    assert got.json()["analysis_id"] == body["analysis_id"]
    assert got.json()["report"]["source"] == "ai"


def test_report_ai_failure_falls_back_to_rule_based(env):
    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_timeout):
        resp = client.post(f"/api/datasets/{corr_id}/report", json={"include_ai": True})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["source"] == "rule-based"
    assert "规则版" in report["ai_text"]
    assert report["tokens"] is None
    assert report["audit"]["score"]["total"] is not None
    assert_evidence_complete(report["conclusions"])


def test_report_without_ai_is_rule_based(env):
    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    resp = client.post(f"/api/datasets/{corr_id}/report", json={"include_ai": False})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["source"] == "rule-based"
    assert report["tokens"] is None
    assert "规则版" in report["ai_text"]


def test_report_single_numeric_column_has_no_regression(env):
    client = env["client"]
    single_id = env["datasets"]["single"]["id"]
    resp = client.post(f"/api/datasets/{single_id}/report", json={"include_ai": False})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["regression"]["available"] is False
    assert report["regression"]["note"]
    assert report["stats"]["columns"]["value"]["mean"] == 1.875
    assert_evidence_complete(report["conclusions"])


def test_report_404s(env):
    client = env["client"]
    assert client.post("/api/datasets/999999/report", json={}).status_code == 404
    corr_id = env["datasets"]["corr"]["id"]
    assert client.get(f"/api/datasets/{corr_id}/report").status_code == 404
    assert client.get("/api/datasets/999999/report").status_code == 404


# ---------------------------------------------------------------------------
# 3. Rendering + number check: tampered AI numbers must not leak into the
#    deterministic sections of the rendered report.
# ---------------------------------------------------------------------------

def test_tampered_ai_numbers_do_not_change_rendered_numbers(env, gemini_helper):
    from app.report import render_markdown

    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_tampered):
        resp = client.post(f"/api/datasets/{corr_id}/report", json={"include_ai": True})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["source"] == "ai"
    # The tampered number is flagged by the safety-net check (hint only).
    unmatched = [u["value"] for u in report["number_check"]["unmatched"]]
    assert "999.999" in unmatched
    # Rendered report: deterministic sections keep the JSON originals.
    md = render_markdown(report)
    head = md.partition("## AI 解读")[0]
    assert "999.999" not in head
    assert "0.98506" in head  # true Pearson r from the JSON
    assert report["regression"]["equation"] in head
    assert str(report["audit"]["score"]["total"]) in head


# ---------------------------------------------------------------------------
# 4. Single analysis fetch + rerun
# ---------------------------------------------------------------------------

def test_get_analysis_and_rerun_audit_consistent(env):
    from app.audit import run_audit

    client = env["client"]
    dirty_id = env["datasets"]["dirty"]["id"]
    df = pd.read_csv(GOLDEN_DIR / "dirty.csv")
    result = run_audit(df)
    aid = _insert_analysis(dirty_id, "audit", result["params"], result, "0.2.0")

    got = client.get(f"/api/analyses/{aid}")
    assert got.status_code == 200
    assert got.json()["params"] == result["params"]
    assert got.json()["result"]["score"]["total"] == result["score"]["total"]

    rerun = client.post(f"/api/analyses/{aid}/rerun")
    assert rerun.status_code == 200, rerun.text
    body = rerun.json()
    assert body["original_id"] == aid
    assert body["consistent"] is True
    assert body["differences"] == []
    assert body["rerun_id"] != aid
    again = client.get(f"/api/analyses/{body['rerun_id']}")
    assert again.json()["result"] == result


def test_rerun_uses_original_params_not_current_defaults(env):
    from app.audit import run_audit

    client = env["client"]
    dirty_id = env["datasets"]["dirty"]["id"]
    df = pd.read_csv(GOLDEN_DIR / "dirty.csv")
    custom = run_audit(df, algorithms=["zscore"], z_threshold=2.0, profile="survey")
    default = run_audit(df)
    # The custom parameters must actually change the result, otherwise this
    # test could not tell original params apart from defaults.
    assert custom != default
    aid = _insert_analysis(dirty_id, "audit", custom["params"], custom, "0.2.0")

    rerun = client.post(f"/api/analyses/{aid}/rerun")
    assert rerun.status_code == 200, rerun.text
    body = rerun.json()
    assert body["consistent"] is True
    assert body["differences"] == []
    got = client.get(f"/api/analyses/{body['rerun_id']}").json()
    assert got["params"] == custom["params"]
    assert got["result"] == custom
    assert got["result"]["score"]["total"] == custom["score"]["total"]


def test_stats_rerun_consistent(env):
    from app.stats import compute_stats

    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    df = pd.read_csv(GOLDEN_DIR / "corr.csv")
    result = compute_stats(df)
    sid = _insert_analysis(
        corr_id, "stats", {"method": "pearson", "std_ddof": 1}, result, "0.2.0"
    )
    rerun = client.post(f"/api/analyses/{sid}/rerun")
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["consistent"] is True
    assert rerun.json()["differences"] == []


def test_report_rerun_reuses_ai_text_without_new_model_call(env, gemini_helper):
    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    with patch("app.ai_adapter.subprocess.run", side_effect=_fake_run_ok) as m:
        resp = client.post(f"/api/datasets/{corr_id}/report", json={"include_ai": True})
        assert resp.status_code == 200, resp.text
        assert m.call_count == 1
        report_id = resp.json()["analysis_id"]
        original_text = resp.json()["report"]["ai_text"]
        rerun = client.post(f"/api/analyses/{report_id}/rerun")
        # No second model call during the rerun.
        assert m.call_count == 1
    assert rerun.status_code == 200, rerun.text
    body = rerun.json()
    assert body["consistent"] is True
    assert body["differences"] == []
    got = client.get(f"/api/analyses/{body['rerun_id']}").json()
    assert got["result"]["ai_text"] == original_text
    assert got["result"]["source"] == "ai"
    assert "rerun_note" in got["result"]


def test_get_analysis_404(env):
    assert env["client"].get("/api/analyses/999999").status_code == 404


def test_rerun_unsupported_type_400(env):
    client = env["client"]
    corr_id = env["datasets"]["corr"]["id"]
    cid = _insert_analysis(corr_id, "charts", {"kind": "heatmap"}, {"type": "heatmap"}, "0.3.0")
    resp = client.post(f"/api/analyses/{cid}/rerun")
    assert resp.status_code == 400
    assert "不支持重跑" in resp.json()["detail"]

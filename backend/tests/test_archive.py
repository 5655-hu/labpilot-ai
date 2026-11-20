"""Wave 4 tests: reproducibility archive, rerun package, compare rerun,
and the Turso (libSQL) database adapter.

Archive tests run against the session TestClient (temp SQLite DB, seeded
golden data). The libSQL tests run against a local sqld server when one
is reachable (LIBSQL_TEST_URL, e.g. http://127.0.0.1:8080 started with
`sqld --http-listen-addr 127.0.0.1:8080 -d /tmp/sqld-data`); when no
server is reachable they SKIP with the reason recorded — they never
pretend to have tested the remote path.
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

# ---------------------------------------------------------------------------
# Helpers: build real analyses through the API, as a user would
# ---------------------------------------------------------------------------


def _dataset_ids(client):
    data = client.get("/api/datasets").json()
    out = {}
    for d in data["datasets"]:
        if "脏数据" in d["name"]:
            out["dirty"] = d["id"]
        if "相关性" in d["name"]:
            out["corr"] = d["id"]
    return out


def _run_audit(client, dataset_id):
    r = client.post(f"/api/datasets/{dataset_id}/audit", json={})
    assert r.status_code == 200, r.text
    return r.json()["analysis_id"]


def _run_compare(client, dataset_id):
    r = client.post(
        f"/api/datasets/{dataset_id}/compare",
        json={"group_col": "group", "value_col": "response"},
    )
    assert r.status_code == 200, r.text
    return r.json()["analysis_id"]


# ---------------------------------------------------------------------------
# 1. Archive fields
# ---------------------------------------------------------------------------


def test_archive_fields_complete(client):
    ids = _dataset_ids(client)
    audit_id = _run_audit(client, ids["dirty"])
    r = client.get(f"/api/analyses/{audit_id}/archive")
    assert r.status_code == 200, r.text
    arc = r.json()

    assert arc["analysis_id"] == audit_id
    assert arc["analysis_type"] == "audit"
    assert arc["archive_version"] == "1.0"

    # SHA-256 matches the dataset record exactly (upload-time hash).
    ds = client.get(f"/api/datasets/{ids['dirty']}/preview").json()
    assert arc["data_fingerprint"]["algorithm"] == "SHA-256"
    assert arc["data_fingerprint"]["file_hash"] == ds["file_hash"]
    assert len(arc["data_fingerprint"]["file_hash"]) == 64

    # Environment: real versions, none empty.
    env = arc["environment"]
    assert env["python_version"].startswith("3.")
    assert env["platform"]
    for dep in ("pandas", "numpy", "scipy", "scikit-learn", "fastapi"):
        assert env["dependencies"][dep], f"{dep} version missing"

    # Params are the original analysis params, verbatim.
    orig = client.get(f"/api/analyses/{audit_id}").json()
    assert arc["params"] == orig["params"]
    assert arc["cleaning_rules"]["profile"] == orig["params"]["profile"]
    assert arc["cleaning_rules"]["algorithms"] == orig["params"]["algorithms"]
    assert arc["cleaning_rules"]["iqr_k"] == orig["params"]["iqr_k"]

    # Engine + code versions.
    assert arc["engine_version"] == orig["engine_version"]
    assert arc["code_version"] == "0.6.0"

    # Random seed: this project is deterministic — recorded as such.
    assert arc["random_seed"]["seed"] is None
    assert "无随机性" in arc["random_seed"]["note"]

    # Result snapshot is the original result.
    assert arc["result_snapshot"] == orig["result"]
    assert arc["result_snapshot"]["score"]["total"] is not None


def test_archive_404_unknown_analysis(client):
    assert client.get("/api/analyses/999999/archive").status_code == 404
    assert client.get("/api/analyses/999999/archive/export").status_code == 404


# ---------------------------------------------------------------------------
# 2. Rerun package export
# ---------------------------------------------------------------------------


def test_export_rerun_package(client):
    ids = _dataset_ids(client)
    audit_id = _run_audit(client, ids["dirty"])
    r = client.get(f"/api/analyses/{audit_id}/archive/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    assert f"analysis-{audit_id}.json" in r.headers["content-disposition"]
    pkg = json.loads(r.text)

    assert pkg["format"] == "labpilot-rerun-package"
    assert pkg["format_version"] == 1
    assert pkg["analysis_id"] == audit_id
    assert pkg["analysis_type"] == "audit"
    # The three things a rerun needs: hash, params, code version.
    ds = client.get(f"/api/datasets/{ids['dirty']}/preview").json()
    assert pkg["dataset"]["file_hash"] == ds["file_hash"]
    assert pkg["dataset"]["hash_algorithm"] == "SHA-256"
    orig = client.get(f"/api/analyses/{audit_id}").json()
    assert pkg["params"] == orig["params"]
    assert pkg["code_version"] == "0.6.0"
    assert pkg["engine_version"] == orig["engine_version"]
    assert pkg["expected_result"] == orig["result"]
    assert pkg["rerun"]["endpoint"] == f"POST /api/analyses/{audit_id}/rerun"
    # No raw rows and no secrets in the package (the word "token" in the
    # howto text only refers to token *usage* as a volatile field).
    dumped = json.dumps(pkg)
    assert "auth_token" not in dumped
    assert "TURSO_AUTH_TOKEN" not in dumped
    assert "api_key" not in dumped
    assert "preview_rows" not in dumped


def test_export_package_rerun_reproduces(client):
    """End-to-end: export the package, rerun via its endpoint, compare
    the new result with the package's expected_result snapshot."""
    from app.report import diff_results

    ids = _dataset_ids(client)
    audit_id = _run_audit(client, ids["dirty"])
    pkg = json.loads(
        client.get(f"/api/analyses/{audit_id}/archive/export").text
    )
    r = client.post(f"/api/analyses/{audit_id}/rerun")
    assert r.status_code == 200, r.text
    assert r.json()["consistent"] is True
    new_result = client.get(f"/api/analyses/{r.json()['rerun_id']}").json()["result"]
    assert diff_results(pkg["expected_result"], new_result) == []


# ---------------------------------------------------------------------------
# 3. Archive list per dataset
# ---------------------------------------------------------------------------


def test_dataset_archives_list(client):
    ids = _dataset_ids(client)
    a1 = _run_audit(client, ids["corr"])
    a2 = _run_compare(client, ids["corr"])
    r = client.get(f"/api/datasets/{ids['corr']}/archives")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dataset_id"] == ids["corr"]
    got = {a["analysis_id"] for a in data["archives"]}
    assert {a1, a2} <= got
    assert data["total"] == len(data["archives"])
    for arc in data["archives"]:
        assert arc["data_fingerprint"]["file_hash"]
        assert arc["environment"]["dependencies"]["pandas"]
    assert client.get("/api/datasets/999999/archives").status_code == 404


# ---------------------------------------------------------------------------
# 4. Compare rerun (Wave 3 leftover, fixed in Wave 4)
# ---------------------------------------------------------------------------


def test_compare_rerun_consistent(client):
    ids = _dataset_ids(client)
    compare_id = _run_compare(client, ids["corr"])
    orig = client.get(f"/api/analyses/{compare_id}").json()
    r = client.post(f"/api/analyses/{compare_id}/rerun")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "compare"
    assert body["consistent"] is True, body["differences"]
    assert body["differences"] == []
    # Key numbers agree with the Wave 3 golden values.
    new_result = client.get(f"/api/analyses/{body['rerun_id']}").json()["result"]
    assert new_result["test_result"]["p_value"] == orig["result"]["test_result"]["p_value"]
    assert new_result["effect_size"]["value"] == orig["result"]["effect_size"]["value"]
    assert new_result["selected_test"] == orig["result"]["selected_test"]


# ---------------------------------------------------------------------------
# 5. Turso / libSQL adapter
# ---------------------------------------------------------------------------


def _libsql_test_url():
    return os.environ.get("LIBSQL_TEST_URL", "http://127.0.0.1:8080")


def _sqld_reachable(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def test_db_adapter_sqlite_path(tmp_path):
    """SQLite path: the adapter's connect/init_db behave exactly like the
    old sqlite3-only code (this is the production default)."""
    from app import db, store

    url = f"sqlite:///{tmp_path / 'adapter.db'}"
    assert db.backend_kind(url) == "sqlite"
    conn = db.init_db(url)
    try:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        seeded = store.seed_golden(conn)
        assert len(seeded) == 3
        rec = store.get_dataset(conn, seeded[0]["id"])
        assert rec["file_hash"] == seeded[0]["file_hash"]
        assert len(store.list_datasets(conn)) == 3
    finally:
        conn.close()


def test_db_adapter_row_behaves_like_sqlite_row(tmp_path):
    from app import db

    conn = db.init_db(f"sqlite:///{tmp_path / 'row.db'}")
    try:
        conn.execute("INSERT INTO datasets (name, filename, file_hash, rows_count, cols_count, columns_json, source) VALUES ('x','x.csv','abc',1,1,'[]','upload')")
        conn.commit()
        row = conn.execute("SELECT * FROM datasets WHERE id = 1").fetchone()
        assert row[0] == 1
        assert row["name"] == "x"
        assert dict(row)["filename"] == "x.csv"
        assert "name" in row.keys()
    finally:
        conn.close()


def test_db_adapter_libsql_path():
    """libSQL path against a real local sqld server (Turso protocol).

    Skipped — with the reason — when no sqld is reachable, so a missing
    server is never reported as a passing test.
    """
    url = _libsql_test_url()
    if not _sqld_reachable(url):
        pytest.skip(
            f"no local sqld reachable at {url} "
            "(start one with: sqld --http-listen-addr 127.0.0.1:8080 -d /tmp/sqld-data); "
            "remote libSQL path not verified in this run"
        )
    from app import db, store

    assert db.backend_kind(url) == "libsql"
    conn = db.connect(url)
    try:
        conn.execute("DROP TABLE IF EXISTS analyses")
        conn.execute("DROP TABLE IF EXISTS datasets")
        conn.commit()
        conn.executescript(open(db.SCHEMA_PATH, encoding="utf-8").read())
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        seeded = store.seed_golden(conn)
        assert len(seeded) == 3
        rec = store.get_dataset(conn, seeded[1]["id"])
        assert rec["name"] == seeded[1]["name"]
        assert len(rec["file_hash"]) == 64
        assert len(store.list_datasets(conn)) == 3
        # A second connection sees the same rows (server-side persistence).
        conn2 = db.connect(url)
        try:
            assert conn2.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 3
        finally:
            conn2.close()
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS analyses")
            conn.execute("DROP TABLE IF EXISTS datasets")
            conn.commit()
        except Exception:
            pass
        conn.close()


def test_db_adapter_libsql_missing_client(monkeypatch):
    """libsql:// with no client installed fails loudly, never silently
    falls back to SQLite."""
    import builtins

    from app import db

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "libsql_experimental":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    with pytest.raises(RuntimeError, match="libsql client is not installed"):
        db.connect("libsql://example.turso.io")

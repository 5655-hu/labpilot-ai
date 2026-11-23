"""Hardening 验收 —— 第一批：限流中间件层。

设计说明：
  * 每个用例现场构造一个只带 RateLimitMiddleware 的探针 app，
    不依赖主 app / DB / conftest 的 client fixture；
  * env 在构造 app 之前 setenv，兼容「__init__ 读 env」与「每请求读 env」两种实现；
  * 计数器清零依赖 conftest 里 autouse 的 reset_rate_limit fixture。

第二批（golden 保护 / 只读模式 / seed）需要 conftest 与 store 的实际接口，另行补。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ratelimit import RateLimitMiddleware


def _probe(monkeypatch, *, per_min: str, trust_proxy: str = "0") -> TestClient:
    """按给定 env 造一个最小 app：读 / 写 / health 三种路由各一。"""
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", per_min)
    monkeypatch.setenv("TRUST_PROXY", trust_proxy)

    application = FastAPI()
    application.add_middleware(RateLimitMiddleware)

    @application.get("/api/ping")
    def _read():
        return {"ok": True}

    @application.post("/api/ping")
    def _create():
        return {"ok": True}

    @application.put("/api/ping")
    def _update():
        return {"ok": True}

    @application.patch("/api/ping")
    def _patch():
        return {"ok": True}

    @application.delete("/api/ping")
    def _delete():
        return {"ok": True}

    @application.get("/health")
    def _health():
        return {"status": "ok"}

    return TestClient(application)


def test_write_over_limit_returns_429_with_retry_after(monkeypatch):
    client = _probe(monkeypatch, per_min="3")
    for _ in range(3):
        assert client.post("/api/ping").status_code == 200

    blocked = client.post("/api/ping")
    assert blocked.status_code == 429
    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None, "429 必须带 Retry-After"
    assert retry_after.isdigit(), f"Retry-After 应为整数秒，实际 {retry_after!r}"
    assert 1 <= int(retry_after) <= 60


def test_get_requests_are_not_counted(monkeypatch):
    client = _probe(monkeypatch, per_min="2")
    for _ in range(20):
        assert client.get("/api/ping").status_code == 200
    # 读请求不应吃掉写配额
    assert client.post("/api/ping").status_code == 200
    assert client.post("/api/ping").status_code == 200
    assert client.post("/api/ping").status_code == 429


def test_health_is_exempt(monkeypatch):
    client = _probe(monkeypatch, per_min="1")
    for _ in range(10):
        assert client.get("/health").status_code == 200
    assert client.post("/api/ping").status_code == 200
    assert client.post("/api/ping").status_code == 429


def test_limit_zero_disables_rate_limiting(monkeypatch):
    client = _probe(monkeypatch, per_min="0")
    for _ in range(50):
        assert client.post("/api/ping").status_code == 200


def test_all_write_methods_share_one_budget(monkeypatch):
    client = _probe(monkeypatch, per_min="2")
    assert client.delete("/api/ping").status_code == 200
    assert client.patch("/api/ping").status_code == 200
    assert client.put("/api/ping").status_code == 429
    assert client.post("/api/ping").status_code == 429


def test_trust_proxy_on_buckets_by_forwarded_for(monkeypatch):
    client = _probe(monkeypatch, per_min="2", trust_proxy="1")
    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}

    assert client.post("/api/ping", headers=a).status_code == 200
    assert client.post("/api/ping", headers=a).status_code == 200
    assert client.post("/api/ping", headers=a).status_code == 429
    # 换 IP 应拿到独立配额
    assert client.post("/api/ping", headers=b).status_code == 200
    assert client.post("/api/ping", headers=b).status_code == 200
    assert client.post("/api/ping", headers=b).status_code == 429


def test_trust_proxy_off_ignores_forwarded_for(monkeypatch):
    client = _probe(monkeypatch, per_min="2", trust_proxy="0")
    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}

    assert client.post("/api/ping", headers=a).status_code == 200
    assert client.post("/api/ping", headers=a).status_code == 200
    # 不可信代理：伪造 XFF 不能绕过限流，仍走同一个 socket IP 桶
    assert client.post("/api/ping", headers=b).status_code == 429

# ---------------------------------------------------------------------------
# 第二批：golden 保护 / 只读模式 / seed（store 层，独立临时库）
# 注：文件头已有 from __future__ import annotations，此处不再重复导入。
# ---------------------------------------------------------------------------
import inspect

import pytest

from app import store
from app.db import init_db

_HP_CSV = b"a,b\n1,2\n3,4\n5,6\n"  # 3 行 2 列，与 test_api.py 的 tiny.csv 同规格


def _hp_upload(client, filename="hardening.csv"):
    """上传一个自造数据集，返回数据集 dict。"""
    r = client.post(
        "/api/datasets/upload",
        files={"file": (filename, _HP_CSV, "text/csv")},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _hp_datasets(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["datasets"])
    return body["datasets"]


def _hp_golden(client):
    return [d for d in _hp_datasets(client) if d["source"] == "golden"]


def _hp_ids(client):
    return {d["id"] for d in _hp_datasets(client)}


def _hp_detail(resp):
    try:
        return resp.json().get("detail", "") or ""
    except ValueError:
        return resp.text


def _hp_fresh_conn(tmp_path, monkeypatch):
    """建一个真正空的临时库连接（绝不碰 session client 的共享库）。

    db.init_db 的入口签名未知，按两条路径兜底：
      1) 显式接受路径/URL 参数 → 直接传 tmp_path 下的文件；
      2) 只读 env → 把常见的 DB 路径 env 全指向临时文件。
    调用方随后必须断言 COUNT(*)==0，以便在兜底失效时立刻红掉并给出诊断。
    """
    db_file = tmp_path / "hardening-fresh.sqlite3"
    sig = inspect.signature(init_db)
    for name in ("path", "db_path", "sqlite_path", "filename", "database",
                 "db", "dsn", "url", "database_url", "db_url"):
        if name in sig.parameters:
            value = f"sqlite:///{db_file}" if "url" in name else str(db_file)
            return init_db(**{name: value})

    for name in ("LABPILOT_DB", "LABPILOT_DB_PATH", "DATABASE_PATH",
                 "DB_PATH", "SQLITE_PATH", "SQLITE_DB"):
        monkeypatch.setenv(name, str(db_file))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    return init_db()


# --- 1) golden DELETE → 403，golden 行数不变 -------------------------------
def test_golden_delete_protected_403(client, monkeypatch):
    monkeypatch.delenv("DEMO_READ_ONLY", raising=False)  # 隔离只读守卫，确保命中的是 golden 保护

    before = _hp_golden(client)
    assert len(before) == 3, "lifespan 应已 seed 3 个 golden"
    target = before[0]["id"]

    r = client.delete(f"/api/datasets/{target}")
    assert r.status_code == 403, r.text
    detail = _hp_detail(r)
    assert detail, "403 必须带 detail，前端要显示原因"
    assert "只读" not in detail, f"应是 golden 保护而非只读守卫: {detail!r}"

    after = _hp_golden(client)
    assert len(after) == len(before)
    assert target in {d["id"] for d in after}


# --- 2) 只读模式：写全禁、分析照跑 -----------------------------------------
def test_read_only_blocks_writes_but_allows_audit(client, monkeypatch):
    monkeypatch.delenv("DEMO_READ_ONLY", raising=False)
    rec = _hp_upload(client, "readonly-probe.csv")  # 先在非只读下造一个 upload
    did = rec["id"]
    golden_id = _hp_golden(client)[0]["id"]

    try:
        with monkeypatch.context() as m:
            m.setenv("DEMO_READ_ONLY", "1")

            # 2a) 删自己的 upload 也被拦，且文案是只读（不是 golden 保护）
            r = client.delete(f"/api/datasets/{did}")
            assert r.status_code == 403, r.text
            detail = _hp_detail(r)
            assert "只读" in detail, f"只读 403 文案应命中只读: {detail!r}"
            assert did in _hp_ids(client), "403 之后数据集必须还在"

            # 2b) 只读下 upload → 403
            up = client.post(
                "/api/datasets/upload",
                files={"file": ("blocked.csv", _HP_CSV, "text/csv")},
            )
            assert up.status_code == 403, up.text
            assert "只读" in _hp_detail(up)

            # 2c) 只读下对 golden 做 audit → 200，分析照常跑
            a = client.post(f"/api/datasets/{golden_id}/audit", json={})
            assert a.status_code == 200, a.text
            body = a.json()
            assert body["dataset_id"] == golden_id
            assert body["analysis_id"]
            assert isinstance(body["audit"], dict) and body["audit"]
    finally:
        # monkeypatch.context 退出已还原 env；best-effort 清场，不留脏数据
        client.delete(f"/api/datasets/{did}")


# --- 3) 非只读下 upload → DELETE 200，list 里消失 ---------------------------
def test_upload_then_delete_roundtrip(client, monkeypatch):
    monkeypatch.delenv("DEMO_READ_ONLY", raising=False)
    rec = _hp_upload(client, "roundtrip.csv")
    did = rec["id"]
    assert did in _hp_ids(client)

    r = client.delete(f"/api/datasets/{did}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": did}
    assert did not in _hp_ids(client)


# --- 4) 只读下 seed 仍出 3 个 golden（临时空库，直调 store 层）--------------
def test_seed_golden_runs_in_read_only_on_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_READ_ONLY", "1")
    conn = _hp_fresh_conn(tmp_path, monkeypatch)
    try:
        n = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        assert n == 0, (
            "临时库没生效：init_db 仍指向共享库。"
            "请把 db.py 的 init_db 签名/DB 路径 env 名发我，我改成精确调用。"
        )

        seeded = store.seed_golden(conn)
        assert len(seeded) == 3, "只读模式不应阻止首启 seed（否则演示库是空的）"

        rows = store.list_datasets(conn)
        assert len(rows) == 3
        assert {d["source"] for d in rows} == {"golden"}

        # 幂等：非空库再跑一次直接返回 []（靠行数判断，不靠 file_hash）
        assert store.seed_golden(conn) == []
        assert len(store.list_datasets(conn)) == 3
    finally:
        conn.close()


# --- 5) 拍板：只读下删不存在的 id 仍是 404 ---------------------------------
def test_delete_missing_id_in_read_only_is_404(client, monkeypatch):
    """只读守卫在 store.delete_dataset 里"查到记录后"才检查，查不到 → False → 404。

    保持 404 的理由：只读是写保护而非资源隐藏；对不存在的 id 回 403 会让
    403/404 变成存在性预言机，且与非只读模式语义分叉。store.py 不改。
    """
    with monkeypatch.context() as m:
        m.setenv("DEMO_READ_ONLY", "1")
        r = client.delete("/api/datasets/999999")
        assert r.status_code == 404, r.text

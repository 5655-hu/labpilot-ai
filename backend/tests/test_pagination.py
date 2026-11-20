"""Analysis-list pagination + /health wave label (Wave 5).

Pagination contract: GET /api/analyses?limit=&offset= returns the requested
page in `analyses` and the FULL count in `total` (never the page size), so
callers can compute page counts. Default page size is 20.
"""
import pytest


def _golden_id(client, keyword):
    ds = client.get("/api/datasets").json()["datasets"]
    return next(d["id"] for d in ds if keyword in d["name"])


def _seed_analyses(client, n):
    dirty = _golden_id(client, "脏数据")
    before = client.get("/api/analyses?limit=1").json()["total"]
    for _ in range(n):
        r = client.post(f"/api/datasets/{dirty}/audit", json={})
        assert r.status_code == 200, r.text
    return before


def test_health_reports_wave_and_version(client):
    h = client.get("/health").json()
    assert h["version"] == "0.6.0"
    assert h["wave"] == "Wave 5"


def test_analyses_default_page_is_20(client):
    before = _seed_analyses(client, 25)
    body = client.get("/api/analyses").json()
    assert body["total"] == before + 25
    assert len(body["analyses"]) == 20
    # newest first
    ids = [a["id"] for a in body["analyses"]]
    assert ids == sorted(ids, reverse=True)


def test_analyses_pages_do_not_overlap(client):
    total = client.get("/api/analyses?limit=1").json()["total"]
    assert total >= 25
    p1 = client.get("/api/analyses?limit=5&offset=0").json()
    p2 = client.get("/api/analyses?limit=5&offset=5").json()
    assert len(p1["analyses"]) == 5 and len(p2["analyses"]) == 5
    assert p1["total"] == p2["total"] == total
    ids1 = {a["id"] for a in p1["analyses"]}
    ids2 = {a["id"] for a in p2["analyses"]}
    assert not ids1 & ids2
    # last page holds the remainder
    last = client.get(f"/api/analyses?limit=5&offset={total - (total % 5 or 5)}").json()
    assert len(last["analyses"]) == (total % 5 or 5)
    assert last["total"] == total
    # offset past the end: empty page, total unchanged
    empty = client.get(f"/api/analyses?limit=5&offset={total + 100}").json()
    assert empty["analyses"] == [] and empty["total"] == total


def test_analyses_pagination_validation(client):
    assert client.get("/api/analyses?limit=0").status_code == 422
    assert client.get("/api/analyses?limit=101").status_code == 422
    assert client.get("/api/analyses?offset=-1").status_code == 422
    assert client.get("/api/analyses?limit=abc").status_code == 422

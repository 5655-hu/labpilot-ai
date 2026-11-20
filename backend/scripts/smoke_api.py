"""End-to-end smoke test: exercises every public API endpoint once.

Run against a live backend (default http://127.0.0.1:8000):

    .venv\\Scripts\\python.exe scripts\\smoke_api.py        # Windows
    .venv/bin/python scripts/smoke_api.py                  # Linux/macOS

Exit code 0 means every endpoint answered as expected. The script uploads a
tiny generated CSV and deletes it again, so it leaves no dataset behind;
analysis records it creates stay in the dev database (that is the point —
the archive/report pages need history to show).
"""
from __future__ import annotations

import json
import os
import sys

import httpx
import pandas as pd

BASE = os.environ.get("LABPILOT_API", "http://127.0.0.1:8000")
results: list[tuple[str, int, bool]] = []


def check(name: str, resp: httpx.Response, expect: int = 200) -> httpx.Response:
    ok = resp.status_code == expect
    results.append((name, resp.status_code, ok))
    print(("ok    " if ok else "FAIL  ") + f"{name}  [{resp.status_code}]")
    if not ok:
        print(f"      expected {expect}: {resp.text[:400]}")
    return resp


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60)
    check("GET /health", c.get("/health"))

    ds = check("GET /api/datasets", c.get("/api/datasets")).json()
    by_file = {d["filename"]: d for d in ds["datasets"]}
    print("      datasets:", sorted(by_file))
    corr_id = by_file["corr.csv"]["id"]
    dirty_id = by_file["dirty.csv"]["id"]

    check("GET preview", c.get(f"/api/datasets/{corr_id}/preview", params={"limit": 5}))
    check("POST audit", c.post(f"/api/datasets/{dirty_id}/audit", json={}))
    check("GET audit latest", c.get(f"/api/datasets/{dirty_id}/audit"))
    check("POST audit bad algorithm -> 422", c.post(f"/api/datasets/{dirty_id}/audit", json={"algorithms": ["nope"]}), 422)
    audit = c.post(f"/api/datasets/{dirty_id}/audit", json={}).json()
    print("      dirty quality score:", audit["audit"]["score"]["total"])

    check("POST stats", c.post(f"/api/datasets/{corr_id}/stats"))
    check("GET stats latest", c.get(f"/api/datasets/{corr_id}/stats"))
    stats = c.get(f"/api/datasets/{corr_id}/stats").json()["stats"]
    print("      pearson dose~response:", stats["correlation"]["matrix"]["dose"]["response"])

    check("GET chart columns", c.get(f"/api/datasets/{corr_id}/charts/columns"))
    check("GET histogram", c.get(f"/api/datasets/{corr_id}/charts/histogram", params={"column": "dose"}))
    check("GET boxplot", c.get(f"/api/datasets/{corr_id}/charts/boxplot"))
    check("GET scatter", c.get(f"/api/datasets/{corr_id}/charts/scatter", params={"x": "dose", "y": "response"}))
    check("GET line", c.get(f"/api/datasets/{corr_id}/charts/line", params={"x": "sample_id", "y": "response"}))
    check("GET heatmap", c.get(f"/api/datasets/{corr_id}/charts/heatmap"))
    check("GET regression", c.get(f"/api/datasets/{corr_id}/charts/regression", params={"x": "dose", "y": "response"}))
    check("GET histogram non-numeric column -> 400", c.get(f"/api/datasets/{corr_id}/charts/histogram", params={"column": "group"}), 400)

    check("POST compare", c.post(f"/api/datasets/{corr_id}/compare", json={"group_col": "group", "value_col": "response"}))
    check("GET compare latest", c.get(f"/api/datasets/{corr_id}/compare"))

    report = check("POST report", c.post(f"/api/datasets/{corr_id}/report", json={"include_ai": True})).json()
    print("      report source:", report["report"]["source"], "| conclusions:", len(report["report"]["conclusions"]))
    check("POST report without AI", c.post(f"/api/datasets/{corr_id}/report", json={"include_ai": False}))
    check("GET report latest", c.get(f"/api/datasets/{corr_id}/report"))
    check("POST report unknown dataset -> 404", c.post("/api/datasets/999999/report", json={}), 404)

    check("GET /api/analyses", c.get("/api/analyses"))
    check("GET single analysis", c.get(f"/api/analyses/{report['analysis_id']}"))
    rerun = check("POST rerun report", c.post(f"/api/analyses/{report['analysis_id']}/rerun")).json()
    print("      rerun consistent:", rerun["consistent"], "| differences:", rerun["differences"])
    check("GET rerun record", c.get(f"/api/analyses/{rerun['rerun_id']}"))
    audit_rerun = c.post(f"/api/analyses/{audit['analysis_id']}/rerun").json()
    print("      audit rerun consistent:", audit_rerun["consistent"])

    check("GET archive", c.get(f"/api/analyses/{report['analysis_id']}/archive"))
    package = check("GET archive export", c.get(f"/api/analyses/{report['analysis_id']}/archive/export")).json()
    print("      rerun package keys:", sorted(package.keys())[:8])
    check("GET dataset archives", c.get(f"/api/datasets/{corr_id}/archives"))

    csv_bytes = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2.0, 4.1, 6.2, 7.9]}).to_csv(index=False).encode()
    upload = check("POST upload", c.post("/api/datasets/upload", files={"file": ("smoke.csv", csv_bytes, "text/csv")})).json()
    print("      uploaded id:", upload["id"], "rows:", upload["rows_count"])
    check("GET uploaded preview", c.get(f"/api/datasets/{upload['id']}/preview"))
    check("POST stats on upload", c.post(f"/api/datasets/{upload['id']}/stats"))
    check("DELETE upload", c.delete(f"/api/datasets/{upload['id']}"))
    check("GET deleted preview -> 404", c.get(f"/api/datasets/{upload['id']}/preview"), 404)
    check("upload empty file -> 400", c.post("/api/datasets/upload", files={"file": ("empty.csv", b"", "text/csv")}), 400)
    check("upload unsupported type -> 400", c.post("/api/datasets/upload", files={"file": ("x.txt", b"a,b\n1,2\n", "text/plain")}), 400)

    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print(json.dumps(failed, ensure_ascii=False))
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

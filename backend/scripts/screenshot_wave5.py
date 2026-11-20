"""Wave 5 screenshots: real headless Chromium (Playwright) visits the
PRODUCTION build (static dist served on :4173, backend in production mode
on :8002 with a throwaway SQLite DB), drives Dashboard + Report pages
against live data, waits until the real content renders, then screenshots.
Fails loudly if content never renders (no blank screenshots).

Usage: /tmp/shot-venv/bin/python backend/scripts/screenshot_wave5.py
Prereqs: prod backend on :8002 (DATABASE_URL=sqlite:////tmp/labpilot-prod.db)
and `python3 -m http.server 4173` inside frontend/dist, both running.
"""
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4173"
API = "http://localhost:8002"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def dataset_ids():
    with urllib.request.urlopen(f"{API}/api/datasets", timeout=10) as r:
        data = json.load(r)
    out = {}
    for d in data["datasets"]:
        if "相关性" in d["name"]:
            out["corr"] = d["id"]
        if "脏数据" in d["name"]:
            out["dirty"] = d["id"]
    return out


def main():
    ids = dataset_ids()
    print("datasets:", ids)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})

        # 1. Dashboard on the production build.
        page.goto(f"{BASE}/", wait_until="networkidle")
        page.wait_for_timeout(1200)
        sidebar = page.locator("aside").inner_text()
        assert "Wave 5" in sidebar, f"sidebar wave label wrong: {sidebar!r}"
        assert "v0.6.0" in sidebar, f"sidebar version wrong: {sidebar!r}"
        body = page.locator("main").inner_text()
        assert "3" in body, "dashboard should show 3 datasets"
        page.screenshot(path=str(OUT / "wave5-01-dashboard-prod.png"), full_page=True)
        print("wave5-01-dashboard-prod.png: production dashboard rendered")

        # 2. Report page: the static server has no SPA fallback, so reach
        #    /report through the sidebar link instead of a direct URL.
        #    The page auto-selects the corr dataset and loads its latest
        #    (rule-based) report, generated via API before screenshots.
        page.goto(f"{BASE}/", wait_until="networkidle")
        page.get_by_role("link", name="AI 科研报告").click()
        page.wait_for_selector("select", timeout=15000)
        page.wait_for_selector('[data-testid="report-content"]', timeout=20000)
        page.wait_for_timeout(800)
        text = page.locator('[data-testid="report-content"]').inner_text()
        assert "0.98506" in text or "0.985" in text, f"report missing corr value: {text[:400]!r}"
        page.screenshot(path=str(OUT / "wave5-02-report-prod.png"), full_page=True)
        print("wave5-02-report-prod.png: production report rendered")

        # 3. Archive list on the production build: pagination controls must
        #    render (page 1 of N, 20 per page).
        page.get_by_role("link", name="复现档案").click()
        page.wait_for_selector('[data-testid="archive-list"]', timeout=15000)
        page.wait_for_timeout(800)
        arch = page.locator('[data-testid="archive-list"]').inner_text()
        assert "第 1 /" in arch, f"pagination missing: {arch[:300]!r}"
        page.screenshot(path=str(OUT / "wave5-03-archive-pagination-prod.png"), full_page=True)
        print("wave5-03-archive-pagination-prod.png: pagination rendered")
        browser.close()


if __name__ == "__main__":
    main()

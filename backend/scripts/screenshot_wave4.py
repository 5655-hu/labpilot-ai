"""Wave 4 screenshots: real headless Chromium (Playwright) visits the running
frontend, drives the new Wave 4 UI (archive list + archive detail, dynamic
sidebar version) against live backend data, waits until the real content
renders, then screenshots. Fails loudly if content never renders (no blank
screenshots).

Usage: /tmp/shot-venv/bin/python backend/scripts/screenshot_wave4.py
"""
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def dataset_ids():
    with urllib.request.urlopen("http://localhost:8000/api/datasets", timeout=10) as r:
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

        page.goto(f"{BASE}/archive", wait_until="networkidle")
        page.wait_for_selector('[data-testid="archive-list"]', timeout=15000)
        page.wait_for_timeout(800)
        # Sidebar version must come from the live backend, not the old label.
        sidebar = page.locator("aside").inner_text()
        assert "Wave 4" in sidebar, f"sidebar wave label wrong: {sidebar!r}"
        assert "v0.5.0" in sidebar, f"sidebar version wrong: {sidebar!r}"
        page.screenshot(path=str(OUT / "wave4-01-archive-list.png"), full_page=True)
        print("wave4-01-archive-list.png: archive list rendered")

        # 2. Archive detail: open the first (newest) analysis and check the
        # real archive fields render, including the full SHA-256.
        first = page.locator('[data-testid="archive-list"] li button').first
        first.click()
        page.wait_for_selector('[data-testid="archive-detail"]', timeout=15000)
        page.wait_for_selector('[data-testid="archive-hash"]', timeout=15000)
        page.wait_for_timeout(800)
        detail = page.locator('[data-testid="archive-detail"]').inner_text()
        assert "SHA-256" in detail, "archive hash missing"
        assert "Python 3.12" in detail, "python version missing"
        assert "pandas" in detail, "dependency list missing"
        assert "清洗规则" in detail, "cleaning rules missing"
        assert "下载重跑包" in detail, "export button missing"
        assert "无随机性" in detail, "seed note missing"
        page.screenshot(path=str(OUT / "wave4-02-archive-detail.png"), full_page=True)
        print("wave4-02-archive-detail.png: archive detail rendered")

        # 3. Compare rerun now works from the archive page: rerun a compare
        # row and expect a consistency result, not a 400. Note the rerun
        # inserts a NEW analysis row on top, so assert on the rerun-result
        # badge itself (keyed by the original analysis id), not on the
        # first matching row.
        page.goto(f"{BASE}/archive", wait_until="networkidle")
        page.wait_for_selector('[data-testid="archive-list"]', timeout=15000)
        compare_row = page.locator('[data-testid="archive-list"] li', has_text="分组比较").first
        compare_row.locator("button", has_text="重跑").click()
        page.wait_for_selector('[data-testid^="rerun-result-"]', timeout=15000)
        page.wait_for_timeout(500)
        badge = page.locator('[data-testid^="rerun-result-"]').first.inner_text()
        assert "结果一致" in badge, f"compare rerun did not report consistent: {badge!r}"
        print("compare rerun from archive page: consistent")
        browser.close()


if __name__ == "__main__":
    main()

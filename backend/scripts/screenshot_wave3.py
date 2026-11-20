"""Wave 3 screenshots: real headless Chromium (Playwright) visits the running
frontend, drives the new Wave 3 UI (report, group compare, rerun, independent-
scale boxplot) against live backend data, waits until the real content renders,
then screenshots. Fails loudly if content never renders (no blank screenshots).

Usage: /tmp/shot-venv/bin/python backend/scripts/screenshot_wave3.py
"""
import json
import sys
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

        # 1. Report page: corr dataset, latest report must be the AI one.
        page.goto(f"{BASE}/report", wait_until="networkidle")
        page.wait_for_selector("select", timeout=15000)
        page.locator("select").first.select_option(str(ids["corr"]))
        page.wait_for_selector('[data-testid="report-content"]', timeout=30000)
        page.wait_for_timeout(800)
        body = page.locator('[data-testid="report-content"]').inner_text()
        assert "AI 生成" in body, "report source badge missing"
        assert "response = 2.5241" in body, "regression equation missing"
        assert "0.98506" in body, "correlation value missing"
        assert "证据" in body, "conclusion evidence toggle missing"
        page.screenshot(path=str(OUT / "wave3-01-report.png"), full_page=True)
        print("wave3-01-report.png: AI report rendered")

        # 2. Group compare on the stats page: group vs response, run it live.
        page.goto(f"{BASE}/stats", wait_until="networkidle")
        page.wait_for_selector("select", timeout=15000)
        page.locator("select").first.select_option(str(ids["corr"]))
        page.wait_for_selector('[data-testid="compare-section"]', timeout=30000)
        page.wait_for_selector('[data-testid="compare-result"]', timeout=30000)
        page.get_by_role("button", name="运行比较").click()
        page.wait_for_timeout(1500)
        page.wait_for_selector('[data-testid="compare-result"]', timeout=30000)
        page.wait_for_timeout(500)
        cmp = page.locator('[data-testid="compare-result"]').inner_text()
        assert "独立样本 t 检验" in cmp, "selected test missing"
        assert "组间差异不等于因果" in cmp, "causality note missing"
        assert "Cohen" in cmp, "effect size missing"
        page.locator('[data-testid="compare-section"]').screenshot(
            path=str(OUT / "wave3-02-compare.png")
        )
        print("wave3-02-compare.png: compare result rendered")

        # 3. Rerun: archive page. First prove the compare 400 error is shown,
        # then rerun a stats analysis and capture the consistency result.
        page.goto(f"{BASE}/archive", wait_until="networkidle")
        page.wait_for_selector('[data-testid="archive-list"]', timeout=15000)
        # compare analysis -> Wave 4: compare reruns are supported now, so
        # the rerun must report a consistency verdict, not a 400.
        compare_btn = page.locator('[data-testid="archive-list"] li', has_text="分组比较").first.locator("button", has_text="重跑")
        if compare_btn.count() > 0:
            compare_btn.click()
            page.wait_for_selector('[data-testid^="rerun-result-"]', timeout=30000)
            page.wait_for_timeout(500)
            cmp_res = page.locator('[data-testid^="rerun-result-"]').first.inner_text()
            assert "结果一致" in cmp_res, f"compare rerun verdict missing: {cmp_res!r}"
            print("compare rerun verdict:", cmp_res.replace("\n", " ")[:160])
        stats_btn = page.locator('[data-testid="archive-list"] li', has_text="统计分析").first.locator("button", has_text="重跑")
        assert stats_btn.count() > 0, "no stats analysis row found"
        stats_btn.click()
        page.wait_for_selector('[data-testid^="rerun-result-"]', timeout=30000)
        page.wait_for_timeout(500)
        res = page.locator('[data-testid^="rerun-result-"]').first.inner_text()
        assert "结果一致" in res or "结果不一致" in res, f"rerun verdict missing: {res!r}"
        print("rerun verdict:", res.replace("\n", " ")[:160])
        page.locator('[data-testid="archive-list"]').screenshot(
            path=str(OUT / "wave3-03-rerun.png")
        )
        print("wave3-03-rerun.png: rerun comparison rendered")

        # 4. Boxplot, dirty dataset, independent scale ON (default): every
        # column gets its own Y axis; small-scale columns must not be flat.
        page.goto(f"{BASE}/charts", wait_until="networkidle")
        page.wait_for_selector("select", timeout=15000)
        page.locator("select").first.select_option(str(ids["dirty"]))
        page.get_by_role("tab", name="箱线图").click()
        page.wait_for_selector('[data-testid="boxplot-independent"]', timeout=30000)
        plots = page.locator('[data-testid^="boxplot-col-"][data-chart-ready="true"]')
        plots.first.wait_for(timeout=30000)
        page.wait_for_timeout(800)
        n = plots.count()
        assert n >= 3, f"expected >=3 independent boxplots, got {n}"
        titles = page.locator('[data-testid="boxplot-independent"]').inner_text()
        assert "每列独立量纲" in titles, "independent-scale heading missing"
        assert "concentration" in titles, "concentration subplot missing"
        page.locator('[data-testid="boxplot-independent"]').screenshot(
            path=str(OUT / "wave3-04-boxplot.png")
        )
        print(f"wave3-04-boxplot.png: {n} independent-scale boxplots rendered")
        browser.close()
    print("all screenshots saved to", OUT)


if __name__ == "__main__":
    sys.exit(main())

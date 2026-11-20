"""Wave 2 screenshots: real headless Chromium (Playwright) visits the running
frontend /charts page, switches datasets / chart types / fields, waits until
the Plotly chart reports data-chart-ready="true", then screenshots.

Fails loudly if a chart never renders (no blank-canvas screenshots).
Usage: .venv/bin/python backend/scripts/screenshot_wave2.py
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


def wait_chart(page, title_part, timeout=30000):
    page.wait_for_selector('[data-testid="chart-plot"][data-chart-ready="true"]', timeout=timeout)
    page.wait_for_timeout(600)
    h3 = page.locator("h3").first.inner_text()
    assert title_part in h3, f"chart title {h3!r} does not contain {title_part!r}"
    return h3


def main():
    ids = dataset_ids()
    print("datasets:", ids)
    OUT.mkdir(parents=True, exist_ok=True)
    shots = [
        # (tab, dataset, filename, title-check, field-setup)
        ("直方图", "corr", "wave2-01-histogram.png", "直方图", "dose"),
        ("箱线图", "dirty", "wave2-02-boxplot.png", "箱线图", None),
        ("散点图", "corr", "wave2-03-scatter.png", "散点图", "dose-response"),
        ("折线图", "corr", "wave2-04-line.png", "折线图", "dose-response"),
        ("相关性热力图", "corr", "wave2-05-heatmap.png", "热力图", None),
        ("线性回归", "corr", "wave2-06-regression.png", "线性回归", "dose-response"),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.goto(f"{BASE}/charts", wait_until="networkidle")
        page.wait_for_selector("select", timeout=15000)
        for tab, ds_key, filename, title_part, setup in shots:
            page.locator("select").first.select_option(str(ids[ds_key]))
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(1000)  # let the field defaults + fetch start
            selects = page.locator("select")
            if setup == "dose":
                selects.nth(1).select_option("dose")
            elif setup == "dose-response":
                selects.nth(1).select_option("dose")
                selects.nth(2).select_option("response")
            title = wait_chart(page, title_part)
            page.screenshot(path=str(OUT / filename), full_page=True)
            print(f"{filename}: {title}")
        browser.close()
    print("all screenshots saved to", OUT)


if __name__ == "__main__":
    sys.exit(main())

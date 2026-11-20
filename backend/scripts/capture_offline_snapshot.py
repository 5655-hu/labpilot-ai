"""把运行中的 LabPilot 后端的全部响应抓成静态 JSON，供前端离线演示用。

用法（后端需已在 127.0.0.1:8000 运行）：
    python scripts/capture_offline_snapshot.py

输出：frontend/src/data/golden/index.json + d{id}.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API = os.environ.get("LABPILOT_API", "http://127.0.0.1:8000")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "..", "frontend", "src", "data", "golden")

NUMERIC_DTYPES = {"int64", "float64", "int32", "float32", "Int64", "Float64"}


def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = f"{API}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def try_call(path: str, method: str = "GET", body: dict | None = None) -> dict | None:
    try:
        return call(path, method, body)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:200]
        except Exception:  # noqa: BLE001
            pass
        print(f"  [skip] {method} {path} -> HTTP {exc.code} {detail}")
        return None
    except Exception as exc:  # noqa: BLE001 - 抓取失败就跳过，不污染快照
        print(f"  [skip] {method} {path} -> {exc}")
        return None


def guess_group_column(preview: dict) -> str | None:
    """挑一个基数低（≤8）的列做分组比较；连续变量不算。"""
    cols = preview["columns"]
    rows = preview["preview_rows"]
    best = None
    best_card = 1000
    for col in cols:
        if col["dtype"] in NUMERIC_DTYPES:
            continue
        values = {r.get(col["name"]) for r in rows}
        values.discard(None)
        values.discard("")
        card = len(values)
        if 2 <= card <= 8 and card < best_card:
            best, best_card = col["name"], card
    return best


def guess_numeric_pairs(preview: dict, columns: dict) -> list[tuple[str, str]]:
    """返回若干 (x, y) 数值列组合；跳过行号列，优先取有成对意义的列。"""
    row_id_cols = {"sample_id", "id", "index", "no"}
    numeric = [c["name"] for c in columns["columns"] if c["numeric"]]
    usable = [n for n in numeric if n.lower() not in row_id_cols]
    if len(usable) < 2:
        usable = numeric
    pairs = []
    if len(usable) >= 2:
        pairs.append((usable[0], usable[1]))
    if len(usable) >= 3:
        pairs.append((usable[0], usable[2]))
    return pairs


def capture_dataset(ds: dict) -> dict:
    ds_id = ds["id"]
    name = ds["name"]
    print(f"[capture] #{ds_id} {name} ({ds['rows_count']}x{ds['cols_count']})")

    pack: dict = {"dataset": ds}

    pack["preview"] = try_call(f"/api/datasets/{ds_id}/preview?limit=100")

    # 默认参数跑三件套，确保有 latest 可取
    audit_resp = try_call(
        f"/api/datasets/{ds_id}/audit",
        "POST",
        {"algorithms": ["iqr", "zscore"], "iqr_k": 1.5, "z_threshold": 3.0, "profile": "measurement"},
    )
    pack["audit"] = audit_resp

    stats_resp = try_call(f"/api/datasets/{ds_id}/stats", "POST")
    pack["stats"] = stats_resp

    report_resp = try_call(
        f"/api/datasets/{ds_id}/report", "POST", {"include_ai": False}
    )
    pack["report"] = report_resp

    charts: dict = {}
    columns = try_call(f"/api/datasets/{ds_id}/charts/columns")
    if columns:
        charts["columns"] = columns
        for col in columns["columns"]:
            if col["numeric"]:
                charts[f"histogram:{col['name']}"] = try_call(
                    f"/api/datasets/{ds_id}/charts/histogram?column={urllib.parse.quote(col['name'])}"
                )
        charts["boxplot"] = try_call(f"/api/datasets/{ds_id}/charts/boxplot")
        charts["heatmap"] = try_call(f"/api/datasets/{ds_id}/charts/heatmap")
        for x, y in guess_numeric_pairs(pack["preview"] or {"columns": [], "preview_rows": []}, columns):
            q = f"x={urllib.parse.quote(x)}&y={urllib.parse.quote(y)}"
            charts[f"scatter:{x}|{y}"] = try_call(f"/api/datasets/{ds_id}/charts/scatter?{q}")
            charts[f"line:{x}|{y}"] = try_call(f"/api/datasets/{ds_id}/charts/line?{q}")
            charts[f"regression:{x}|{y}"] = try_call(f"/api/datasets/{ds_id}/charts/regression?{q}")
    pack["charts"] = charts

    # 分组比较：自动找低基数列
    compare = None
    if pack["preview"]:
        group_col = guess_group_column(pack["preview"])
        numeric_cols = [
            c["name"] for c in (columns or {}).get("columns", []) if c["numeric"]
        ]
        if group_col and numeric_cols:
            compare = try_call(
                f"/api/datasets/{ds_id}/compare", "POST", {"group_col": group_col, "value_col": numeric_cols[0]}
            )
    pack["compare"] = compare

    # 归档：拿 audit 的分析 id
    archive = None
    if audit_resp and audit_resp.get("analysis_id"):
        archive = try_call(f"/api/analyses/{audit_resp['analysis_id']}/archive")
    pack["archive"] = archive

    # POST 响应本身不带 created_at；补一个生成时间，免得前端显示 "undefined"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for key in ("audit", "stats", "report", "compare"):
        if isinstance(pack.get(key), dict) and "created_at" not in pack[key]:
            pack[key]["created_at"] = stamp

    return pack


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    health = call("/health")
    datasets_resp = call("/api/datasets")
    analyses_resp = call("/api/analyses?limit=20&offset=0")

    # 接口单页上限有限，按 100 一页翻完
    collected: list[dict] = []
    offset = 0
    total = analyses_resp.get("total", 0)
    while offset < total:
        page = call(f"/api/analyses?limit=100&offset={offset}")
        batch = page.get("analyses", [])
        if not batch:
            break
        collected.extend(batch)
        offset += len(batch)
        if len(collected) >= page.get("total", total):
            break
    analyses_all = {"analyses": collected, "total": total}

    slim_keys = ("id", "dataset_id", "name", "status", "engine_version", "created_at", "finished_at")
    analyses_list = [
        {k: a.get(k) for k in slim_keys} for a in analyses_all.get("analyses", [])
    ]

    index = {
        "captured_at": datetime.now().astimezone().isoformat(),
        "api_base_at_capture": API,
        "health": health,
        "datasets": datasets_resp,
        "analyses": analyses_resp,
        "analyses_list": analyses_list,
        "analyses_total": analyses_all.get("total", len(analyses_list)),
        "dataset_ids": [d["id"] for d in datasets_resp["datasets"]],
    }

    for ds in datasets_resp["datasets"]:
        pack = capture_dataset(ds)
        path = os.path.join(OUT_DIR, f"d{ds['id']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pack, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"  -> {os.path.relpath(path, HERE)} ({os.path.getsize(path) / 1024:.1f} KB)")

    index_path = os.path.join(OUT_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"  -> {os.path.relpath(index_path, HERE)} ({os.path.getsize(index_path) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

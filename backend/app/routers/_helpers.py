"""Shared helpers for analysis routers (audit / stats).

An analysis run is one row in `analyses`: the resolved parameters, the
structured result JSON and the engine version that produced it. The
result JSON is the single source of truth — the frontend, charts, reports
and the archive all read this row, never a recomputed copy.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import store


def load_dataset_df(conn: sqlite3.Connection, dataset_id: int) -> pd.DataFrame:
    """Load the stored parsed CSV for a dataset, or raise LookupError."""
    rec = store.get_dataset(conn, dataset_id)
    if rec is None:
        raise LookupError("数据集不存在")
    path = Path(rec["file_path"])
    if not path.exists():
        raise FileNotFoundError(f"数据集文件丢失: {path}")
    return pd.read_csv(path)


def insert_analysis(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    name: str,
    params: dict,
    result: dict,
    engine_version: str,
) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO analyses (dataset_id, name, status, params_json, result_json,"
        " engine_version, created_at, finished_at) VALUES (?, ?, 'done', ?, ?, ?, ?, ?)",
        (
            dataset_id,
            name,
            json.dumps(params, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            engine_version,
            now,
            now,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_analysis(conn: sqlite3.Connection, *, dataset_id: int, name: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analyses WHERE dataset_id = ? AND name = ? AND status = 'done'"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (dataset_id, name),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    result_json = d.pop("result_json")
    d["result"] = json.loads(result_json) if result_json else None
    return d

"""Stats endpoints (Wave 2): compute stats, fetch the latest stats result."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..stats import ENGINE_VERSION, compute_stats
from ._helpers import insert_analysis, latest_analysis, load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/datasets", tags=["stats"])


@router.post("/{dataset_id}/stats")
def run_dataset_stats(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        df = load_dataset_df(conn, dataset_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="数据集不存在") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        result = compute_stats(df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    analysis_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="stats",
        params={"method": "pearson", "std_ddof": 1},
        result=result,
        engine_version=ENGINE_VERSION,
    )
    return {"analysis_id": analysis_id, "dataset_id": dataset_id, "stats": result}


@router.get("/{dataset_id}/stats")
def get_latest_stats(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    rec = latest_analysis(conn, dataset_id=dataset_id, name="stats")
    if rec is None:
        raise HTTPException(status_code=404, detail="该数据集尚无统计结果")
    return {
        "analysis_id": rec["id"],
        "dataset_id": dataset_id,
        "created_at": rec["created_at"],
        "stats": rec["result"],
    }

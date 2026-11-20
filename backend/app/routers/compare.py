"""Group-comparison endpoints (Wave 3): POST compare, GET latest compare.

The comparison result is stored as an analysis record (name="compare")
via insert_analysis, so the report / evidence chain / rerun modules read
the same row — the result JSON is the single source of truth.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..groups import ENGINE_VERSION, compare_groups
from ._helpers import insert_analysis, latest_analysis, load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/datasets", tags=["compare"])


class CompareRequest(BaseModel):
    group_col: str
    value_col: str
    groups: list | None = None
    override_test: str | None = None


@router.post("/{dataset_id}/compare")
def run_dataset_compare(
    dataset_id: int,
    body: CompareRequest,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        df = load_dataset_df(conn, dataset_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="数据集不存在") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        result = compare_groups(
            df,
            group_col=body.group_col,
            value_col=body.value_col,
            groups=body.groups,
            override_test=body.override_test,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    params = {
        "group_col": body.group_col,
        "value_col": body.value_col,
        "groups": body.groups,
        "override_test": body.override_test,
        "alpha": result["alpha"],
        "auto_test": result["auto_suggestion"],
        "selected_test": result["selected_test"],
        "overridden": result["overridden"],
    }
    analysis_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="compare",
        params=params,
        result=result,
        engine_version=ENGINE_VERSION,
    )
    return {"analysis_id": analysis_id, "dataset_id": dataset_id, "compare": result}


@router.get("/{dataset_id}/compare")
def get_latest_compare(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    rec = latest_analysis(conn, dataset_id=dataset_id, name="compare")
    if rec is None:
        raise HTTPException(status_code=404, detail="该数据集尚无分组比较结果")
    return {
        "analysis_id": rec["id"],
        "dataset_id": dataset_id,
        "created_at": rec["created_at"],
        "compare": rec["result"],
    }

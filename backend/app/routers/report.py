"""Report endpoints (Wave 3): assemble a full report, fetch the latest.

POST assembles the report (audit + stats + regression + evidence-backed
conclusions + AI / rule-based paragraph), stores the audit and stats runs
first so the conclusions' evidence can point at real analysis ids, then
stores the report itself as name="report". AI failure degrades to the
rule-based text with source="rule-based" — the deterministic sections are
identical either way.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import store
from ..audit import ENGINE_VERSION as AUDIT_ENGINE_VERSION
from ..report import ENGINE_VERSION as REPORT_ENGINE_VERSION, assemble_report
from ..stats import ENGINE_VERSION as STATS_ENGINE_VERSION
from ._helpers import insert_analysis, latest_analysis, load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/datasets", tags=["report"])


class ReportRequest(BaseModel):
    include_ai: bool = True


def _get_dataset_or_404(conn: sqlite3.Connection, dataset_id: int) -> dict:
    rec = store.get_dataset(conn, dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return rec


@router.post("/{dataset_id}/report")
def create_report(
    dataset_id: int,
    body: ReportRequest,
    conn: sqlite3.Connection = Depends(get_conn),
):
    rec = _get_dataset_or_404(conn, dataset_id)
    try:
        df = load_dataset_df(conn, dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        report = assemble_report(rec, df, include_ai=body.include_ai)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Store the deterministic runs first so evidence can cite real ids.
    audit_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="audit",
        params=report["audit"]["params"],
        result=report["audit"],
        engine_version=AUDIT_ENGINE_VERSION,
    )
    stats_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="stats",
        params={"method": "pearson", "std_ddof": 1},
        result=report["stats"],
        engine_version=STATS_ENGINE_VERSION,
    )
    ids = {"audit": [audit_id], "stats": [stats_id]}
    for c in report["conclusions"]:
        ev = c["evidence"]
        ev["analysis_ids"] = ids.get(ev.get("analysis"), [])
    report["audit_analysis_id"] = audit_id
    report["stats_analysis_id"] = stats_id
    report_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="report",
        params=report["params"],
        result=report,
        engine_version=REPORT_ENGINE_VERSION,
    )
    return {"analysis_id": report_id, "dataset_id": dataset_id, "report": report}


@router.get("/{dataset_id}/report")
def get_latest_report(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    _get_dataset_or_404(conn, dataset_id)
    rec = latest_analysis(conn, dataset_id=dataset_id, name="report")
    if rec is None:
        raise HTTPException(status_code=404, detail="该数据集尚无报告")
    return {
        "analysis_id": rec["id"],
        "dataset_id": dataset_id,
        "created_at": rec["created_at"],
        "report": rec["result"],
    }

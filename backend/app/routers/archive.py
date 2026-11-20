"""Reproducibility archive endpoints (Wave 4, plan SS9).

Archives are assembled on demand from the stored analysis row and the
dataset row (see app/archive.py) — there is no separate archive table,
so the archive is always consistent with the analysis it describes and
works unchanged on SQLite and on Turso.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..archive import build_archive, build_rerun_package
from .. import store
from .analyses import _get_analysis_or_404, _row_to_dict
from .datasets import get_conn

router = APIRouter(prefix="/api", tags=["archive"])


@router.get("/analyses/{analysis_id}/archive")
def get_analysis_archive(analysis_id: int, conn=Depends(get_conn)):
    analysis = _get_analysis_or_404(conn, analysis_id)
    try:
        return build_archive(conn, analysis)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/analyses/{analysis_id}/archive/export")
def export_rerun_package(analysis_id: int, conn=Depends(get_conn)):
    analysis = _get_analysis_or_404(conn, analysis_id)
    try:
        archive = build_archive(conn, analysis)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    package = build_rerun_package(archive)
    filename = f"labpilot-rerun-analysis-{analysis_id}.json"
    return JSONResponse(
        content=package,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/datasets/{dataset_id}/archives")
def list_dataset_archives(dataset_id: int, conn=Depends(get_conn)):
    rec = store.get_dataset(conn, dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    rows = conn.execute(
        "SELECT * FROM analyses WHERE dataset_id = ? ORDER BY created_at DESC, id DESC",
        (dataset_id,),
    ).fetchall()
    archives = []
    for row in rows:
        analysis = _row_to_dict(row)
        archives.append(build_archive(conn, analysis))
    return {"dataset_id": dataset_id, "archives": archives, "total": len(archives)}

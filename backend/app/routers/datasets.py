"""Dataset endpoints (Wave 1): list / upload / preview / delete."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import store
from ..db import connect

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("")
def list_datasets(conn: sqlite3.Connection = Depends(get_conn)):
    datasets = store.list_datasets(conn)
    return {"datasets": datasets, "total": len(datasets)}


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    content = await file.read()
    try:
        rec = store.store_upload(conn, filename=file.filename or "upload", content=content)
    except store.UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return rec


@router.get("/{dataset_id}/preview")
def preview_dataset(dataset_id: int, limit: int = 100, conn: sqlite3.Connection = Depends(get_conn)):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit 须在 1~1000 之间")
    rec = store.preview_dataset(conn, dataset_id, limit=limit)
    if rec is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return rec


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    if not store.delete_dataset(conn, dataset_id):
        raise HTTPException(status_code=404, detail="数据集不存在")
    return {"deleted": dataset_id}

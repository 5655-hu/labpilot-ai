"""Chart endpoints (Wave 3 in the plan / user Wave 2: charts).

All endpoints are read-only GETs: they compute chart data from the stored
dataset and return Plotly-ready payloads. Nothing is stored as an analysis
record — charts are on-demand views of the data, not analysis runs.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import charts
from ._helpers import load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/datasets", tags=["charts"])


def _load(conn: sqlite3.Connection, dataset_id: int):
    try:
        return load_dataset_df(conn, dataset_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="数据集不存在") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{dataset_id}/charts/columns")
def chart_columns(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    df = _load(conn, dataset_id)
    return {"dataset_id": dataset_id, "columns": charts.list_columns(df)}


@router.get("/{dataset_id}/charts/histogram")
def chart_histogram(
    dataset_id: int,
    column: str = Query(..., description="数值列"),
    bins: int | None = Query(None, description="分箱数，1~100，不填自动"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    df = _load(conn, dataset_id)
    result = _run(charts.histogram, df, column, bins)
    return {"dataset_id": dataset_id, "chart": result}


@router.get("/{dataset_id}/charts/boxplot")
def chart_boxplot(
    dataset_id: int,
    columns: str | None = Query(None, description="逗号分隔的列名，不填为全部数值列"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    df = _load(conn, dataset_id)
    wanted = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    result = _run(charts.boxplot, df, wanted)
    return {"dataset_id": dataset_id, "chart": result}


@router.get("/{dataset_id}/charts/scatter")
def chart_scatter(
    dataset_id: int,
    x: str = Query(...),
    y: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    df = _load(conn, dataset_id)
    result = _run(charts.scatter, df, x, y)
    return {"dataset_id": dataset_id, "chart": result}


@router.get("/{dataset_id}/charts/line")
def chart_line(
    dataset_id: int,
    x: str = Query(...),
    y: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    df = _load(conn, dataset_id)
    result = _run(charts.line, df, x, y)
    return {"dataset_id": dataset_id, "chart": result}


@router.get("/{dataset_id}/charts/heatmap")
def chart_heatmap(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    df = _load(conn, dataset_id)
    result = _run(charts.heatmap, df)
    return {"dataset_id": dataset_id, "chart": result}


@router.get("/{dataset_id}/charts/regression")
def chart_regression(
    dataset_id: int,
    x: str = Query(...),
    y: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    df = _load(conn, dataset_id)
    result = _run(charts.regression, df, x, y)
    return {"dataset_id": dataset_id, "chart": result}

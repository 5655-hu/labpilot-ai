"""Audit endpoints (Wave 2): run an audit, fetch the latest audit result."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from ..audit import ENGINE_VERSION, PROFILES, run_audit
from ._helpers import insert_analysis, latest_analysis, load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/datasets", tags=["audit"])


class AuditRequest(BaseModel):
    algorithms: list[str] = ["iqr"]
    iqr_k: float = 1.5
    z_threshold: float = 3.0
    profile: str = "measurement"
    weights: dict[str, float] | None = None
    allowed_missing_columns: list[str] = []
    range_rules: dict[str, dict[str, float]] = {}
    per_column_algorithms: dict[str, list[str]] = {}

    @field_validator("algorithms")
    @classmethod
    def _check_algorithms(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("至少选择一种异常值检测算法")
        bad = sorted({a for a in v if a.lower() not in ("iqr", "zscore")})
        if bad:
            raise ValueError(f"不支持的异常值算法: {bad}（可用 iqr / zscore）")
        return [a.lower() for a in v]

    @field_validator("iqr_k")
    @classmethod
    def _check_iqr_k(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("IQR 倍数 k 必须大于 0")
        return v

    @field_validator("z_threshold")
    @classmethod
    def _check_z(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Z-score 阈值必须大于 0")
        return v

    @field_validator("profile")
    @classmethod
    def _check_profile(cls, v: str) -> str:
        if v not in PROFILES:
            raise ValueError(f"不支持的规则画像: {v}（可用 {sorted(PROFILES)}）")
        return v


@router.post("/{dataset_id}/audit")
def run_dataset_audit(
    dataset_id: int,
    body: AuditRequest,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        df = load_dataset_df(conn, dataset_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="数据集不存在") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        result = run_audit(
            df,
            algorithms=body.algorithms,
            iqr_k=body.iqr_k,
            z_threshold=body.z_threshold,
            profile=body.profile,
            weights=body.weights,
            allowed_missing_columns=body.allowed_missing_columns,
            range_rules=body.range_rules,
            per_column_algorithms=body.per_column_algorithms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    analysis_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name="audit",
        params=result["params"],
        result=result,
        engine_version=ENGINE_VERSION,
    )
    return {"analysis_id": analysis_id, "dataset_id": dataset_id, "audit": result}


@router.get("/{dataset_id}/audit")
def get_latest_audit(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    rec = latest_analysis(conn, dataset_id=dataset_id, name="audit")
    if rec is None:
        raise HTTPException(status_code=404, detail="该数据集尚无审计结果")
    return {
        "analysis_id": rec["id"],
        "dataset_id": dataset_id,
        "created_at": rec["created_at"],
        "audit": rec["result"],
    }

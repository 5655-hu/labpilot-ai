"""Analysis history endpoint (Wave 1: list only; runs land in Wave 2+).

Wave 3 adds: single-record fetch and rerun with the original parameters
(plan §9A). Reruns of audit / stats / report recompute the deterministic
parts with the stored params; a report rerun reuses the original AI text
and never calls the model again. Wave 4 adds compare reruns (same params,
same derivation). Unsupported types (e.g. charts, which are on-demand
views and never stored) return 400.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import store
from ..db import connect
from ..report import diff_results
from ._helpers import insert_analysis, load_dataset_df
from .datasets import get_conn

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

RERUNNABLE = ("audit", "stats", "report", "compare")


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    result_json = d.pop("result_json")
    d["result"] = json.loads(result_json) if result_json else None
    return d


def _get_analysis_or_404(conn: sqlite3.Connection, analysis_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    return _row_to_dict(row)


@router.get("/{analysis_id}")
def get_analysis(analysis_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return _get_analysis_or_404(conn, analysis_id)


@router.post("/{analysis_id}/rerun")
def rerun_analysis(analysis_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    orig = _get_analysis_or_404(conn, analysis_id)
    name = orig["name"]
    params = orig["params"]
    orig_result = orig["result"]
    if orig_result is None:
        raise HTTPException(status_code=400, detail="原分析无结果，无法重跑")
    if name not in RERUNNABLE:
        raise HTTPException(
            status_code=400,
            detail=f"分析类型 {name} 不支持重跑（仅支持 audit / stats / report / compare）",
        )
    dataset_id = orig["dataset_id"]
    rec = store.get_dataset(conn, dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    try:
        df = load_dataset_df(conn, dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        if name == "audit":
            from ..audit import ENGINE_VERSION, run_audit

            new_result = run_audit(df, **params)
            engine_version = ENGINE_VERSION
        elif name == "stats":
            from ..stats import ENGINE_VERSION, compute_stats

            new_result = compute_stats(df)
            engine_version = ENGINE_VERSION
        elif name == "compare":
            # Wave 4: rerun a group comparison with the original inputs
            # (group_col / value_col / groups / override_test). The stored
            # params also carry the derived fields (alpha, auto_test,
            # selected_test); compare_groups re-derives those, so only the
            # four inputs are passed — the diff then proves the derivation
            # itself is stable.
            from ..groups import ENGINE_VERSION, compare_groups

            new_result = compare_groups(
                df,
                group_col=params["group_col"],
                value_col=params["value_col"],
                groups=params.get("groups"),
                override_test=params.get("override_test"),
            )
            engine_version = ENGINE_VERSION
        else:  # report — deterministic parts only; AI text is reused, never re-called
            from ..audit import ENGINE_VERSION as AUDIT_ENGINE_VERSION
            from ..report import (
                ENGINE_VERSION,
                assemble_report,
                check_numbers,
            )
            from ..stats import ENGINE_VERSION as STATS_ENGINE_VERSION

            new_report = assemble_report(
                rec,
                df,
                include_ai=False,
                audit_params=params.get("audit"),
            )
            # Reuse the original AI paragraph verbatim (no new model call).
            new_report["ai_text"] = orig_result.get("ai_text")
            new_report["source"] = orig_result.get("source", "rule-based")
            new_report["tokens"] = orig_result.get("tokens")
            new_report["send_manifest"] = orig_result.get("send_manifest")
            new_report["params"] = params
            new_report["rerun_note"] = (
                "重跑：确定性部分按原参数重算；AI 文本沿用原报告，未重新调用模型。"
            )
            new_report["number_check"] = check_numbers(
                new_report["ai_text"], new_report
            )
            # Store the deterministic runs first, as the report endpoint does.
            audit_id = insert_analysis(
                conn,
                dataset_id=dataset_id,
                name="audit",
                params=new_report["audit"]["params"],
                result=new_report["audit"],
                engine_version=AUDIT_ENGINE_VERSION,
            )
            stats_id = insert_analysis(
                conn,
                dataset_id=dataset_id,
                name="stats",
                params={"method": "pearson", "std_ddof": 1},
                result=new_report["stats"],
                engine_version=STATS_ENGINE_VERSION,
            )
            ids = {"audit": [audit_id], "stats": [stats_id]}
            for c in new_report["conclusions"]:
                ev = c["evidence"]
                ev["analysis_ids"] = ids.get(ev.get("analysis"), [])
            new_report["audit_analysis_id"] = audit_id
            new_report["stats_analysis_id"] = stats_id
            new_result = new_report
            engine_version = ENGINE_VERSION
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    differences = diff_results(orig_result, new_result)
    rerun_id = insert_analysis(
        conn,
        dataset_id=dataset_id,
        name=name,
        params=params,
        result=new_result,
        engine_version=engine_version,
    )
    return {
        "original_id": analysis_id,
        "rerun_id": rerun_id,
        "name": name,
        "consistent": len(differences) == 0,
        "differences": differences,
        "original_engine_version": orig["engine_version"],
        "engine_version": engine_version,
        "engine_version_changed": orig["engine_version"] != engine_version,
    }


@router.get("")
def list_analyses(
    conn: sqlite3.Connection = Depends(get_conn),
    limit: int = Query(20, ge=1, le=100, description="每页条数（默认 20，最大 100）"),
    offset: int = Query(0, ge=0, description="跳过条数"),
):
    """Analysis history, newest first, paginated (Wave 5).

    `total` is always the full count (not the page size) so callers can
    compute page counts; the page itself is sliced with LIMIT/OFFSET.
    """
    total = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM analyses ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d.pop("params_json"))
        result_json = d.pop("result_json")
        d["result"] = json.loads(result_json) if result_json else None
        out.append(d)
    return {"analyses": out, "total": total}

"""Reproducibility archive (Wave 4, plan SS9).

An archive is assembled on demand from the stored analysis row and the
dataset row — no new table, so nothing about the schema changes and the
same code works on SQLite and on Turso. The archive answers "can someone
else, given this package, reproduce the same numbers?": dataset SHA-256,
environment (real installed dependency versions), cleaning rules, the
full original parameters, engine + code versions, the random-seed note
and a snapshot of the structured result.

Deterministic by construction: every engine in this project is
deterministic (audit / stats / compare / report / regression), so the
seed entry records "no randomness" instead of inventing a seed.
"""
from __future__ import annotations

import json
import platform
import sys
from datetime import datetime

from . import VERSION, store

ARCHIVE_VERSION = "1.0"

_DEPENDENCIES = ("pandas", "numpy", "scipy", "scikit-learn", "fastapi")

# Cleaning rules as actually implemented in app/audit.py (not a paraphrase
# of the plan): these are the rules any rerun must apply to get the same
# numbers. Values that come from the audit parameters are filled in per
# analysis; the fixed policy lines below never change.
CLEANING_POLICY = [
    "不删除任何原始数据：检出的异常点只标注为“待确认”，不自动删除、不自动修正。",
    "哨兵缺失码 -999 / -9999 / -99999 / 999999 判为确定错误，不当作真实测量值。",
    "带单位的数值文本（如 25.3C、0.52 mol/L）判为类型错误，建议清洗为纯数值并把单位单独成列。",
    "数值列判定：非空值中可转为数值的比例 ≥ 50% 且至少有 1 个可转数值时，该列按数值列处理；否则按分类型处理。",
    "缺失处理：按列统计缺失；画像或逐列设置允许缺失的列不计入有效缺失率。",
    "统计异常（IQR / Z-score 检出）不扣分、不删除，只给保留 / 复核 / 剔除三种处理建议，由用户决定。",
]


def dependency_versions() -> dict:
    """Real installed versions, read from importlib.metadata (never hardcoded)."""
    from importlib.metadata import version as _pkg_version

    out = {}
    for name in _DEPENDENCIES:
        try:
            out[name] = _pkg_version(name)
        except Exception:
            out[name] = None
    return out


def environment_snapshot() -> dict:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependencies": dependency_versions(),
    }


def _audit_rule_snapshot(conn, dataset_id: int, params: dict, name: str) -> dict:
    """Cleaning-rule snapshot for this analysis.

    Audit analyses carry their own rules in params. Other analyses reuse
    the dataset's latest audit run when one exists, so the archive still
    records which rules the underlying data was judged by; otherwise the
    engine defaults are recorded and marked as defaults.
    """
    from .audit import (
        DEFAULT_ALGORITHMS,
        DEFAULT_IQR_K,
        DEFAULT_PROFILE,
        DEFAULT_Z_THRESHOLD,
        PROFILES,
        SENTINEL_VALUES,
    )
    from .routers._helpers import latest_analysis

    if name == "audit":
        p = params
        source = "本次审计参数"
    else:
        latest = latest_analysis(conn, dataset_id=dataset_id, name="audit")
        if latest is not None:
            p = latest["params"]
            source = f"数据集最近一次审计（分析 #{latest['id']}）的参数"
        else:
            p = {}
            source = "引擎默认值（该数据集尚无审计记录）"

    profile = p.get("profile", DEFAULT_PROFILE)
    weights = p.get("weights") or dict(PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])["weights"])
    return {
        "source": source,
        "policy": CLEANING_POLICY,
        "profile": profile,
        "profile_label": PROFILES.get(profile, {}).get("label"),
        "weights": weights,
        "score_formula": (
            "score = 100 - (missing×有效缺失率 + duplicate×重复行率"
            " + type_error×类型错误率 + definite_error×确定错误率)；统计异常不扣分"
        ),
        "algorithms": list(p.get("algorithms", list(DEFAULT_ALGORITHMS))),
        "iqr_k": p.get("iqr_k", DEFAULT_IQR_K),
        "z_threshold": p.get("z_threshold", DEFAULT_Z_THRESHOLD),
        "allowed_missing_columns": list(p.get("allowed_missing_columns", [])),
        "range_rules": p.get("range_rules", {}),
        "per_column_algorithms": p.get("per_column_algorithms", {}),
        "sentinel_missing_values": sorted(SENTINEL_VALUES),
    }


def build_archive(conn, analysis: dict) -> dict:
    """Assemble the full archive for one stored analysis row.

    `analysis` is the dict shape returned by routers.analyses._row_to_dict
    (params / result already parsed from JSON). Raises LookupError when
    the dataset row is gone.
    """
    dataset_id = analysis["dataset_id"]
    rec = store.get_dataset(conn, dataset_id)
    if rec is None:
        raise LookupError("数据集不存在")
    columns = json.loads(rec["columns_json"])
    env = environment_snapshot()
    name = analysis["name"]
    return {
        "archive_version": ARCHIVE_VERSION,
        "analysis_id": analysis["id"],
        "analysis_type": name,
        "dataset_id": dataset_id,
        "dataset": {
            "id": rec["id"],
            "name": rec["name"],
            "filename": rec["filename"],
            "source": rec["source"],
            "rows": rec["rows_count"],
            "cols": rec["cols_count"],
            "columns": columns,
            "created_at": rec["created_at"],
        },
        "data_fingerprint": {
            "algorithm": "SHA-256",
            "file_hash": rec["file_hash"],
            "note": "解析后数据的 SHA-256，与数据集上传时记录的 file_hash 一致；文件内容不变则哈希不变。",
        },
        "environment": env,
        "code_version": VERSION,
        "engine": name,
        "engine_version": analysis["engine_version"],
        "cleaning_rules": _audit_rule_snapshot(conn, dataset_id, analysis["params"], name),
        "params": analysis["params"],
        "random_seed": {
            "seed": None,
            "note": (
                "本分析无随机性：审计、统计、分组比较、报告与线性回归均为确定性计算，"
                "不使用随机种子；线性回归为确定性最小二乘求解，无 random_state。"
            ),
        },
        "result_snapshot": analysis["result"],
        "analysis_created_at": analysis["created_at"],
        "analysis_finished_at": analysis["finished_at"],
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rerun": {
            "supported": name in ("audit", "stats", "report", "compare"),
            "endpoint": f"POST /api/analyses/{analysis['id']}/rerun",
            "note": (
                "用原参数重跑同一分析并与本档案的结果快照逐项比对；"
                "报告重跑沿用原 AI 文本，不重新调用模型。"
                if name in ("audit", "stats", "report", "compare")
                else "该分析类型为即时视图，未入库，不支持重跑。"
            ),
        },
    }


def build_rerun_package(archive: dict) -> dict:
    """One-click rerun package: everything needed to reproduce the run.

    The package carries no raw data rows (privacy boundary) and no
    secrets — only the dataset fingerprint, the full parameters, the
    code/engine versions and the expected result snapshot to compare
    against after a rerun.
    """
    return {
        "format": "labpilot-rerun-package",
        "format_version": 1,
        "archive_version": archive["archive_version"],
        "analysis_id": archive["analysis_id"],
        "analysis_type": archive["analysis_type"],
        "dataset_id": archive["dataset_id"],
        "dataset": {
            "name": archive["dataset"]["name"],
            "filename": archive["dataset"]["filename"],
            "file_hash": archive["data_fingerprint"]["file_hash"],
            "hash_algorithm": "SHA-256",
            "rows": archive["dataset"]["rows"],
            "cols": archive["dataset"]["cols"],
            "columns": archive["dataset"]["columns"],
        },
        "params": archive["params"],
        "cleaning_rules": archive["cleaning_rules"],
        "random_seed": archive["random_seed"],
        "engine": archive["engine"],
        "engine_version": archive["engine_version"],
        "code_version": archive["code_version"],
        "environment": archive["environment"],
        "expected_result": archive["result_snapshot"],
        "rerun": {
            "method": "POST",
            "endpoint": archive["rerun"]["endpoint"],
            "howto": (
                "在本项目后端运行后，用原数据集调用 "
                f"{archive['rerun']['endpoint']}（无需传参，服务端取原参数重跑），"
                "再将返回的新结果与本包 expected_result 逐项比对；"
                "比对时忽略时间戳、token 用量等易变字段，与后端 rerun 接口的比对口径一致。"
            ),
        },
        "exported_at": archive["archived_at"],
    }

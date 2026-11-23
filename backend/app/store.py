"""Dataset storage: parse, hash, persist metadata, seed golden data.

Uploads are parsed with pandas, normalised to CSV and stored under
backend/data/uploads/{id}.csv together with their SHA-256. Only the parsed
data + hash are kept (no raw-file blob); production (Wave 5) moves the parsed
file to Turso/object storage — the metadata row is unchanged.

Wave 6 write guards
-------------------
* Golden protection: rows with source == GOLDEN_SOURCE are never deletable.
  `source` is the single source of truth (schema.sql + seed_golden); dataset
  names and golden_manifest.json are display/generation artefacts and are
  deliberately NOT used for the check.
* DEMO_READ_ONLY=1 freezes the dataset library (upload + delete). Analysis
  runs are still allowed — they only append to `analyses`. Seeding is exempt
  so a read-only demo still boots with its three golden datasets.

Both guards raise dedicated exceptions; app/main.py maps them to HTTP 403.
The store never imports FastAPI, so it stays usable from scripts and tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BACKEND_DIR / "data" / "uploads"
GOLDEN_DIR = BACKEND_DIR / "data" / "golden"

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 100_000
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}

UPLOAD_SOURCE = "upload"
GOLDEN_SOURCE = "golden"
TRUTHY = frozenset({"1", "true", "yes", "on"})


class UploadRejected(ValueError):
    """Raised for invalid uploads; the API maps this to HTTP 400."""


class GoldenDatasetProtected(Exception):
    """Raised when deleting a seeded golden dataset; the API maps this to 403."""


class ReadOnlyMode(Exception):
    """Raised when DEMO_READ_ONLY blocks a library write; the API maps this to 403."""


def read_only_enabled() -> bool:
    """Read the flag on every call so tests can monkeypatch the environment."""
    return os.environ.get("DEMO_READ_ONLY", "").strip().lower() in TRUTHY


def is_golden(rec: dict | None) -> bool:
    return bool(rec) and rec.get("source") == GOLDEN_SOURCE


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_dataframe(path: Path, suffix: str) -> pd.DataFrame:
    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path, engine="openpyxl")
    except Exception as exc:  # unreadable / corrupt file
        raise UploadRejected(f"文件无法解析为表格数据: {exc}") from exc


def insert_dataset(
    conn: sqlite3.Connection,
    *,
    name: str,
    filename: str,
    df: pd.DataFrame,
    source: str,
    stored_path: Path,
) -> dict:
    columns = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]
    cur = conn.execute(
        "INSERT INTO datasets (name, filename, file_hash, rows_count, cols_count,"
        " columns_json, source, file_path) VALUES (?,?,?,?,?,?,?,?)",
        (
            name,
            filename,
            sha256_file(stored_path),
            int(len(df)),
            int(len(df.columns)),
            json.dumps(columns, ensure_ascii=False),
            source,
            str(stored_path),
        ),
    )
    conn.commit()
    return get_dataset(conn, cur.lastrowid)


def get_dataset(conn: sqlite3.Connection, dataset_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    return dict(row) if row else None


def list_datasets(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM datasets ORDER BY created_at DESC, id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["columns"] = json.loads(d.pop("columns_json"))
        out.append(d)
    return out


def store_upload(conn: sqlite3.Connection, *, filename: str, content: bytes) -> dict:
    if read_only_enabled():
        raise ReadOnlyMode("演示模式为只读：已关闭上传。关闭 DEMO_READ_ONLY 后重试。")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"只支持 CSV / XLSX 文件, 不支持 {suffix or '无后缀'} 文件")
    if len(content) > MAX_FILE_BYTES:
        raise UploadRejected(f"文件超过 10 MB 上限 (实际 {len(content) / 1024 / 1024:.1f} MB)")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOADS_DIR / f"_tmp_{hashlib.md5(content).hexdigest()}{suffix}"
    tmp.write_bytes(content)
    try:
        df = _parse_dataframe(tmp, suffix)
    except UploadRejected:
        tmp.unlink(missing_ok=True)
        raise
    if len(df) == 0:
        tmp.unlink(missing_ok=True)
        raise UploadRejected("文件没有数据行")
    if len(df) > MAX_ROWS:
        tmp.unlink(missing_ok=True)
        raise UploadRejected(f"行数超过 100000 行上限 (实际 {len(df)} 行)")
    # Normalise to CSV so preview / later analysis always read one format.
    rec = insert_dataset(
        conn,
        name=Path(filename).stem,
        filename=filename,
        df=df,
        source=UPLOAD_SOURCE,
        stored_path=tmp,  # hash is computed before the rename below
    )
    final = UPLOADS_DIR / f"{rec['id']}.csv"
    # os.replace overwrites an existing target atomically on POSIX *and* on
    # Windows; Path.rename() maps to os.rename(), which raises FileExistsError
    # on Windows when the target already exists (e.g. a reused row id).
    os.replace(tmp, final)
    conn.execute("UPDATE datasets SET file_path = ? WHERE id = ?", (str(final), rec["id"]))
    conn.commit()
    return get_dataset(conn, rec["id"])


def delete_dataset(conn: sqlite3.Connection, dataset_id: int) -> bool:
    """Delete an uploaded dataset. False when unknown (API → 404).

    Golden datasets raise GoldenDatasetProtected (API → 403); in read-only
    demo mode any deletion raises ReadOnlyMode (API → 403).
    """
    rec = get_dataset(conn, dataset_id)
    if rec is None:
        return False
    if is_golden(rec):
        raise GoldenDatasetProtected("黄金演示数据集受保护，不可删除。")
    if read_only_enabled():
        raise ReadOnlyMode("演示模式为只读：已关闭删除。关闭 DEMO_READ_ONLY 后重试。")
    conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    if rec.get("file_path"):
        Path(rec["file_path"]).unlink(missing_ok=True)
    return True


def preview_dataset(conn: sqlite3.Connection, dataset_id: int, limit: int = 100) -> dict | None:
    rec = get_dataset(conn, dataset_id)
    if rec is None:
        return None
    path = Path(rec["file_path"])
    df = pd.read_csv(path, nrows=limit)
    columns = json.loads(rec["columns_json"])
    return {
        "id": rec["id"],
        "name": rec["name"],
        "filename": rec["filename"],
        "rows": rec["rows_count"],
        "cols": rec["cols_count"],
        "columns": columns,
        "preview_rows": df.head(limit).fillna("").astype(str).to_dict(orient="records"),
        "preview_limit": limit,
        "file_hash": rec["file_hash"],
    }


def seed_golden(conn: sqlite3.Connection) -> list[dict]:
    """Insert the three golden demo datasets when the library is empty.

    Idempotent: only runs when the datasets table has zero rows. The golden
    CSVs are copied into uploads/ so preview works exactly like uploads.
    Exempt from DEMO_READ_ONLY — a read-only demo still needs its library.
    """
    count = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    if count > 0:
        return []
    manifest = json.loads((GOLDEN_DIR / "golden_manifest.json").read_text(encoding="utf-8"))
    names = {
        "clean": "干净实验数据（黄金演示）",
        "dirty": "脏数据演示集（黄金演示）",
        "corr": "相关性与回归数据（黄金演示）",
    }
    seeded = []
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for key in ("clean", "dirty", "corr"):
        src = GOLDEN_DIR / manifest["datasets"][key]["file"]
        df = pd.read_csv(src)
        dest = UPLOADS_DIR / f"golden_{key}.csv"
        shutil.copyfile(src, dest)
        seeded.append(
            insert_dataset(
                conn,
                name=names[key],
                filename=src.name,
                df=df,
                source=GOLDEN_SOURCE,
                stored_path=dest,
            )
        )
    return seeded

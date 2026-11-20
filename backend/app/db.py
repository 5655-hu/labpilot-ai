"""Database layer: local SQLite file, Turso (libSQL) by DATABASE_URL.

Connection selection (DATABASE_URL):
  - unset            -> backend/data/labpilot.db (local dev default)
  - sqlite:///path   -> that SQLite file (any path, e.g. a persistent volume)
  - libsql://...     -> Turso cloud SQLite (or a local sqld server over
                        http://...). Needs the libsql-experimental client
                        (requirements.txt) and TURSO_AUTH_TOKEN in the
                        environment when the server requires auth. See
                        docs/turso_setup.md. Never put a token in code.
  - anything else    -> RuntimeError with an explicit message.

Adapter design (Wave 4): both backends are reached through one small
interface — `connect()` returns an object with the sqlite3 methods the
rest of the codebase already uses (`execute`, `executemany`,
`executescript`, `commit`, `rollback`, `close`, context-manager use).
Rows behave like sqlite3.Row: index access (`row[0]`), key access
(`row["id"]`) and `dict(row)` all work, on either backend. No SQL lives
here and no SQL was moved: routers / store keep their queries unchanged.

libSQL specifics (learned by probing libsql-experimental 0.0.55 against
a local sqld 0.24.32):
  - parameters must be a tuple, not a list;
  - rows come back as plain tuples; column names come from
    cursor.description, so the adapter wraps them in Row;
  - `executescript` exists on the client but is executed statement by
    statement here so schema.sql behaves identically on both backends;
  - remote mode keeps an embedded replica file locally; its path is
    LIBSQL_LOCAL_PATH or backend/data/libsql-replica.db. The replica is
    a sync cache — Turso stays the source of truth.
  - PRAGMA foreign_keys is a SQLite-local setting and is not sent to a
    remote server.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / "data" / "labpilot.db"
DEFAULT_REPLICA = BACKEND_DIR / "data" / "libsql-replica.db"
SCHEMA_PATH = BACKEND_DIR / "schema.sql"


def resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{DEFAULT_DB}"
    return url


def backend_kind(database_url: str | None = None) -> str:
    """'sqlite' or 'libsql' for a DATABASE_URL (default: the configured one)."""
    url = database_url or resolve_database_url()
    if url.startswith("libsql://") or url.startswith("libsql:"):
        return "libsql"
    if url.startswith("http://") or url.startswith("https://"):
        return "libsql"
    return "sqlite"


# ---------------------------------------------------------------------------
# Row: tuple subclass that also behaves like sqlite3.Row
# ---------------------------------------------------------------------------

class Row(tuple):
    """A result row: tuple order + name lookup + dict(row), like sqlite3.Row."""

    def __new__(cls, values, keys):
        obj = super().__new__(cls, tuple(values))
        obj._keys = tuple(keys)
        return obj

    def keys(self):
        return list(self._keys)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                idx = self._keys.index(key)
            except ValueError:
                raise KeyError(key) from None
            return super().__getitem__(idx)
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# libSQL adapter: wraps a libsql_experimental connection/cursor
# ---------------------------------------------------------------------------

class LibSQLCursor:
    """sqlite3-cursor-shaped wrapper around a libsql_experimental cursor."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._description = None

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def description(self):
        return self._cursor.description

    def _wrap(self, rows):
        if rows is None:
            return None
        keys = [d[0] for d in (self._cursor.description or [])]
        return [Row(r, keys) for r in rows]

    def execute(self, sql, parameters=()):
        if parameters is None:
            parameters = ()
        if not isinstance(parameters, tuple):
            parameters = tuple(parameters)
        # libsql Connection.execute() returns a fresh Cursor (not self),
        # so keep the returned cursor for description / fetching.
        self._cursor = self._cursor.execute(sql, parameters)
        self._description = self._cursor.description
        return self

    def executemany(self, sql, seq_of_parameters):
        for params in seq_of_parameters:
            self.execute(sql, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        keys = [d[0] for d in (self._cursor.description or [])]
        return Row(row, keys)

    def fetchall(self):
        return self._wrap(self._cursor.fetchall())

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        return self._wrap(rows)


class LibSQLConnection:
    """sqlite3-connection-shaped wrapper around a libsql_experimental connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, parameters=()):
        return LibSQLCursor(self._conn).execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        cur = LibSQLCursor(self._conn)
        return cur.executemany(sql, seq_of_parameters)

    def executescript(self, script: str):
        # Run statement by statement so schema.sql behaves the same on
        # both backends (comments stripped by the split below).
        for stmt in _split_statements(script):
            self._conn.execute(stmt)
        return LibSQLCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on ';' outside of line comments and strings.

    schema.sql is plain DDL with -- comments and no semicolons inside
    string literals, so a small state machine is enough; this is only
    used for the libSQL path.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    while i < len(script):
        ch = script[i]
        if in_string:
            buf.append(ch)
            if ch == "'":
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < len(script) and script[i + 1] == "-":
            while i < len(script) and script[i] != "\n":
                i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def _libsql_auth_token(url: str) -> str:
    """Auth token: TURSO_AUTH_TOKEN env wins; else ?authToken= in the URL."""
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if token:
        return token
    qs = parse_qs(urlparse(url).query)
    vals = qs.get("authToken") or qs.get("auth_token") or []
    return vals[0] if vals else ""


def _libsql_sync_url(url: str) -> str:
    """The URL the libsql client dials (query string stripped)."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return url.split("?")[0]
    return url.split("?")[0]


def _connect_libsql(url: str) -> LibSQLConnection:
    try:
        import libsql_experimental as libsql
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL uses libsql:// but the libsql client is not "
            "installed. Run: .venv/bin/pip install -r requirements.txt "
            "(libsql-experimental). See backend/docs/turso_setup.md."
        ) from exc
    replica = os.environ.get("LIBSQL_LOCAL_PATH", "").strip()
    replica_path = Path(replica) if replica else DEFAULT_REPLICA
    replica_path.parent.mkdir(parents=True, exist_ok=True)
    raw = libsql.connect(
        str(replica_path),
        sync_url=_libsql_sync_url(url),
        auth_token=_libsql_auth_token(url),
    )
    return LibSQLConnection(raw)


def _connect_sqlite(url: str) -> sqlite3.Connection:
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    elif url.startswith("sqlite://"):
        path = url[len("sqlite://"):]
    else:
        raise RuntimeError(
            f"Unsupported DATABASE_URL scheme: {url!r} (use sqlite:/// or libsql://)"
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # FastAPI runs sync dependencies/endpoints in a thread pool, so the
    # connection may be used from a different thread than the one that
    # created it. Each request gets its own connection; nothing is shared.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect(database_url: str | None = None):
    """Open a database connection for DATABASE_URL (or the env default).

    Returns a sqlite3.Connection for sqlite:// URLs and a
    LibSQLConnection (same call shape) for libsql:// / http(s):// URLs.
    """
    url = database_url or resolve_database_url()
    if backend_kind(url) == "libsql":
        return _connect_libsql(url)
    return _connect_sqlite(url)


def init_db(database_url: str | None = None):
    conn = connect(database_url)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn

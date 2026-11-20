"""LabPilot AI backend — FastAPI entry (Wave 1).

Run from backend/:  .venv/bin/uvicorn app.main:app --reload --port 8000
Seeds the three golden demo datasets on first start when the library is empty.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import VERSION, WAVE, store
from .db import backend_kind, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = init_db()
    try:
        seeded = store.seed_golden(conn)
        app.state.seeded = [s["name"] for s in seeded]
    finally:
        conn.close()
    yield


app = FastAPI(title="LabPilot AI", version=VERSION, lifespan=lifespan)

FRONTEND_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in FRONTEND_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers import analyses, archive, audit, charts, compare, datasets, report, stats  # noqa: E402

app.include_router(datasets.router)
app.include_router(analyses.router)
app.include_router(archive.router)
app.include_router(audit.router)
app.include_router(stats.router)
app.include_router(charts.router)
app.include_router(report.router)
app.include_router(compare.router)
app.state.seeded = []


@app.get("/health")
def health():
    from .db import connect

    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    finally:
        conn.close()
    return {"status": "ok", "version": VERSION, "wave": WAVE, "db": backend_kind(), "datasets": n}


# ---- 可选：同源托管前端 ----
# 设了 FRONTEND_DIR（或用默认 backend/static）就挂载前端构建产物，
# 一个进程同时服务页面和 /api，部署只需一个服务、无跨域。
_FRONTEND_DIR = os.environ.get(
    "FRONTEND_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
)
if os.path.isdir(_FRONTEND_DIR):
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    # 必须最后挂载：否则 "/" 会把 /api 路由吃掉
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


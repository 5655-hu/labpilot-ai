"""LabPilot AI backend — FastAPI entry (Wave 1).

Run from backend/: .venv/bin/uvicorn app.main:app --reload --port 8000
Seeds the three golden demo datasets on first start when the library is empty.

Hardening (Wave 1):
  * RateLimitMiddleware — 写操作按客户端 IP 限流，GET / /health 不计数
  * 403 handlers — 示例数据集保护 / 演示只读模式
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import VERSION, WAVE, store
from .db import backend_kind, init_db
from .ratelimit import RateLimitMiddleware


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

# --- 中间件顺序 ---------------------------------------------------------
# Starlette 的 add_middleware 是 insert(0)，后 add 的在外层。
# 这里先 add RateLimit、后 add CORS ⇒ CORS 在外层、RateLimit 在内层：
#   1) 限流器短路返回的 429 仍会经过 CORS，带上跨域头，前端能读到状态码；
#   2) OPTIONS 预检被外层 CORS 直接应答，不进限流器、不消耗配额。
# 反过来（RateLimit 在外层）会让 429 缺 CORS 头，浏览器只报跨域错误。
app.add_middleware(RateLimitMiddleware)

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


# --- 领域异常 → HTTP 403 ------------------------------------------------
# ExceptionMiddleware 在所有 user middleware 内层，因此这两个 handler 产出的
# 响应同样会向外穿过 RateLimit / CORS。响应体沿用 HTTPException 的 {"detail": ...}
# 形状，前端现有的错误处理不需要改。
@app.exception_handler(store.GoldenDatasetProtected)
async def _golden_protected_handler(request: Request, exc: store.GoldenDatasetProtected):
    return JSONResponse(
        status_code=403,
        content={"detail": str(exc) or "示例数据集受保护，不可删除"},
    )


@app.exception_handler(store.ReadOnlyMode)
async def _read_only_handler(request: Request, exc: store.ReadOnlyMode):
    return JSONResponse(
        status_code=403,
        content={"detail": str(exc) or "演示模式为只读，写操作已禁用"},
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


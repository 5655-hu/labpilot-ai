# 全栈镜像：前端构建产物 + FastAPI 后端，单进程同源服务。
# 构建： docker build -t labpilot-ai .
# 运行： docker run -p 8000:8000 labpilot-ai
# 数据持久化： docker run -p 8000:8000 -v labpilot-data:/app/data labpilot-ai

# ---------- 阶段 1：构建前端 ----------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build

# 依赖层单独缓存：改代码不会重装依赖
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# 同源部署：前端请求直接打到 /api，不写死后端域名
ENV VITE_API_SAME_ORIGIN=1
RUN npm run build

# ---------- 阶段 2：运行 ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 国内构建可加：--build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY backend/requirements.txt ./
RUN pip install --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY backend/ ./
COPY --from=frontend /build/dist ./static

# SQLite 与上传目录
RUN mkdir -p /app/data/uploads

ENV FRONTEND_DIR=/app/static \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

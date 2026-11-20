# LabPilot AI 后端镜像
#
# 构建（默认 PyPI）：
#   docker build -t labpilot-ai-backend:0.6.0 ./backend
# 构建（国内加速）：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#                -t labpilot-ai-backend:0.6.0 ./backend
# 运行：
#   docker run --rm -p 8000:8000 labpilot-ai-backend:0.6.0
# 验证：
#   curl http://127.0.0.1:8000/health
#
# 说明：
# - 基础镜像锁 python:3.12-slim（pandas 2.1.4 不支持 3.13）
# - 依赖层单独 COPY，改代码不会触发重新装包
# - 以非 root 用户运行
# - 数据目录 /app/data 可写；容器重启后 SQLite 重置，但启动会自动 seed 三份黄金数据
# - 要持久化：挂卷 `-v labpilot-data:/app/data`，或设 DATABASE_URL 指向 Turso

FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖先装，利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

# 再拷代码
COPY . .

RUN useradd --create-home --uid 1001 labpilot \
 && mkdir -p /app/data/uploads \
 && chown -R labpilot:labpilot /app

USER labpilot

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3); sys.exit(0)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# Turso 持久库切换说明（Wave 4）

LabPilot AI 的数据库层通过 `DATABASE_URL` 切换：本地开发用 SQLite 文件，
生产用 Turso 云端 SQLite（libSQL）。两种后端共用同一套 SQL（`schema.sql`
只用标准 SQLite 语法）和同一套读写接口（`app/db.py` 的适配层），切换
不需要改代码、不需要迁移表结构。

> 安全红线：Turso token 是密钥。只放在你自己机器 / 服务器的环境变量里，
> 绝不要发给任何人、绝不要写进代码、文档、聊天记录或 git 仓库。本说明
> 和本项目代码里没有任何真实 token。

## 1. 免费建一个 Turso 库

1. 打开 Turso 官网（turso.tech），用 GitHub 账号注册登录。
2. 在控制台创建一个数据库（Create Database），名字例如 `labpilot-ai`，
   地区选离你最近的（例如 `sin` 新加坡）。
3. 在数据库详情页找到连接信息：
   - 数据库 URL：形如 `libsql://labpilot-ai-<你的账号>.turso.io`
   - 创建一个 token：控制台里 Databases → 你的库 → Create Token
     （或用 Turso CLI：`turso db tokens create <库名>`）。
4. 记下这两样东西，只保存在你自己的环境变量里。

免费层（以 Turso 官网当前说明为准）：免费额度包含若干数据库与一定
的存储 / 读取额度，本项目 3 份演示数据 + 分析记录远低于免费额度。

## 2. 切换后端

```bash
# 本地开发（默认，不用做任何事）
unset DATABASE_URL            # 或 DATABASE_URL=sqlite:///backend/data/labpilot.db

# 切换到 Turso（在你自己的 shell / 服务器上设置，不要写进仓库）
export DATABASE_URL="libsql://labpilot-ai-<你的账号>.turso.io"
export TURSO_AUTH_TOKEN="<你在 Turso 控制台创建的 token>"
# 可选：本地同步副本文件位置（默认 backend/data/libsql-replica.db，
# 它只是同步缓存，Turso 才是数据的源头）
# export LIBSQL_LOCAL_PATH="/path/to/labpilot-replica.db"
```

依赖：后端已包含 `libsql-experimental`（见 `requirements.txt`），
装好依赖即可：

```bash
cd backend && .venv/bin/pip install -r requirements.txt
```

也可以用 URL 参数传 token（`libsql://...?authToken=<token>`），但不推荐：
token 会进 shell 历史与日志，环境变量是更安全的做法。

## 3. 切换后验证

```bash
# 1) 启动后端
cd backend && .venv/bin/uvicorn app.main:app --port 8000

# 2) 健康检查：db 字段应为 libsql
curl -s http://localhost:8000/health
# {"status":"ok","version":"0.5.0","db":"libsql","datasets":3}

# 3) 数据集列表：首次启动自动建表并写入 3 份黄金演示数据
curl -s http://localhost:8000/api/datasets | head -c 400

# 4) 写一条再读回：跑一次审计，确认分析记录落到 Turso
curl -s -X POST http://localhost:8000/api/datasets/1/audit \
  -H 'Content-Type: application/json' -d '{}' | head -c 300
curl -s http://localhost:8000/api/analyses | head -c 300
```

验证通过的标准：`/health` 的 `db` 为 `libsql`，数据集为 3 条，
审计能写入并在 `/api/analyses` 里查到；重启后端后数据仍在
（Turso 持久化，不丢）。

切回本地 SQLite：取消 `DATABASE_URL`（或设为 `sqlite:///...`）并重启，
本地 `backend/data/labpilot.db` 的数据不受影响——两边是互相独立的库，
切换不会互相覆盖。

## 4. 本地开发时模拟 Turso（不用注册账号）

本项目 Wave 4 已用本地 sqld（Turso 的开源服务器，协议与 Turso 云端
一致）实测过 libSQL 路径：

```bash
# 下载 sqld（GitHub tursodatabase/libsql releases，选 libsql-server
# 最新版的 x86_64-unknown-linux-gnu 包），解压后：
sqld --http-listen-addr 127.0.0.1:8080 -d /tmp/sqld-data
# 后端用：
DATABASE_URL="http://127.0.0.1:8080" .venv/bin/uvicorn app.main:app --port 8000
# 健康检查应返回 "db": "libsql"
```

本地 sqld 不需要 token（`TURSO_AUTH_TOKEN` 留空即可）。测试
`tests/test_archive.py::test_db_adapter_libsql_path` 就是对这条路
径的自动化验证：无本地 sqld 时该测试自动 skip 并注明原因。

## 5. 常见问题

- `RuntimeError: libsql client is not installed`：没装依赖，
  跑 `.venv/bin/pip install -r requirements.txt`。
- `Unsupported DATABASE_URL scheme`：URL 拼错了，检查是否以
  `sqlite:///` 或 `libsql://` 开头。
- 连接 Turso 报 401：token 不对或过期，去 Turso 控制台重新创建一个
  token，再更新 `TURSO_AUTH_TOKEN`。
- 连不上 Turso：先确认本机能访问外网与 `*.turso.io`；公司 / 校园网
  有时代理会挡住，去掉代理或换网络再试。
- 本地 SQLite 里的旧数据不会自动同步到 Turso：两边是独立的库。
  演示数据会在 Turso 库首次启动时自动重新写入；你自己上传的数据
  如需迁移，重新上传一次即可（本项目数据量小，不做自动迁移工具）。

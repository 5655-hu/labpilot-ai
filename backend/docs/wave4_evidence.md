# Wave 4 证据包 — 复现档案 + Turso 持久库 + compare 重跑

验证时间：2026-11-20 02:26–02:40 CST（UTC 2026-11-19 18:26–18:40）。
后端 v0.5.0（`app/__init__.py` VERSION = "0.5.0"），0 token 调用（全程确定性计算，未调用任何模型）。

## 1. 做了什么

- **复现档案（新模块，按需组装，无新表）**：`backend/app/archive.py` +
  `backend/app/routers/archive.py`（已在 `main.py` 注册）。
  档案字段：数据集 SHA-256、Python 与依赖真实版本（`importlib.metadata` 实读）、
  清洗规则（画像/权重/算法/阈值/哨兵值/永不删数据的政策，取自 `audit.py` 的真实实现）、
  原分析完整 `params_json`、引擎版本、代码版本 v0.5.0、随机种子（本项目确定性计算，
  注明“本分析无随机性”）、结果快照。
  接口：`GET /api/analyses/{id}/archive`、`GET /api/datasets/{id}/archives`、
  `GET /api/analyses/{id}/archive/export`（`application/json` 附件下载）。
  档案按需从分析记录现场组装，与分析记录永远一致；不另建档案表，因此 SQLite 与
  Turso 共用同一套逻辑、零迁移。
- **Turso 持久库**：`backend/app/db.py` 重写为小适配层。`sqlite://` 走原 sqlite3
  连接（行为不变）；`libsql://` / `http(s)://` 走 `libsql-experimental` 客户端。
  适配层只做接口翻译（tuple 参数、plain tuple 行包成 sqlite3.Row 行为、
  `executescript` 逐句执行、`lastrowid` 透传），SQL 仍留在原模块，未重写任何查询。
  Token 只从环境变量 `TURSO_AUTH_TOKEN`（或 URL 的 `authToken` 参数）读取，
  代码与文档中无任何真实 token。`requirements.txt` 增加 `libsql-experimental==0.0.55`。
  `/health` 的 `db` 字段改为按实际后端返回（`sqlite` / `libsql`）。
  操作说明：`backend/docs/turso_setup.md`（免费建库、切换、验证、本地 sqld 模拟、FAQ）。
- **第三波遗留修复**：compare 重跑（`routers/analyses.py` 增加 compare 分支，
  用原参数 `group_col/value_col/groups/override_test` 重跑并比对）；
  侧边栏版本改为读后端 `/health` 的 `version` 动态显示（加载失败回落写死文案
  "Wave 4 · v0.5.0"）；`Archive.tsx` 与 `RerunButton.tsx` 的“compare 会 400”
  旧文案已更新；`scripts/screenshot_wave3.py` 里断言 compare 400 的旧步骤
  同步改为断言重跑一致（否则该脚本重跑即失败）。

## 2. curl 实调（线上服务 localhost:8000，SQLite）

```
$ curl -s http://localhost:8000/health
{"status":"ok","version":"0.5.0","db":"sqlite","datasets":3}

$ curl -s -X POST http://localhost:8000/api/datasets/2/audit -H 'Content-Type: application/json' -d '{}'
{"analysis_id":41,...,"score":{"total":97.95,...}}        # 脏数据审计，与 Wave 1 黄金值一致

$ curl -s http://localhost:8000/api/analyses/35/archive | python3 -c ...
type: audit
hash: 26982eedbce416951970327dd5a866ef1793863ddb337d1f0250033f2251c02c
python: 3.12.3
deps: {'pandas': '2.1.4+dfsg', 'numpy': '1.26.4', 'scipy': '1.11.4', 'scikit-learn': '1.9.1', 'fastapi': '0.165.0'}
code: 0.5.0 engine: 0.2.0
params: {'algorithms': ['iqr'], 'iqr_k': 1.5, 'z_threshold': 3.0, 'profile': 'measurement',
         'weights': {'missing': 30.0, 'duplicate': 20.0, 'type_error': 25.0, 'definite_error': 25.0}, ...}
seed: {'seed': None, 'note': '本分析无随机性：审计、统计、分组比较、报告与线性回归均为确定性计算，...'}
cleaning profile: measurement

$ curl -s http://localhost:8000/api/datasets/3/preview | python3 -c ...
preview file_hash: 26982eedbce416951970327dd5a866ef1793863ddb337d1f0250033f2251c02c
# ↑ 档案 SHA-256 与上传记录完全一致

$ curl -s -D /tmp/export-headers.txt http://localhost:8000/api/analyses/35/archive/export -o /tmp/rerun-35.json
content-type: application/json
content-disposition: attachment; filename="labpilot-rerun-analysis-35.json"
format: labpilot-rerun-package
hash: 26982eedbce416951970327dd5a866ef1793863ddb337d1f0250033f2251c02c
params keys: ['algorithms', 'allowed_missing_columns', 'iqr_k', 'per_column_algorithms', 'profile', 'range_rules', 'weights', 'z_threshold']
code: 0.5.0
endpoint: POST /api/analyses/35/rerun

$ curl -s -X POST http://localhost:8000/api/analyses/40/rerun
{"consistent": true, "rerun_id": 42, "differences": []}   # compare 重跑，不再 400

$ curl -s http://localhost:8000/api/datasets/3/archives | python3 -c ...
total: 36
```

## 3. pytest（全量）

```
$ cd backend && .venv/bin/python -m pytest tests/ -q
89 passed, 1 warning in 4.22s
```

- 前三波原有 79 个测试全部通过（无一修改、无一跳过）。
- 新增 `tests/test_archive.py` 10 个测试，全部通过：
  - 档案字段完整（SHA-256 与数据集一致、Python/依赖版本非空、参数与原分析一致、
    代码版本 0.5.0、随机种子注明无随机性、结果快照与原结果一致）；
  - 重跑包导出（`application/json` 附件、JSON 可解析、哈希/参数/代码版本齐全、
    无原始行、无 token/密钥字段；导出后按包内 endpoint 重跑，结果与包内
    `expected_result` 逐项一致）；
  - 档案列表接口（数据集 3 的档案含新建的审计与比较记录，404 正常）；
  - compare 重跑一致性（p 值与 Cohen's d 与原结果相等，`consistent: true`）；
  - Turso 适配层：SQLite 路径（建表/种子数据/读写/Row 行为）全过；
    libSQL 路径对真实本地 sqld 实测通过（见第 4 节）；
    无客户端时明确报错（不静默回落 SQLite）。

## 4. Turso 验证情况（实测到哪一步、缺口是什么）

**已实测（真实服务，非模拟）：**

1. 客户端安装：`libsql-experimental==0.0.55` 可在 `.venv` 正常安装
   （`pip install libsql-experimental`，5.3 MB wheel，2026-11-20 实测）。
2. 本地 sqld：从 GitHub tursodatabase/libsql releases 下载
   `libsql-server 0.24.32`（`libsql-server-x86_64-unknown-linux-gnu.tar.xz`），
   `sqld --http-listen-addr 127.0.0.1:8080 -d /tmp/sqld-data` 启动，
   `/health` 返回 200。
3. 适配层直连实测（`test_db_adapter_libsql_path` 通过）：建表（`executescript`
   跑 `schema.sql`）、写 3 条黄金数据集、读回（哈希 64 位、名称一致）、
   第二个连接读到同一批数据（服务端持久化），测完清表。
4. 整站切换实测：另起后端 `DATABASE_URL="http://127.0.0.1:8080" ... uvicorn
   --port 8001`，结果：
   - `GET /health` → `{"status":"ok","version":"0.5.0","db":"libsql","datasets":3}`
     （启动时自动建表并写入 3 份黄金演示数据，与 SQLite 行为一致）；
   - `POST /api/datasets/2/audit` → 新分析 #1，脏数据评分 97.95，与 SQLite
     侧的黄金值一致；
   - 8001 验证服务随后已停用，8000（SQLite）继续运行。
5. 探明的客户端行为（已写进 `app/db.py` 注释）：参数必须是 tuple（list 会报
   `TypeError`）；行是 plain tuple、无 keys，列名取自 `cursor.description`；
   `Connection.execute()` 返回的是新 Cursor 而非 self。

**验证缺口（未实测，如实记录）：**

- **未连真实 Turso 云端**：创建 Turso 账号与 token 需要用户自己注册，
  本波未创建任何 Turso 账号、未使用任何真实 token。云端 `libsql://` 路径
  与本地 sqld 走同一协议（Hrana over HTTP）与同一客户端，但云端握手、
  认证（`TURSO_AUTH_TOKEN`）、跨公网延迟三项只在文档里写了步骤，未实测。
  用户按 `docs/turso_setup.md` 第 1–3 节操作后，用 `/health` 的 `db:
  "libsql"` 与数据集列表验证即可。
- **无自动迁移**：本地 SQLite 里的用户上传数据不会自动同步到 Turso，
  两边是独立的库（文档第 5 节已写明，演示数据会在 Turso 侧自动重建）。
- 本地 sqld 服务器（`/tmp/sqld-bin/.../sqld`，数据在 `/tmp/sqld-data`）
  仍在运行（PID 9507，127.0.0.1:8080），供复验；它是 /tmp 下的临时服务，
  重启后需重新启动，`tests/test_archive.py::test_db_adapter_libsql_path`
  在其不可达时会自动 skip 并注明原因。
- libSQL 路径的测试会在 `backend/data/` 下生成同步副本
  `libsql-replica.db`（客户端的本地副本缓存）；验证后已删除，测试重跑时会
  再次生成——这是客户端的正常行为，不是脏数据。

## 5. 前端 build 与截图

```
$ cd frontend && npm run build
✓ built in 3.67s（dist/index.html + assets；仅有 plotly chunk > 500 kB 的既有警告）
```

Playwright 1.65.2 + Chrome Headless Shell（`/tmp/shot-venv`），脚本
`backend/scripts/screenshot_wave4.py`：

- `backend/docs/screenshots/wave4-01-archive-list.png` — 档案列表页真实渲染
  （44 条分析记录；侧边栏显示 "Wave 4 · v0.5.0"，断言通过）。
- `backend/docs/screenshots/wave4-02-archive-detail.png` — 档案详情页真实渲染
  （#44 分组比较档案：SHA-256 全文、Python 3.12.3、依赖版本表、清洗规则、
  参数 JSON、随机种子说明、结果快照、下载重跑包按钮；已目视检查，非空白）。
- 脚本内另断言：档案页点 compare 重跑返回“结果一致”（不再 400）——通过。

## 6. 未解决问题清单

1. **真实 Turso 云端未联调**（见第 4 节缺口）：需用户注册 Turso 账号后按
   `docs/turso_setup.md` 操作并验证；本波不代劳、不收 token。
2. **Dashboard “科研项目数量”仍固定为 1**（Wave 2 遗留显示问题，本波未动，
   与档案无关）。
3. **侧边栏版本文案为 “Wave 4 · v{version}”**：波次数字仍是写死的 "Wave 4"，
   只有版本号是动态的；下次升波需改这一处常量（Layout.tsx）。
4. **档案列表无分页**：分析记录增多后列表会很长（截图时已有 44 条），
   未做分页/筛选；建议第五波或后续优化时再加。
5. **重跑包不含原始数据行**（有意为之，隐私边界）：拿到包重跑的前提是
   本项目后端里已有同一数据集（按 `file_hash` 核对）；包内 `rerun.howto`
   已写明这一点。
6. **libsql 客户端握手日志较吵**：每次建连时 `libsql::replication::remote_client`
   会向 stderr 打一条 INFO 日志，不影响功能，生产部署时可忽略。

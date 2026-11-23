# LabPilot AI — 科研数据智能审计与复现助手

> **在线体验（真后端）**：http://8.163.38.73:8000 —— 上传自己的 CSV、跑审计 / 统计 / 图表 / 报告，全部实时计算，不是演示快照。
>
> **作品主页（Qoder Sites，公开）**：https://labpilot-ai-7rqxdfoi89b.qoder.zone —— 免登录可看完整演示数据快照，页内可一键跳到真后端版本。

Qoder 高校创造力大赛 StudyHack 赛道，个人参赛，目标冲击一等奖。
硬截止：2026-11-30 18:00。完整方案见 `../your_files/labpilot-ai-xiang-mu-fang-an/labpilot-ai-xiang-mu-fang-an.pdf`（v2，18 页）。

> 让每一份实验数据都可检查、可解释、可复现。

**当前状态（Wave 5，v0.6.0，2026-11-21）：五波开发全部完成并通过实际运行验证。
公网部署已完成——Qoder Sites 公开站点 + 阿里云轻量真后端双通道，均已匿名实测通过；
比赛提交材料见 `backend/docs/tianchi_post.md`。**

## 原则（不可动摇）

- 所有统计数值来自 Pandas / NumPy / SciPy / Scikit-learn 真实计算，AI 不生成、不改写、不约算数字。
- 数据质量评分公式公开，每笔扣分带证据；异常与错误分档，永不自动删除数据。
- 报告数字由后端结构化 JSON 填槽，AI 只写解释文字。
- 原始行数据默认不发送给任何第三方 AI；AI 适配层只接受统计摘要。
- 没有实际运行验证的功能，不标记为完成。

## 功能（五波全部落地）

- **数据集管理**：上传 CSV / Excel（≤10MB、≤10 万行），预览，SHA-256，删除。
- **数据质量审计**：缺失、重复、类型错误、范围与单位风险；公开评分公式与逐笔扣分证据；
  IQR / Z-score 双算法可选，异常只标“待确认”；测量 / 问卷 / 时序三套规则画像。
- **统计分析**：均值、中位数、标准差、方差、最值、Pearson 相关矩阵、基础线性回归；
  常量列、小样本、非数值列均有明确处理。
- **数据可视化**：直方图、箱线图、散点图、折线图、相关性热力图，Plotly 交互图表；
  回归图展示方程、R² 与样本量；相关性处均有“相关性不代表因果关系”提示。
- **分组比较**：对照组 vs 实验组，先做正态性与方差齐性检查再自动选检验，必报效应量。
- **AI 科研报告**：数字填槽组装，AI 只写文字；无 AI 时规则版报告照常导出 Markdown；
  每条结论带证据链编号，可溯源到统计指标、参数与原始列。
- **复现档案**：每次分析自动封存 SHA-256、环境与依赖版本、清洗规则、全部参数、代码版本、
  随机种子说明；支持一键重跑（原参数逐项比对）与重跑包导出；列表分页（每页 20 条）。

## 目录结构

```
labpilot-ai/
  frontend/   Vite + React + TypeScript + Tailwind CSS + Plotly.js（7 个页面）
  backend/    Python + FastAPI + Pandas/NumPy/SciPy
    app/          main.py（入口）、db.py、store.py、ai_adapter.py、audit.py、stats.py、
                  charts.py、report.py、archive.py、compare.py、routers/
    data/         labpilot.db（本地 SQLite）、golden/（3 份黄金演示数据 + 清单）
    schema.sql    SQLite 兼容建表语句（生产换 Turso 不用改 SQL）
    scripts/      generate_golden.py（黄金数据生成器，种子固定）、screenshot_wave*.py
    tests/        pytest：API 测试 + 黄金数据期望值断言（104 passed, 1 skipped；2026-11-23 Wave 6 hardening 实测。skip = tests/test_archive.py:263，本地无 sqld，远程 libSQL 路径未验证）
    docs/         wave1~5_evidence.md、turso_setup.md、deploy_checklist.md、
                  tianchi_post.md、competition_checklist.md
  README.md
```

## 本地运行

环境要求：**Python ≥ 3.11**（`fastapi 0.165` 的硬约束；3.10 会在安装阶段直接失败）、Node ≥ 20。

```bash
# 后端（开发模式）
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
# 健康检查：curl http://localhost:8000/health

# 前端（另开一个终端）
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### Windows（PowerShell）

```powershell
# 后端
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\uvicorn.exe app.main:app --port 8000

# 前端（另开一个窗口）
cd frontend
npm install
npm run dev
```

Windows 下 `libsql-experimental` 没有预编译包（源码构建需要 Rust + MSVC `link.exe`），
`requirements.txt` 已用 `sys_platform != "win32"` 跳过它；本地 `sqlite://` 后端不会 import 该包。

前端 API 地址由 `frontend/.env` 中的 `VITE_API_URL` 配置，默认 `http://localhost:8000`。

### 生产模式（本波已验证）

```bash
# 后端：去掉 --reload，用环境变量配数据库与 CORS
cd backend
DATABASE_URL=sqlite:////path/to/labpilot-prod.db \
  CORS_ORIGINS=http://localhost:4173,http://127.0.0.1:4173 \
  .venv/bin/uvicorn app.main:app --port 8002

# 前端：构建时把 VITE_API_URL 写死为后端公网地址，再静态托管 dist/
cd frontend
VITE_API_URL=https://<后端公网地址> npm run build
python3 -m http.server 4173 --directory dist
```

## 数据库与持久化

- 本地开发：`backend/data/labpilot.db`（SQLite 文件，随项目走，不放临时路径）。
- 生产：`DATABASE_URL` 环境变量。`sqlite:///绝对路径` 用指定文件；
  `libsql://...` 走 Turso 云端 SQLite（`libsql-experimental` 客户端已接入，
  本地 sqld 实测通过；真实云端联调需用户注册账号，见 `backend/docs/turso_setup.md`）。
- 启动时若数据集表为空，自动 seeding 3 份黄金演示数据（干净 / 脏 / 相关性回归）。

## 黄金演示数据

`backend/data/golden/`：`clean.csv`（200 行，零缺失零重复）、`dirty.csv`（126 行，缺失 16、重复 6、类型错误 3 处）、`corr.csv`（150 行，dose-response Pearson 0.98506）。期望值全部由生成脚本从写好的 CSV 文件回读算出，记在 `golden_manifest.json`，测试直接拿期望值断言。

关键验证数字：脏数据审计质量分 **97.95**；corr 回归 `response = 2.5241·dose + 1.2063`，
**R² = 0.970344，n = 150**。

## 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -q    # Linux/macOS：104 passed, 1 skipped（Wave 6 hardening 新增 12 项；skip: tests/test_archive.py:263，本地无 sqld）
cd backend && .venv\Scripts\python.exe -m pytest tests/ -q    # Windows
cd frontend && npm run build                          # 通过
```

测试隔离：数据库走临时文件，上传文件写入会话临时目录（`tests/conftest.py`），
跑完不在 `backend/data/uploads/` 留任何残留。
`GeminiProvider.available()` 依赖仓库外的私有连接器 `custom.gemini`，测试用
`gemini_helper` fixture 造一个占位文件并 mock `subprocess`，因此不联网、不调真实模型。

### 接口冒烟（对运行中的后端）

```bash
cd backend && .venv/Scripts/python.exe scripts/smoke_api.py    # Windows
cd backend && .venv/bin/python scripts/smoke_api.py            # Linux/macOS
```

覆盖 36 项检查（数据集、审计、统计、六类图表、分组比较、报告、重跑、档案导出、
上传/删除、边界 404/400/422），退出码 0 表示全部通过。可用 `LABPILOT_API` 指向其他地址。

证据包：`backend/docs/wave1_evidence.md` ~ `backend/docs/wave5_evidence.md`
（API 实调记录、pytest 与 build 结果、真实截图、未解决问题清单）。

## 部署与发帖状态

- 前端：Qoder Sites（待用户用自己的 Qoder 账号发布并设为公开）。
- 后端：公网 Python 服务（待用户选定服务商部署；启动命令与环境变量见 `backend/docs/deploy_checklist.md`）。
- 天池发帖：草稿见 `backend/docs/tianchi_post.md`，发帖需用户天池账号，截止 2026-11-30 18:00。
- 合规提醒：本项目代码在本地搭建、上线走 Qoder；“使用 Qoder 完成的作品”口径如实写在
  `backend/docs/deploy_checklist.md` 第 4 节，请用户自行判断。

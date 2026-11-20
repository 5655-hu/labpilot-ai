# LabPilot AI — 科研数据智能审计与复现助手

Qoder 高校创造力大赛 StudyHack 赛道，个人参赛，目标冲击一等奖。
硬截止：2026-11-30 18:00。完整方案见 `../your_files/labpilot-ai-xiang-mu-fang-an/labpilot-ai-xiang-mu-fang-an.pdf`（v2，18 页）。

> 让每一份实验数据都可检查、可解释、可复现。

**当前状态（Wave 5，v0.6.0，2026-11-20）：五波开发全部完成并通过实际运行验证。
本地生产构建联调通过；公网部署（Qoder Sites + 后端公网服务）与天池发帖待用户操作，
步骤见 `backend/docs/deploy_checklist.md`，清单见 `backend/docs/competition_checklist.md`。**

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
    tests/        pytest：API 测试 + 黄金数据期望值断言（93 passed）
    docs/         wave1~5_evidence.md、turso_setup.md、deploy_checklist.md、
                  tianchi_post.md、competition_checklist.md
  README.md
```

## 本地运行

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
cd backend && .venv/bin/python -m pytest tests/ -q   # 93 passed
cd frontend && npm run build                          # 通过
```

证据包：`backend/docs/wave1_evidence.md` ~ `backend/docs/wave5_evidence.md`
（API 实调记录、pytest 与 build 结果、真实截图、未解决问题清单）。

## 部署与发帖状态

- 前端：Qoder Sites（待用户用自己的 Qoder 账号发布并设为公开）。
- 后端：公网 Python 服务（待用户选定服务商部署；启动命令与环境变量见 `backend/docs/deploy_checklist.md`）。
- 天池发帖：草稿见 `backend/docs/tianchi_post.md`，发帖需用户天池账号，截止 2026-11-30 18:00。
- 合规提醒：本项目代码在本地搭建、上线走 Qoder；“使用 Qoder 完成的作品”口径如实写在
  `backend/docs/deploy_checklist.md` 第 4 节，请用户自行判断。

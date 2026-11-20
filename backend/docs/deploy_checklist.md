# LabPilot AI 部署检查清单（Wave 5）

> 状态（2026-11-20 02:44 CST）：**本地生产构建已验证通过；公网部署待用户操作**。
> 本文件不含任何账号、密码与 token；所有需要登录的步骤都由用户本人完成。

## 0. 部署状态总览

| 项 | 状态 | 说明 |
|---|---|---|
| 前端生产构建（`npm run build` → `dist/`） | ✅ 已验证 | 本波实测 5.28s 构建成功；静态服务 + 生产模式后端联调通过 |
| 后端生产模式启动（uvicorn，无 `--reload`） | ✅ 已验证 | 临时库实测：健康检查、审计、统计、规则版报告、档案全部通过 |
| 前端部署到 Qoder Sites | ⏳ 待用户操作 | 需用户 Qoder 账号登录（见第 2 节）；本机无 CLI、无登录态，无法代劳 |
| 后端部署到公网 Python 服务 | ⏳ 待用户操作 | 需选一家服务商并用用户账号部署（见第 3 节） |
| Turso 云端数据库联调 | ⏳ 待用户操作 | 需用户注册 Turso 账号后按 `turso_setup.md` 操作（Wave 4 已验证本地 sqld 路径） |
| 公开访问链接 | ⏳ 待部署后补 | 前后端上线后把链接写进 `competition_checklist.md` 与天池帖 |
| “使用 Qoder 完成的作品”合规 | ⚠️ 见第 4 节 | 本项目是在本机由 AI 代理搭建的，未在 Qoder 内开发；如实说明，见第 4 节 |

## 1. 部署前检查项（本地已全部通过）

- [x] 前端 `npm run build` 通过（`tsc -b && vite build`，仅有 plotly chunk > 500 kB 的既有警告）
- [x] 后端 pytest 全量通过：**93 passed**（Wave 4 的 89 个 + 本波分页 4 个）
- [x] 环境变量：后端只读 `DATABASE_URL`、`TURSO_AUTH_TOKEN`、`CORS_ORIGINS`，无一写进代码或文档
- [x] 数据库：本地 SQLite 正常；`DATABASE_URL` 切换 Turso 的路径已在 Wave 4 用本地 sqld 实测（`db: "libsql"`）
- [x] 演示数据：3 份黄金数据集随启动自动 seeding（clean / dirty / corr），无 AI、无密钥可完整演示
- [x] AI 降级：无 AI 密钥时审计、统计、图表与规则版报告照常运行（本波冒烟用 `include_ai: false` 验证）
- [x] 生产构建本地实测（见第 5 节）：`dist/` 静态服务 + 后端生产模式，curl 健康检查与审计调用通过

## 2. 前端部署到 Qoder Sites（用户操作步骤）

依据：Qoder Sites 官方文档（docs.qoder.cn/en/cli/sites）与 Qoder CN 登录文档
（docs.qoder.cn/en/cli/authentication），2026-11-20 核查。

前提：Qoder Sites 的发布走 Qoder CLI CN（`qodercn sites`），**使用本机 Qoder 登录态**；
写操作（发布、改公开策略）需在会话内由用户本人确认。免费版仅支持静态站点发布，
动态站点需专业版及以上——本项目前端是纯静态构建产物（`dist/`），免费版即可发布；
后端不在 Qoder Sites 里，见第 3 节。

1. 在你自己的电脑上安装 Qoder CLI CN（Linux/macOS）：
   ```bash
   curl -fsSL https://qoder.com.cn/install | bash
   qodercn --version
   ```
2. 登录你的 Qoder 账号（两种方式任选其一，不要把 token 发给任何人）：
   - 交互登录：运行 `qodercn`，在提示符输入 `/login`，按浏览器登录流程完成；
   - 或在 Qoder 官网“账号 → 服务集成”页生成 Personal Access Token，
     设置环境变量 `QODERCN_PERSONAL_ACCESS_TOKEN`。
3. 进项目目录，确认前端构建产物是最新的：
   ```bash
   cd labpilot-ai/frontend
   VITE_API_URL=https://<你的后端公网地址> npm run build
   ```
   注意：`VITE_API_URL` 必须在构建时写死为后端公网地址（例如 `https://labpilot-api.example.com`），
   构建后再改不生效；本地验证时用 `http://localhost:8002` 即可。
4. 在 Qoder CLI 会话里发布（推荐自然语言方式，让内置 Sites Skill 走流程）：
   - 运行 `qodercn`，说：“把 frontend/dist 发布为一个公开站点”；
   - 或用 `/sites` 面板：Publish → 选择已就绪的部署 → Sharing 改为 Public（公开需二次确认）。
5. 发布后验证：用手机流量（异地网络）打开站点链接，走一遍演示动线
   （首页 → 脏数据审计 → 统计 → 图表 → 报告 → 档案），确认无白屏、无跨域报错。
6. 把公开链接记下来，填进 `competition_checklist.md` 与天池帖。

## 3. 后端部署到公网 Python 服务（用户操作步骤）

Qoder Sites 只托管前端；后端（FastAPI）需另找支持 Python 的公网服务。
以下为通用步骤，具体以所选服务商的控制台为准（Render / Railway / Hugging Face Spaces /
阿里云函数计算等均可，选免费层即可；本项目不指定服务商、不代选账号）：

1. 把代码推到你自己的 Git 仓库（GitHub 账号 `5655-hu` 已有，仓库名自定，例如 `labpilot-ai`）。
2. 在服务商处新建一个 Python Web Service，指向该仓库的 `backend/` 目录：
   - 启动命令：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
     （不要加 `--reload`；`$PORT` 用服务商注入的端口变量）。
   - Python 版本：3.12；依赖：`pip install -r requirements.txt`。
3. 在服务商控制台设置环境变量（只填你自己的值，不要写进仓库）：
   - `DATABASE_URL`：生产建议填 Turso 的 `libsql://…`（见 `turso_setup.md`）；
     临时也可用默认 SQLite，但免费磁盘不持久，重启会丢用户上传的数据。
   - `TURSO_AUTH_TOKEN`：与 `DATABASE_URL` 配对使用。
   - `CORS_ORIGINS`：填前端 Qoder Sites 的公开域名，例如 `https://<你的站点>.qoder.site`。
4. 部署后验证：
   ```bash
   curl https://<你的后端公网地址>/health
   # 应返回 {"status":"ok","version":"0.6.0","wave":"Wave 5","db":"libsql","datasets":3}
   ```
5. 回到第 2 节第 3 步，用这个后端地址重新构建前端并重新发布。

## 4. 合规提醒： “必须为使用 Qoder 完成的作品”

比赛官方要求（天池赛题页，经 competehub 镜像核对，2026-11-20）：
参赛作品“必须为使用 Qoder 完成的作品”，且“使用 Qoder 开发一个完整的项目，
部署到 Qoder Sites 并开放公开访问”。

**如实情况**：LabPilot AI 的代码是在本机由 Muse（AI 代理）在 VS Code 外的环境中搭建的，
开发过程没有在 Qoder IDE / Qoder CLI 内进行。这一点无法事后改写，也不做任何掩饰。

建议用户这样处理（由用户本人决定，Muse 不代判断）：
- 在 Qoder 中打开本项目（Qoder IDE 或 `qodercn` 会话），用 Qoder 走一遍后续工作
  （发布、调试、迭代），让“使用 Qoder 开发与发布”的过程真实发生；
- 在天池帖中如实写清开发工具链：前期脚手架与核心模块由 AI 代理在本地完成，
  上线、发布与后续迭代在 Qoder 内完成；不声称“全程在 Qoder 内开发”。
- 是否符合评审口径，最终由主办方判定；不要为合规而编造开发过程。

## 5. 本地生产验证记录（2026-11-20 02:44 CST）

验证方式：前端 `VITE_API_URL=http://localhost:8002 npm run build`（5.28s），
`python3 -m http.server 4173`  serving `frontend/dist`；
后端 `DATABASE_URL=sqlite:////tmp/labpilot-prod.db CORS_ORIGINS=http://localhost:4173,http://127.0.0.1:4173 uvicorn app.main:app --port 8002`
（生产模式，无 `--reload`，临时库，验证后可删）。

```
$ curl -s http://localhost:8002/health
{"status":"ok","version":"0.6.0","wave":"Wave 5","db":"sqlite","datasets":3}

$ curl -s -X POST http://localhost:8002/api/datasets/2/audit -d '{}'
audit id 1, score 97.95, missing 16, dupes 6          # 与黄金值一致

$ curl -s -X POST http://localhost:8002/api/datasets/3/stats -d '{}'
stats id 2, corr dose-response 0.98506               # 与黄金值一致

$ curl -s -X POST http://localhost:8002/api/datasets/3/report -d '{"include_ai": false}'
report id 5, conclusions 3, 规则版（未调用 AI）

$ curl -s http://localhost:8002/api/analyses/1/archive
archive analysis 1, code 0.6.0, SHA-256 与数据集一致
```

Playwright 真实无头浏览器访问生产构建（:4173）截图：
`docs/screenshots/wave5-01-dashboard-prod.png`（Dashboard，侧边栏 Wave 5 · v0.6.0）、
`docs/screenshots/wave5-02-report-prod.png`（报告页，corr 相关系数 0.98506）、
`docs/screenshots/wave5-03-archive-pagination-prod.png`（档案列表分页，第 1/1 页）。

注意：`python3 -m http.server` 没有 SPA fallback，直接访问 `/report` 会 404；
生产部署时 Qoder Sites 会处理 SPA 路由，本地验证用侧边栏导航跳转（截图脚本已按此方式）。
验证用的临时库 `/tmp/labpilot-prod.db` 与两个验证服务（:8002、:4173）均为临时进程，
不影响开发服务（:8000、:5173）。

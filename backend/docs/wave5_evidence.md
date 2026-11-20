# Wave 5 证据包 — 生产构建与部署就绪 + 比赛材料

验证时间：2026-11-20 02:38–02:45 CST（UTC 2026-11-19 18:38–18:45）。
后端 v0.6.0（`app/__init__.py` VERSION = "0.6.0"，WAVE = "Wave 5"），0 token 调用
（全程确定性计算，未调用任何模型；冒烟报告用 `include_ai: false` 规则版）。

## 1. 做了什么

- **生产构建与部署就绪**：前端 `npm run build` 通过（`dist/` 可用）；后端生产启动方式
  整理进 `backend/docs/deploy_checklist.md`（uvicorn 无 `--reload`、环境变量说明、
  `DATABASE_URL` 切换说明复用 `turso_setup.md`）；部署前检查项全部逐项核对。
- **Qoder Sites 部署调查**：查官方文档（docs.qoder.cn/en/cli/sites、authentication）
  与比赛官方要求（天池赛题页，经 competehub 镜像核对）。结论：发布走 Qoder CLI CN
  （`qodercn sites`），依赖本机 Qoder 登录态；本机无 CLI、无登录态，无法代劳。
  部署状态明确标注“待用户操作”，步骤写进 `deploy_checklist.md` 第 2–3 节。
  另如实标注“使用 Qoder 完成的作品”合规缺口（第 4 节），不掩饰、不编造。
- **天池发帖材料**：`backend/docs/tianchi_post.md`（可直接发布的中文介绍帖草稿 +
  发布步骤清单）；`backend/docs/competition_checklist.md`（一页纸比赛材料清单：
  官方强制项逐项打勾/待办、截止 2026-11-30 18:00、负责人）。
- **小尾巴修复**：侧边栏波次文案不再写死——后端 `/health` 新增 `wave` 字段
  （`app/__init__.py` 的 `WAVE` 为唯一来源），前端读 `wave` 动态显示，
  失败回落 "Wave 5 · v0.6.0"；档案列表加分页（后端 `GET /api/analyses?limit=&offset=`，
  默认 20 条，`total` 恒为全量计数；前端 `Archive.tsx` 上一页/下一页 + 第 X/Y 页）。
- **版本与收尾**：后端升 0.6.0，前端侧边栏同步；根目录 `README.md` 重写
  （功能、生产启动、部署与发帖状态）。

## 2. pytest（全量）

```
$ cd backend && .venv/bin/python -m pytest tests/ -q
93 passed, 1 warning in 4.54s
```

- Wave 4 的 89 个测试全部通过；本波新增 `tests/test_pagination.py` 4 个全部通过
  （默认页 20 条、分页不重叠、越界空页、非法参数 422、`/health` 返回 wave/version）。
- 升版时两处写死版本号的旧测试（`test_archive.py` 的 `"0.5.0"`）随版本改为 `"0.6.0"`，
  其余测试未动。`total` 保持全量计数的设计使 `test_audit_persists_and_latest`
  的前后计数断言继续通过。

## 3. 前端 build

```
$ cd frontend && npm run build
✓ built in 4.59s（dist/index.html + assets；仅有 plotly chunk > 500 kB 的既有警告）

$ VITE_API_URL=http://localhost:8002 npm run build   # 生产验证用构建
✓ built in 5.28s
```

## 4. 生产构建本地实测（curl 冒烟，生产模式后端 :8002 + 静态 dist :4173）

后端：`DATABASE_URL=sqlite:////tmp/labpilot-prod.db CORS_ORIGINS=http://localhost:4173,http://127.0.0.1:4173 uvicorn app.main:app --port 8002`
（无 `--reload`，临时库）；前端：`python3 -m http.server 4173` serving `frontend/dist`。

```
$ curl -s http://localhost:8002/health
{"status":"ok","version":"0.6.0","wave":"Wave 5","db":"sqlite","datasets":3}

$ curl -s -X POST http://localhost:8002/api/datasets/2/audit -d '{}'
audit id 1, score 97.95, missing 16, dupes 6

$ curl -s -X POST http://localhost:8002/api/datasets/3/stats -d '{}'
stats id 2, corr dose-response 0.98506

$ curl -s -X POST http://localhost:8002/api/datasets/3/report -d '{"include_ai": false}'
report id 5, conclusions 3, 规则版（未调用 AI）

$ curl -s http://localhost:8002/api/analyses/1/archive
archive analysis 1, code 0.6.0, SHA-256 与数据集一致
```

开发服务（:8000）重启后同样验证：`/health` 返回 0.6.0 / Wave 5，
`GET /api/analyses?limit=2` 返回 2 条。

## 5. Playwright 截图（生产构建，真实无头浏览器）

脚本 `backend/scripts/screenshot_wave5.py`（`/tmp/shot-venv`），访问 :4173 的生产构建：

- `backend/docs/screenshots/wave5-01-dashboard-prod.png` — 生产 Dashboard
  （侧边栏 "Wave 5 · v0.6.0"，数据集计数真实）。
- `backend/docs/screenshots/wave5-02-report-prod.png` — 生产报告页
  （corr 数据集最新规则版报告，相关系数 0.98506 已断言在屏）。
- `backend/docs/screenshots/wave5-03-archive-pagination-prod.png` — 生产档案列表分页
  （共 5 条，第 1/1 页 · 每页 20 条；已目视检查，非空白）。

注：`python3 -m http.server` 无 SPA fallback，直接访问 `/report` 会 404；
截图脚本改走侧边栏导航跳转（生产部署时 Qoder Sites 会处理 SPA 路由）。

## 6. 部署状态（截至本波结束）

| 项 | 状态 |
|---|---|
| 前端生产构建 | ✅ 已验证（`dist/`，5.28s） |
| 后端生产模式 | ✅ 已验证（:8002 冒烟全过） |
| Qoder Sites 发布 | ⏳ 待用户操作（需用户 Qoder 账号登录；本机无 CLI、无登录态） |
| 后端公网部署 | ⏳ 待用户操作（需选服务商并用用户账号部署） |
| Turso 云端联调 | ⏳ 待用户操作（需用户注册账号；本地 sqld 路径 Wave 4 已验证） |
| 公开访问链接 | ⏳ 待部署后补 |
| 天池发帖 | ⏳ 待用户发（草稿 `backend/docs/tianchi_post.md` 已备好） |
| “使用 Qoder 完成”合规 | ⚠️ 见 `deploy_checklist.md` 第 4 节（本地搭建、Qoder 发布；如实说明） |

## 7. 未解决问题清单

1. **公网部署未完成**（本波最大缺口）：Qoder Sites 发布与后端公网部署都需要用户账号，
   本波只能做到“本地生产验证通过 + 步骤写清”，不能代劳。见 `deploy_checklist.md`。
2. **真实 Turso 云端未联调**（Wave 4 遗留）：需用户注册账号后按 `turso_setup.md` 操作验证。
3. **Dashboard“科研项目数量”仍固定为 1**（Wave 2 遗留显示问题，与本波无关，未动）。
4. **项目架构图、路演 PPT 未做**（方案第 14 节交付清单中的两项）：见
   `competition_checklist.md`；架构图可后续补，PPT 建议进决赛后再准备。
5. **P2 扩展未做**（多组 ANOVA、配对检验、差异报告导出）：按方案，不承诺工期。
6. **验证用临时服务与临时库**：:8002 后端、:4173 静态服务、`/tmp/labpilot-prod.db`
   均为本波验证用的临时进程/文件，验证后已停用；开发服务 :8000 / :5173 继续运行。

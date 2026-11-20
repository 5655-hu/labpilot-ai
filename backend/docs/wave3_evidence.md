# LabPilot AI 第三波证据包（报告 + 证据链 + 重跑 + 分组比较）

后端 v0.4.0。第三波 6 项全部完成。本波模型调用：Gemini 2 次真实调用（一次接线实测 900 token / 2.06 秒，一次报告生成 736 token；另有前端验证生成的一次 779 token），其余全部确定性计算。图表未动（第二波已验收），复现档案、Turso、部署不在本波。

## 1. 报告组装与导出

- `backend/app/report.py`（新建）：先跑审计 + 统计引擎，相关矩阵取自 stats，最强相关对做回归（排除 `id`/`*_id` 标识列——实测发现 corr 集最强相关本是 `sample_id×dose` r=0.999288 行号伪相关，已排除，改为 `dose×response` r=0.98506）。
- `POST /api/datasets/{id}/report` / `GET /api/datasets/{id}/report`；AI 解释走 `ai_adapter.py` 的 `GeminiProvider`（subprocess 调 `custom.gemini` helper，模型 `gemini-3.5-flash-lite`，超时 60 秒），只发统计摘要 JSON，原始行发送恒为 0；AI 不可用/超时自动降级规则版，`source` 字段标注。
- 报告数字由后端从 JSON 原值填槽渲染（`render_markdown`），AI 段落原样嵌入；`check_numbers` 扫描 AI 段落数字比对 JSON 数值集合，对不上的列入 `number_check.unmatched`（只提示，不拦截）。

### 实测记录（协调员亲手 curl，后端 :8000）

```
$ curl -X POST http://localhost:8000/api/datasets/3/report -d '{"include_ai": true}'
→ HTTP 200，analysis_id 13，source "ai"
  tokens: prompt 599 / candidates 137 / total 736
  评分 100.0；结论 3 条，全部带 evidence 且 analysis_ids 非空
  回归：response = 2.5241·dose + 1.2063，R² 0.970344，n=150
  number_check.unmatched: []
  （完整 JSON：backend/docs/report_corr_response.json）

$ curl -X POST http://localhost:8000/api/datasets/3/report -d '{"include_ai": false}'
→ HTTP 200，analysis_id 37，source "rule-based"
  ai_text 以“数据集「相关性与回归数据（黄金演示）」共 150 行、5 列。数据质量评分 100.0 分…”开头

Gemini 接线实测（开发直接调 helper，corr 黄金摘要）：
  returncode 0，elapsed 2.06s
  tokens: prompt 760 / candidates 140 / total 900
  回复 230 字、无阿拉伯数字，符合“只写定性段落”要求
```

- 前端报告页：全文展示 + 每条结论“证据”展开 + AI/规则版标识 + 导出 Markdown（客户端用同一份报告 JSON 生成，Playwright 下载实测 `labpilot-report-corr-analysis-25.md` 2887 字符，与页面一致）。

## 2. 证据链

报告 `conclusions` 每条带 `evidence: {dataset_id, analysis_ids, analysis, statistic, method, params, value}`；无 evidence 的结论不进入报告。实测：corr 报告 3 条结论 evidence 全部完整（见 report_corr_response.json）。前端每条结论旁“证据”展开项可点开查看。

## 3. 重跑比对

- `GET /api/analyses/{id}`（单条详情，含原始 params）；`POST /api/analyses/{id}/rerun` 按原记录 name 与 params_json 重跑 audit/stats/report（report 重跑不重新调 AI，沿用原 ai_text 并注明 `rerun_note`）；重跑结果作为新 analysis 行入库，返回 `{original_id, rerun_id, consistent, differences}`，关键数值相对容差 1e-9。

```
$ curl -X POST http://localhost:8000/api/analyses/11/rerun
→ consistent: true，rerun_id: 14，differences: []
```

- 前端 Archive 页真实分析记录列表（32 条）与报告页均有“重跑”按钮，展示对比结果；重跑后列表重载导致结果短暂清空的 bug 已修（RerunButton 模块级结果缓存）。

## 4. 分组比较（对照组 vs 实验组）

- `backend/app/groups.py`：Shapiro-Wilk（每组）→ Levene → 自动选检验：均正态且方差齐用独立样本 t 检验；正态但方差不齐用 Welch；任一组非正态用 Mann-Whitney U（注明比较分布与秩次而非均值）。效应量：参数检验 Cohen's d，非参数秩二列相关。结论文字含“组间差异不等于因果”。
- `POST /api/datasets/{id}/compare` / `GET /api/datasets/{id}/compare`，以 `name="compare"` 入库；`override_test` 改选记入 params，`auto_suggestion` 保留自动选择。

```
$ curl -X POST http://localhost:8000/api/datasets/3/compare -d '{"group_col":"group","value_col":"response"}'
→ 独立样本 t 检验（Shapiro p=0.105 / 0.221；Levene p=0.928494）
  t = -20.203418，p = 2.166478252142054e-44
  Cohen's d = -3.299204（效应量较大）
  control 均值 4.501413（n=75），treatment 均值 10.75636（n=75）
$ curl http://localhost:8000/api/datasets/3/compare
→ 最新比较 analysis_id 33，t 检验，p = 2.166478252142054e-44
```

- 前端统计页内分组比较区块：分组列/数值列下拉（真实列名）、前提检查全文、检验结果表、结论与风险提示。

## 5. 箱线图独立量纲（第二波遗留）

- Charts.tsx 新增“每列独立量纲”切换，默认开启：开启时每列单独成图、各用各的 Y 轴；关闭恢复共用一轴。
- dirty.csv 目视验证：concentration（箱体 ~0.46–0.55，异常点 2.45/0.7/0.3）、temperature、humidity 箱体与异常点全部清晰，不再被 sample_id（0–125）压扁；共 14 个 IQR 异常点，与审计的待确认清单一致。

## 6. 测试与构建（协调员亲手复核）

```
$ cd backend && .venv/bin/python -m pytest -q
79 passed, 1 warning in 3.43s
  （原有 44 个全部通过；新增 test_report.py 13 个 + test_compare.py 22 个）

$ cd frontend && npm run build
✓ built in 4.06s（仅 chunk 超大既有警告）
```

测试覆盖：AI 路径 source 与 manifest（raw_rows_sent=0）、AI 超时降级、篡改 AI 数字不影响渲染数字、证据链字段完整、重跑同参数一致、重跑用原始参数、检验选择三分支、效应量与手工计算一致、corr 黄金结构自洽、全部边界（分组列不存在、组数不足、样本量过小、非数值列、超 2 组未指定 groups、非法改选）。测试不调真实模型（mock subprocess）。另有一处旧测试随行为更新：`test_golden.py` 中 Wave 1 stub 时代断言 Gemini `available() is False` 的 3 行改为新行为（Gemini 已接线可用；DeepSeek 仍为 stub），测试总数不变。

## 截图（Playwright 真实无头浏览器，逐张目视检查过）

- `backend/docs/screenshots/wave3-01-report.png` — 报告页（AI 报告 #25：AI 生成标识、Token 599/180/779、gemini-3.5-flash-lite、5.95 秒、原始行发送 0 行；评分 100.0；相关矩阵 dose×response 0.9851；回归方程与 R²/n；结论证据展开；AI 解读）
- `backend/docs/screenshots/wave3-02-compare.png` — 分组比较结果（实时运行出分析 #33）
- `backend/docs/screenshots/wave3-03-rerun.png` — 重跑一致 #34 + compare 重跑 400 错误同屏
- `backend/docs/screenshots/wave3-04-boxplot.png` — dirty 独立量纲箱线图（4 列分图，14 个异常点）

截图脚本：`backend/scripts/screenshot_wave3.py`（Playwright venv 在 `/tmp/shot-venv`，临时目录，复跑需保留或重建）。

## 尚未解决的问题

1. **compare 分析不支持重跑**：`POST /api/analyses/{id}/rerun` 仅支持 audit / stats / report，compare 返回 400“分析类型 compare 不支持重跑”。前端已把该错误原样展示。本波任务书的重跑范围写的是“审计/统计/图表计算”，compare 未列入，故未扩；如需支持，后端在 rerun 分发里加 compare 分支即可（小改动）。
2. **侧边栏版本文案滞后**：前端侧边栏仍显示 “Wave 2 · v0.3.0”，后端已是 v0.4.0。纯展示问题，未修。
3. **Dashboard“科研项目数量”固定显示 1**：第二波遗留的展示性标签，多项目统计是后续需求。
4. 验证过程在开发库产生真实分析记录（报告 #13/#22/#25/#37、比较 #26/#31/#33、重跑 #14/#16/#19/#32/#34 等），属真实调用的正常产物；测试用独立临时库，不受影响。

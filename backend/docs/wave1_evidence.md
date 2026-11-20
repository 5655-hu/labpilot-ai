# LabPilot AI 第一波（扩展验收）证据包

> 范围：第一波结构/数据库/黄金数据/页面骨架/上传接口/基础测试，外加用户
> 2026-11-20 重新划线后追加的审计引擎、统计引擎、前端联调与扩展测试。
> 图表不在本波范围内（下一波）。本文件所有数字均为真实运行结果，未编造。
> 生成时间：2026-11-20（UTC+8）。后端版本 0.2.0。

环境：Python 3.12.3、Node v24.22.1、npm 10.9.4；后端 FastAPI 0.165.0 /
Uvicorn 0.54.0 / pytest 9.2.0；前端 Vite 8 + React 19 + TypeScript + Tailwind v4。

服务（验证时正在运行）：后端 `http://localhost:8000`，前端 `http://localhost:5173`。

## 1. 实际 API 请求与响应记录

### 1.1 健康检查

```bash
curl -s http://localhost:8000/health
```

```json
{"status": "ok", "version": "0.2.0", "db": "sqlite", "datasets": 3}
```

### 1.2 审计 dirty.csv（脏数据演示集，id=2）

```bash
curl -s -X POST http://localhost:8000/api/datasets/2/audit \
  -H 'Content-Type: application/json' \
  -d '{"algorithms":["iqr","zscore"],"profile":"measurement"}'
# HTTP 200；完整返回见同目录 audit_dirty_response.json
```

关键返回（完整 JSON 在 `audit_dirty_response.json`）：

```json
{
  "analysis_id": 7,
  "dataset_id": 2,
  "audit": {
    "rows": 126, "cols": 4, "total_cells": 504,
    "score": {
      "total": 97.95,
      "formula": "质量分 = 100 − (30×有效缺失率 + 20×重复行率 + 25×类型错误率 + 25×确定错误率)",
      "total_deduction": 2.05,
      "deductions": [
        {"category": "missing", "label": "缺失值", "weight": 30.0, "rate": 0.031746,
         "rate_basis": "有效缺失单元格 16 / 有效单元格总数 504", "deduction": 0.95,
         "evidence": [{"column": "temperature", "count": 9, "rate": 0.071429,
                       "example_rows": [{"row_index": 5, "row_number": 6, "value": null},
                                        {"row_index": 17, "row_number": 18, "value": null},
                                        {"row_index": 42, "row_number": 43, "value": null}]},
                      {"column": "humidity", "count": 5}, {"column": "concentration", "count": 2}]},
        {"category": "duplicate", "label": "重复值", "weight": 20.0, "rate": 0.047619,
         "rate_basis": "重复行 6 / 总行数 126", "deduction": 0.95},
        {"category": "type_error", "label": "字段类型错误", "weight": 25.0, "rate": 0.005952,
         "rate_basis": "类型错误单元格 3 / 全部单元格 504", "deduction": 0.15,
         "evidence": [{"column": "temperature", "count": 1, "example_rows": [{"row_index": 12, "row_number": 13, "value": "25.3C"}]},
                      {"column": "humidity", "count": 1, "example_rows": [{"row_index": 66, "row_number": 67, "value": "high"}]},
                      {"column": "concentration", "count": 1, "example_rows": [{"row_index": 90, "row_number": 91, "value": "0.52 mol/L"}]}]},
        {"category": "definite_error", "label": "确定错误（不可能的值）", "weight": 25.0, "rate": 0.0, "deduction": 0.0}
      ]
    },
    "missing": {"total": 16},
    "duplicates": {"count": 6},
    "unit_risks": [
      {"column": "temperature", "units": ["C"]},
      {"column": "concentration", "units": ["mol/L"]}
    ],
    "pending_outliers": [
      {"column": "temperature", "count": 4, "status": "待确认"},
      {"column": "humidity", "count": 5, "status": "待确认"},
      {"column": "concentration", "count": 5, "status": "待确认"}
    ]
  }
}
```

核对（与 `golden_manifest.json` 一致）：缺失 16、重复 6、类型错误 3
（temperature "25.3C"、humidity "high"、concentration "0.52 mol/L"）；统计异常
不扣分（IQR 与 Z-score 两种算法下总分同为 97.95）。

### 1.3 统计 corr.csv（相关性与回归数据，id=3）

```bash
curl -s -X POST http://localhost:8000/api/datasets/3/stats
# HTTP 200；完整返回见同目录 stats_corr_response.json
```

关键返回：

```json
{
  "analysis_id": 8,
  "dataset_id": 3,
  "stats": {
    "rows": 150, "cols": 5,
    "columns": {
      "dose": {"count": 150, "missing": 0, "mean": 2.54446, "median": 2.5385,
               "std": 1.429484, "variance": 2.043424, "min": 0.041, "max": 4.996},
      "response": {"count": 150, "missing": 0, "mean": 7.628887, "median": 7.4695,
                   "std": 3.662927, "variance": 13.417031, "min": 0.594, "max": 14.71}
    },
    "skipped_columns": [{"column": "group", "reason": "非数值列，已跳过"}],
    "correlation": {
      "method": "pearson",
      "matrix": {"dose": {"response": 0.98506, "dose": 1.0}}
    }
  }
}
```

核对：dose-response Pearson 相关系数 **0.98506**，与清单值一致（容差 ±0.001）。

### 1.4 取最新结果与 Dashboard 计数

```bash
curl -s http://localhost:8000/api/datasets/2/audit   # 最新审计，score 97.95
curl -s http://localhost:8000/api/datasets/3/stats   # 最新统计，Pearson 0.98506
curl -s http://localhost:8000/api/analyses
```

`GET /api/analyses` 返回 `total: 8`（4 次审计 + 4 次统计，均为真实运行记录），
Dashboard“已完成分析次数”显示同一数字。测试用的临时数据库与此开发库分离，
pytest 不受这些记录影响。

## 2. 前端实际操作截图

截图工具：本机原先没有 chromium / google-chrome / playwright，本波内通过
`pip install --break-system-packages playwright` + `playwright install chromium`
安装（Playwright 1.65.2，Chrome Headless Shell 159，约 126 MB，缓存于
`~/.cache/ms-playwright`）。截图为真实 Chromium 无头浏览器访问正在运行的
前端开发服务器（`http://localhost:5173`）所得，非合成图。

| 文件 | 内容 | 验证点 |
|---|---|---|
| `screenshots/01-dashboard.png` | Dashboard | 3 个数据集、476 行、已完成分析 2 次（截图时）、最近记录为真实审计与统计 |
| `screenshots/02-datasets-upload.png` | 数据集页上传 | 通过文件选择框真实上传 5 行 CSV，页面显示“已上传 shot_upload：5 行 × 3 列，SHA-256 已记录” |
| `screenshots/03-datasets-preview.png` | 数据集页预览 | 上传后点“预览”，真实表格前 5 行 |
| `screenshots/04-audit.png` | 审计页 | 脏数据评分 97.95/100、公式、扣分表、逐笔证据、待确认清单、豁免说明、规则快照、单位风险 |
| `screenshots/05-stats.png` | 统计页 | corr 数据描述统计表、Pearson 矩阵（dose-response 0.9851）、group 列跳过原因 |

## 3. pytest 全量结果

```bash
cd backend && .venv/bin/python -m pytest -q
```

```text
35 passed, 1 warning in 1.52s
```

35 个测试 = 第一波 17 个（全部继续通过）+ 审计 9 个 + 统计 9 个。覆盖：正常
数据、缺失数据、重复数据、异常值（IQR 与 Z-score）、空文件、非数值字段、
小样本（n=2）、常量列、无法计算相关性、审计/统计入库与取最新、无效参数。
唯一 warning 是 starlette 建议改用 httpx2 的 deprecation 提示，不影响结果。

## 4. 前端 build 结果

```bash
cd frontend && npm run build   # tsc -b && vite build
```

```text
vite v8.3.8 building client environment for production...
✓ 34 modules transformed.
dist/index.html                   0.45 kB │ gzip:  0.29 kB
dist/assets/index-CBIzsIpl.css   16.69 kB │ gzip:  4.26 kB
dist/assets/index-Bt26YCrI.js   294.99 kB │ gzip: 90.61 kB
✓ built in 508ms
```

TypeScript 类型检查与 Vite 构建均通过，无报错。

## 5. 尚未解决的问题清单

1. **本波内发现并已修复的问题（记录在案，不再遗留）：**
   - 第一波 `GET /api/analyses` 在结果非空时会 `KeyError: 'result_json'`（先
     `pop` 再读取同一键）；审计/统计写入首条结果后触发。已修复
     `app/routers/analyses.py` 与 `app/routers/_helpers.py`，35 个测试全过。
   - 侧边栏版本号仍显示“Wave 1 · v0.1.0”，已改为“Wave 2 · v0.2.0”并重新构建。
   - 截图脚本首版在删除数据集后等待一条不会消失的成功提示而超时；已改为
     用 API 确认删除成功，未伪造任何截图。
2. **注意（不是缺陷）：**脏数据按方案公式得分为 97.95——公式以单元格/行
   占比计分，16 个缺失占 504 个单元格仅 3.17%，所以分数看起来高；这是方案
   §6 的公式定义，不是计算错误。问卷型画像下同一数据为 98.15。
3. **未做（下一波及以后）：**Plotly 五类图表、报告组装与导出、复现档案逻辑、
   证据链与重跑（P1）、Turso libsql 客户端、公网部署与 Qoder Sites 上线。
4. **开发库现状：**`backend/data/labpilot.db` 内现有 8 条真实分析记录（本波
   验证运行产生），数据集仍为 3 份黄金数据（截图上传的临时数据集已删除）。
   测试使用独立临时数据库，不受影响。
5. **Dashboard“科研项目数量”显示为固定值 1**（当前项目 LabPilot AI），
   属展示性标签，非后端计算值；如需改为多项目统计，属后续需求。
6. **模型调用：本波 0 次，0 token、0 花费**（审计、统计、规则版 fallback
   均为确定性计算；AI 适配层 provider 仍为接口桩）。

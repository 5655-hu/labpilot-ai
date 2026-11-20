# LabPilot AI 第二波（图表）证据包

后端 v0.3.0。本波 **0 次模型调用，0 token、0 花费**。图表未用任何静态图片，全部是 Plotly.js 交互图（悬停读数、缩放、下载），数据全部由后端真实计算。

## 1. 实际 API 请求与响应（2026-11-20 实测）

### 箱线图 — dirty.csv（数据集 id 2）

请求：

```
GET /api/datasets/2/charts/boxplot
```

响应摘要（完整 JSON 见接口实时返回）：

```
boxes: sample_id 0 个异常点，temperature 4 个，humidity 5 个，concentration 5 个
total: 14 个异常点，与审计的 14 个待确认 IQR 异常点一致
每箱含 Q1 / 中位数 / Q3 / 须线（1.5×IQR）/ 异常点行号与值
```

### 线性回归 — corr.csv（数据集 id 3）

请求：

```
GET /api/datasets/3/charts/regression?x=dose&y=response
```

响应（完整 JSON 已保存为 `backend/docs/regression_corr_response.json`）：

```
equation:  response = 2.5241·dose + 1.2063
slope:     2.52413
intercept: 1.206339
R²:        0.970344   （= 0.98506²，容差内一致）
r:         0.98506
n:         150
points:    150 个观测点 + 拟合直线两端点
```

### 相关性热力图 — corr.csv（数据集 id 3）

请求：

```
GET /api/datasets/3/charts/heatmap
```

响应摘要：

```
columns: sample_id, dose, response, temperature（group 为非数值列，已跳过并注明）
matrix: 对称，对角线全为 1.0；dose-response = 0.98506
与统计页 compute_stats 的同一矩阵逐项一致（测试断言）
```

### 其他已验证的端点

- `GET /api/datasets/{id}/charts/columns` — 每列是否可作数值图及原因（group：非数值列）
- `GET /api/datasets/{id}/charts/histogram?column=temperature` — dirty 温度直方图：n=116（126 行 − 9 缺失 − 1 非数值 "25.3C"），频数之和 = 116
- `GET /api/datasets/{id}/charts/scatter|line?x=dose&y=response` — 150 个成对点；折线图按 x 升序
- 错误：非数值列作图 400、列不存在 400、bins=0 时 400、数据集不存在 404

## 2. pytest 测试结果

```
44 passed, 1 warning in 2.01s
```

第一波 35 个测试全部继续通过；新增 `tests/test_charts.py` 9 个：直方图频数之和等于有效样本数；箱线图异常点与审计逐项一致（含 Q1/须线）；散点/折线点数等于成对有效样本数、折线按 x 排序；热力图对称、对角线为 1、dose-response 为 0.98506、与统计接口一致；回归 R²/n/方程格式正确（斜率按范围 2.0–3.0 断言，不写死期望值）；小样本与常量列回归 400；非数值字段、不存在的数据集/列返回正确错误；columns 端点数值性判断；缺失值剔除计数。

## 3. 前端 build 结果

```
npm run build → tsc -b && vite build → ✓ built in 3.84s
```

Plotly.js 采用动态 import 懒加载，单独拆为 `plotly-*.js` chunk，不拖慢其他页面首屏。剩余一个 >500 kB chunk 体积警告属于 Plotly 本身体积，不影响使用。

## 4. 前端截图（Playwright 1.65.2 + Chrome Headless Shell 真实无头浏览器）

截图脚本：`backend/scripts/screenshot_wave2.py`（先确认图渲染出真实数据才截图，否则失败退出）。六张均已肉眼验过：

- `screenshots/wave2-01-histogram.png` — 直方图：dose（corr，6 箱 Freedman-Diaconis，n=150）
- `screenshots/wave2-02-boxplot.png` — 箱线图：dirty 四列，红圈异常点 14 个，数据说明与审计一致
- `screenshots/wave2-03-scatter.png` — 散点图：dose × response，强正相关形态清晰，150 点
- `screenshots/wave2-04-line.png` — 折线图：response 随 dose 变化，按 dose 升序
- `screenshots/wave2-05-heatmap.png` — 相关性热力图：dose-response 0.99，对角线 1.00，含“相关性不代表因果关系”提示（横幅 + 图下各一次）
- `screenshots/wave2-06-regression.png` — 线性回归：散点 + 红色拟合直线，回归面板含方程 `response = 2.5241·dose + 1.2063`、R² 0.9703、r 0.9851、n 150，含因果提示横幅

## 5. 本波内发现并已修复的问题

- 直方图测试期望值修正：temperature 有效数是 116 不是 117（"25.3C" 作为非数值被剔除，与统计引擎同一规则）；humidity 同理为 120。引擎行为正确，测试期望错，已修正并重测通过。
- 热力图 Y 轴标签被裁剪（"temperature" 显示为 "mperature"）与 "-0.00" 显示：Plot 组件统一注入 automargin，数值格式化把 |v|<0.005 显示为 0.00；已重截图验证。
- pkill 重启后端时误杀了自己的 shell（命令含匹配串）：改用括号 trick 避开自匹配；服务已恢复。
- Playwright 的 Python 包在环境刷新后丢失（浏览器二进制仍在缓存）：在后端 .venv 内重装 playwright==1.65.2，复用缓存的 Chromium Headless Shell，无需重新下载浏览器。

## 6. 尚未解决的问题

1. 报告组装与导出、复现档案逻辑、证据链与重跑、分组比较、Turso 客户端、公网部署/Qoder Sites — 后续波次，不在本波范围。
2. 箱线图多列共用同一 Y 轴：dirty 数据中 sample_id（0–120）量级远大于 temperature 等列，四箱同图时后三箱被压缩；数值与异常点均真实准确，如需每列独立量纲是后续体验优化。
3. Dashboard“科研项目数量”仍显示固定值 1（当前项目 LabPilot AI），属展示性标签，如需多项目统计是后续需求。
4. 两服务（:8000、:5173）保持运行中，可直接验收；前端当前跑的是 Vite 开发服务器（源码直出），生产构建产物在 `frontend/dist/`。

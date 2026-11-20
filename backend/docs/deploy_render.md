# Render 部署操作手册（后端）

目标：把 FastAPI 后端跑在公网，供 Qoder Sites 上的前端调用。
全程约 40 分钟，其中 Render 构建约 8 分钟。

---

## 第 0 步：先把代码推到 GitHub

Render 从 GitHub 拉代码，**本地代码不推上去它看不到**。

```powershell
cd C:\Users\Lenovo\Desktop\qoder\labpilot-ai
git push origin main
```

首次会弹窗让你登录 GitHub（浏览器授权），**不需要把 token 给任何人**。

> 两个选择，你要清楚后果：
> - `git push origin main` —— 覆盖远端为「改造版」。最简单，比赛就用这个。
> - `git push origin main:render` —— 推到新分支 `render`，远端 main 保持原始版。
>   注意：Blueprint 创建时要把分支选成 `render`，否则部署的还是原始版（那份在 Linux 上其实也能跑，但没有修复）。
>
> 本手册以下按 **推 main** 写。

---

## 第 1 步：确认渲染配置已在仓库里

仓库根目录必须有 `render.yaml`，`backend/.python-version` 内容为 `3.12.8`。
这两份文件已备好，推上去即可。

---

## 第 2 步：在 Render 创建 Blueprint

1. 打开 https://dashboard.render.com ，用 **GitHub 账号登录**（Sign in with GitHub）
2. 首次使用会要求授权 Render 读取你的仓库，点允许（可以只授权 `labpilot-ai` 这一个仓库）
3. 右上角 **New** → **Blueprint**
4. 选择仓库 `5655-hu/labpilot-ai`，分支 `main`
5. Render 会读出 `render.yaml` 并显示服务名 `labpilot-ai-backend`
6. 它会提示填写 `CORS_ORIGINS`（因为标了 `sync: false`）
   - **先填占位值**：`https://placeholder.qoder.zone`
   - 等前端发布后拿到真实域名，再回来改（见第 5 步）
7. 点 **Apply** / **Create**

---

## 第 3 步：等构建并验证

构建约 5-10 分钟。日志里应该能看到：

```
Successfully installed ... fastapi-0.165.0 ... pandas-2.1.4 ...
```

> `libsql-experimental` 在 Linux 有预编译 wheel（manylinux2014_x86_64），不会触发编译，属正常安装。

服务变成 **Live** 后，打开 Render 给你的地址（形如 `https://labpilot-ai-backend-xxxx.onrender.com`），访问：

```
https://<你的服务地址>/health
```

**期望返回：**

```json
{"status":"ok","version":"0.6.0","wave":"Wave 5","db":"sqlite","datasets":3}
```

如果 `datasets` 是 3，说明三份黄金演示数据已自动导入，后端完全可用。

> 免费实例 15 分钟无请求会休眠，之后再访问要等 30-60 秒冷启动——**这是正常现象，不是挂了**。
> 演示前建议先打开一次预热。

---

## 第 4 步：前端指向公网后端并构建

```powershell
cd C:\Users\Lenovo\Desktop\qoder\labpilot-ai\frontend
$env:VITE_API_URL='https://labpilot-ai-backend-xxxx.onrender.com'
npm run build
```

构建产物在 `frontend/dist/`。

> `VITE_API_URL` 是**构建时**写进 JS 的，改完必须重新 `npm run build`，改 `.env` 后再跑 dev 不会影响已构建产物。

---

## 第 5 步：发布到 Qoder Sites

在 Qoder 里把 `dist/` 发布成站点，然后：

1. 站点详情 → **分享** → **更改访问范围** → **任何人都可访问** → 确认「允许公开访问」
2. 复制地址（形如 `https://labpilot-xxxx.qoder.zone`）

---

## 第 6 步：回填 CORS（关键，漏了前端会全红）

1. 回 Render 控制台 → 你的服务 → **Environment**
2. 把 `CORS_ORIGINS` 改成 Qoder Sites 的真实域名：

```
https://labpilot-xxxx.qoder.zone
```

3. 保存，服务会自动重新部署（约 2 分钟）

> 为什么要这一步：FastAPI 的 CORS 白名单不给 Qoder 域名，浏览器会拦截所有请求，
> 页面看起来"能打开但一直加载失败"。这是部署后最常见的翻车点。

---

## 第 7 步：验收（必须用手机流量做一次）

用**手机 4G/5G 流量**（不要连公司/家里 WiFi），打开 Qoder Sites 地址：

- [ ] 首页能看到 3 个数据集
- [ ] 点「脏数据」→ 审计 → 出现质量分 **97.95**
- [ ] 点「相关性数据」→ 统计 → Pearson **0.98506**
- [ ] 图表页散点图正常渲染
- [ ] 报告页能生成并导出 Markdown
- [ ] 浏览器 F12 → Console 无红色报错，Network 无 CORS 失败

全部通过，后端这条线就算打通了。

---

## 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 构建失败，日志出现 `libsql` 编译 / Rust 报错 | 用了不支持的 Python 版本 | 确认 `backend/.python-version` 是 `3.12.8` |
| 页面能开，但一直"加载失败" | CORS 白名单没配 Qoder 域名 | 回第 6 步 |
| `/health` 返回 502 | 实例在冷启动 | 等 30-60 秒重试 |
| `/health` 返回 `datasets: 0` | seed 失败 | 看 Render 日志里 lifespan 报错 |
| 上传的文件过一会儿没了 | 免费层无持久磁盘 | 正常，按需接 Turso（`docs/turso_setup.md`） |
| 首次打开很慢 | 免费实例休眠后冷启动 | 正常，演示前预热一次 |

---

## 成本与限制（免费层）

| 项 | 限制 |
|---|---|
| 价格 | 0 元 |
| 休眠 | 15 分钟无请求休眠 |
| 内存 | 512 MB |
| 磁盘 | 临时，重启重置 |
| 带宽 | 100 GB/月 |

对本项目的演示规模（3 份黄金数据、单次上传 ≤10MB）足够。

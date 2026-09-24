# 青野 Verda — 常驻 Worker 部署手册

> 本手册配套 C 计划（让线上也能跑后台长任务）。**状态：只规划不部署** —— 配置文件已就绪，
> 实际发布需你确认并在目标主机执行。本地修复（`runner.py` 解耦）已就位，无需本手册即可本地运行。

---

## 0. 为什么需要 Worker（根因一句话）

线上 Vercel 是 **Serverless**：函数实例临时、限时、无状态。原 `run_pipeline` 直接在 SSE 处理函数里
`async for` 消费 → 任务生命周期 == HTTP 连接生命周期 → 断连即杀、超时即丢。本地修复把执行从传输
解耦到 `runner.py`（常驻进程 + 内存任务表 + 回放缓冲），但 **Serverless 没有常驻进程**，所以必须
把这套后端搬到一台「常驻单实例主机（worker）」，Vercel 降为静态前端 + 网关。

**核心 invariant（务必理解）**：执行与传输解耦后，反向代理 / SSE 超时**只影响展示层，不影响任务完成**——
`runner` 在 worker 进程内独立驱动 `run_pipeline`，前端 `EventSource` 断线重连 + 回放缓冲即可续看。

---

## 1. 三路径速览

| 路径 | 适用 | 运维成本 | 持久化 | 长任务 |
|---|---|---|---|---|
| ① PaaS（Railway/Render/Fly） | 想零运维上线 | 低 | 付费磁盘（free 层不持久） | ✅ |
| ② 自管云主机（复用阿里云 ECS 47.114.101.59） | 已有主机 / 要可控 | 中 | 主机卷（稳） | ✅ |
| ③ 本地 | 仅本机开发 | 无 | 本机 SQLite | ✅（已跑通） |

三路径**共用同一份后端代码 + 同一个 Dockerfile**，只是编排语法不同。镜像源单一，无代码分叉。

---

## 2. 环境变量总表（worker 必填 / 可选）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | ✅ | — | 智谱 GLM / BigModel API Key（旧名 `ZHIPU_API_KEY` 兼容） |
| `LLM_BASE_URL` | | `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容网关 |
| `LLM_MODEL` / `_CORE` / `_AUX` / `_FAST` | | glm-5.1 / 5.2 / 5.1 / glm-z1-air | 模型矩阵 |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | | 180 / 1 | 单次调用超时/重试 |
| `BOCHA_API_KEY` | ✅（采集） | — | 博查搜索 Key |
| `BOCHA_BASE_URL` | | `https://api.bocha.cn/v1` | — |
| `DOUYIN_COOKIE` / `XHS_COOKIE` / `BILIBILI_COOKIE` | | 空 | 平台采集（可选） |
| `APP_HOST` | | `127.0.0.1` | **容器内必须 `0.0.0.0`**（config.py 默认仅本机） |
| `APP_PORT` | | `8000` | 监听端口 |
| `VERDA_DB_PATH` | ✅ | `backend/app/data/verda.db` | **指向持久卷**，如 `/data/verda.db` |
| `ENABLE_DEMO_FALLBACK` | | `true` | 无 LLM 时降级演示 |

> 密钥经 `backend/app/core/config.py` 读取；运行时改配置走 `/api/settings` 落 SQLite（同样落在卷里，持久）。
> 前端仅需 `VITE_API_BASE`（见 §5）。

---

## 3. 路径① PaaS

### Railway
- 根目录 `railway.json` + `Dockerfile` 已就绪。
- 控制台：创建 Project → 链接仓库；在 **Variables** 填 `LLM_API_KEY`、`BOCHA_API_KEY`（其余 `railway.json` 已带默认值，`${LLM_API_KEY}` 引用项目变量）。
- **创建卷**：`railway.json` 引用卷名 `verda_data` 挂 `/data`，需在 Railway 控制台创建同名卷（size≥1GB），否则 `VERDA_DB_PATH=/data/verda.db` 写不进。
- 部署后健康检查 `GET /health` 返回 `{"status":"ok",...}` 即就绪。

### Render
- 根目录 `render.yaml` 已就绪（`runtime: docker`）。
- 控制台：**Environment** 填 `LLM_API_KEY` / `BOCHA_API_KEY`（`sync: false` 占位）。
- **磁盘**：`render.yaml` 已声明 `disk` 挂 `/data`；**free 实例无持久磁盘**，需升级 paid 才生效，否则重启丢数据（见 §6 风险）。
- `healthCheckPath: /health` 已配。

### Fly
- `fly launch` 用根 `Dockerfile`；`fly volumes create verda_data --size 1`；`fly deploy`。
- env 经 `fly secrets set LLM_API_KEY=... BOCHA_API_KEY=...`；挂载 `/data` 并设 `VERDA_DB_PATH=/data/verda.db`。

---

## 4. 路径② 自管云主机（阿里云 ECS 等）

镜像同源（根 `Dockerfile`），编排用 `deploy/docker-compose.yml`（单服务 + 命名卷 `verda_data`）。

### 一键引导（手动执行，不自动跑真机）
```bash
# 1) 把仓库放到 /opt/verda（或改脚本顶部 VERDA_REPO_DIR）
# 2) 执行引导脚本：装 docker → 写 .env → 构建启动 → systemd 自启 → Nginx 接入
VERDA_DOMAIN=verda.your-domain.com bash deploy/setup-vm.sh
```
脚本会：检测 docker、校验代码位置、生成 `deploy/.env`（交互填密钥，含占位符校验）、
`docker compose up -d`、`systemctl enable --now verda-worker`、`cp deploy/nginx/verda.conf` 到
`/etc/nginx/conf.d/verda.conf` 并替换域名、`nginx -t && reload`。

### 手动步骤（等价）
```bash
cd deploy
cp .env.worker.example .env      # 填入真实密钥
docker compose build
docker compose up -d
# Nginx：include deploy/nginx/verda.conf，改 server_name，reload
# systemd：cp deploy/systemd/verda-worker.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now verda-worker
```

### Nginx 要点（`deploy/nginx/verda.conf`）
- `proxy_buffering off` + `proxy_read_timeout 3600s`：SSE 思维流实时且不被截断。
- `proxy_set_header Connection ""`：SSE 是 HTTP/1.1 流式，不需 WebSocket 的 Upgrade。
- 容器不直暴公网，`expose 8000` 仅宿主内；由 Nginx 反代 `127.0.0.1:8000`。

---

## 5. 路径③ 本地（已完成，仅文档）

- 后端 `:8020` / 前端 `:3500` 本地已跑新代码，长任务修复生效，**无需任何 Worker / C 工作**。
- 前端 `VITE_API_BASE` 留空 → 走 `vite.config.ts` 代理 `/api` → `127.0.0.1:8020`。
- 本地 SQLite 默认 `backend/app/data/verda.db`（已 WAL）。

### 线上前端（Vercel 构建）
- `frontend/.env.example`：`VITE_API_BASE=https://<worker-domain>`。
- **Vite 在构建时内联 `import.meta.env`** → 必须在 Vercel「项目环境变量」设置后 **redeploy** 才生效。
- `vercel.json` 的 `buildCommand: npm run build` + `outputDirectory: frontend/dist` 不变。

---

## 6. Vercel 网关切换（cutover，条件触发，**本次不执行**）

当前 `vercel.json` 把 `/api/*` 指向 Serverless `api/index.py`（旧版，跑不了长任务）。
**Worker 稳定后**做两步：

1. `vercel.json` rewrite 指向 worker（Vercel rewrite 支持外部 URL）：
   ```json
   "rewrites": [
     { "source": "/api/(.*)", "destination": "https://<worker-domain>/api/$1" },
     { "source": "/health",   "destination": "https://<worker-domain>/health" },
     { "source": "/(.*)",     "destination": "/index.html" }
   ]
   ```
2. 确认 worker 稳定后**删除 `api/index.py` 及 `api/app` 副本**（消除双真相、避免旧代码误导）。

> 门槛：必须等至少一个 worker 真实可用，否则删 `api/index.py` 会让线上 Vercel 直接 404。

---

## 7. 架构硬约束（部署必守）

- **`--workers 1`**：`runner._running` 是进程内存任务表，多 worker 会破坏断连续跑/回放/取消。
- **单实例**：SQLite 单写，worker 必须单实例；水平扩展须换 Postgres + 外部任务队列（超出本手册）。
- **持久卷 `/data`**：任务/报告/证据全落 `verda.db`，无卷重启即丢。
- **SSE 代理放行**：`proxy_buffering off` + 高 `read_timeout`（Nginx 已配；PaaS 平台代理超时仅影响展示）。

---

## 8. 健康检查与监控

- `GET /health` → `{"status":"ok","llm_configured":bool}`。
- `GET /api/llm/ping` → 实测 LLM 连通（worker 是线上 SPOF，建议接外部监控定时 ping）。
- `GET /api/tasks/running` → 进行中任务列表（悬浮条/侧栏入口依赖）。
- 容器重启：lifespan 里 `reconcile_orphans()` 把 DB 残留 `running` 标 `failed`，前端不会永久转圈。

---

## 9. 回滚

- 不删 `api/index.py` 前：直接回退 `vercel.json` rewrite 即可恢复 Serverless（旧行为）。
- Worker 出问题：compose `down` / PaaS 回退上个镜像；SQLite 在卷里不受影响。
- 配置错误：改 `deploy/.env` 或平台变量 → 重启 worker（`docker compose restart` / Redeploy）。

---

## 10. 风险与约定

- 不连真机、不 push、不实际部署（遵守「只规划不部署」）。
- `setup-vm.sh` 仅作可复用脚本，执行前需你确认并填真实密钥/域名。
- PaaS free 层无持久磁盘 → 数据重启即丢；要持久请用付费磁盘或路径②。
- 多 worker 一律禁止；SQLite 单写 → worker 必须单实例。

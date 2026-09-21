# 青野 Verda · AI 旅游调研工作台

> 让每个结论都有出处，让每次调研都活着。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Built with TRAE](https://img.shields.io/badge/Built%20with-TRAE%20AI-7C5CFF.svg)](https://www.trae.ai/)

青野 Verda 是一个**会自己组队、能溯源、看得见思考过程**的「AI 旅游调研工作台」。
它把一支由 48 位虚拟专家组成的多 Agent 团队封装进一条 Deep Research 流水线：从澄清需求、真实联网采集、交叉验证、结构化分析，到并行撰写一份带证据溯源的旅游调研报告——全程可观测、可回放、可人工介入二次深化。

首页可选择调研类型：**游玩攻略**（交通 · 住宿 · 路线 · 美食 · 预算）与**调研评估**（可达性 · 配套 · 安全 · 性价比），类型决定章节骨架、搜索角度、分析结构与澄清问卷。

- **真实，不演示**：真实 LLM（智谱 GLM）+ 真实联网搜索（博查 Bocha）+ 真实网页抓取 + SQLite 持久化。搜不到就如实标注「未采集到」，绝不编造假数据。
- **每个结论都有出处**：四条铁律——无证据不立论 / 交叉验证 / 返工闭环 / 全程可观测。
- **看得见的思考**：每个 Agent 的 Prompt、输入输出、Token、决策、引用证据全部落 Trace，可在工作台实时滚动、在报告页「决策回放」。

> 本项目在开发过程中深度使用 [TRAE](https://www.trae.ai/) AI 编程工具协作完成，设计与演进过程见 [docs/系统升级实施方案.md](./docs/系统升级实施方案.md)。

---

## ✨ 核心特性

| 能力 | 说明 |
|---|---|
| 🧠 多 Agent 编排 | 48 位分层虚拟专家（决策层 / 策略层 / 执行层），按任务自动组队、指派、终审 |
| 🔎 Deep Research 流水线 | `intake → orchestrator → collect → analyze → write → audit → done`，带返工闭环 |
| 🌐 真实联网采集 | 博查 Bocha 多角度多轮搜索 + 真实正文抓取 + 乱码/相关性过滤 |
| 📊 结构化知识 Schema | 游玩攻略：逐日路线 / 住宿选型 / 预算拆解；调研评估：可达性矩阵 / 配套清单 / 风险画像。前端渲染路线表、清单与矩阵 |
| 🔬 可信度真实计算 | 按来源分级 + 域名权威性 + 时效性 + 抓取质量打分（0–100，非写死） |
| 📈 量化提升 & 业务闭环指标 | 效率提升 / 覆盖度 / 一致性 / 准确率 / 人工修正率，每项可解释 |
| 👀 全链路可观测 Trace | 每个 Agent 的 Prompt/输出/Token/决策可查、可回放 |
| ✍️ 批注驱动二次调研 | 对报告正文划线批注 → 触发针对性补充调研并更新章节 |
| 🎚️ 三档调研模式 | 快速 / 深度 / 专家级，按搜索量 + 章节数 + 模型档位分档 |

---

## 🏗️ 技术栈

**前端**：React 19 · TypeScript · Vite · TailwindCSS · Zustand · React Router · ReactFlow · ECharts / D3 · Framer Motion

**后端**：FastAPI · LangGraph 风格编排 · SQLite · SSE（Server-Sent Events 思维流）

**LLM**：智谱 GLM（BigModel 开放平台，OpenAI 兼容网关）。核心章 `glm-5.2`、辅助章 `glm-5.1`、杂务 `glm-z1-air`，多模型按章节分配以充分利用并发额度

**搜索**：博查 Bocha Web Search

更完整的架构与数据流见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

---

## 📂 目录结构

```
.
├── frontend/              # React + Vite 前端
│   ├── src/
│   │   ├── components/    # 通用组件（VTracePanel / VDataGrid / VChart 等）
│   │   ├── layout/        # AppLayout / VSidebar 全局框架
│   │   ├── pages/         # 11 个页面（首页/工作台/报告/图谱/Trace/专家…）
│   │   ├── store/         # Zustand 状态管理
│   │   ├── lib/           # api.ts 等工具
│   │   └── hooks/         # useTaskStream（SSE 订阅）
│   └── tailwind.config.js # 设计 token 主题映射
│
├── backend/              # FastAPI + 多 Agent 编排后端（本地开发主目录）
│   ├── app/
│   │   ├── core/          # 编排 / LLM / 搜索 / 抓取 / 可信度 / Trace / 指标…
│   │   ├── data/          # 48 专家定义 experts.json
│   │   └── main.py        # FastAPI 入口
│   └── requirements.txt
│
├── api/                  # Vercel Serverless 部署入口（后端代码的部署镜像，见下方说明）
│   └── index.py
│
├── docs/                 # 架构 / Agent 协议 / 部署 / 设计方案文档
├── vercel.json           # Vercel 部署配置
├── restart.sh / stop.sh  # 本地一键启停脚本
└── LICENSE               # AGPL-3.0
```

> **关于 `backend/` 与 `api/` 的代码重复**：
> `backend/` 是本地开发与调试的主目录；`api/` 是为 [Vercel Serverless](https://vercel.com/docs/functions) 部署准备的镜像副本（Vercel 约定 Serverless 函数放在 `api/` 目录）。两者业务逻辑一致，部署时只使用 `api/`。详细说明与同步约定见 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)。

---

## 🚀 快速开始

### 环境要求

- Node.js ≥ 22.12
- Python ≥ 3.9

### 1. 克隆并配置密钥

```bash
git clone <your-repo-url>
cd verda

# 配置后端密钥（绝不硬编码，全部走环境变量）
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 ZHIPU_API_KEY 等（见下方「配置密钥」）
```

### 2. 启动后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8020
# 后端: http://localhost:8020   健康检查: /health   LLM 自检: /api/llm/ping
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
# 前端: http://localhost:3500
```

### 一键启停（可选）

项目根目录提供了本地一键脚本（macOS / Linux）：

```bash
./restart.sh   # 清理旧进程 → 启动后端(:8020) → 等待就绪 → 启动前端(:3500)
./stop.sh      # 按端口精确关闭本项目前后端
```

---

## 🔑 配置密钥

复制 `backend/.env.example` 为 `backend/.env`，按需填写：

| 变量 | 说明 | 必填 |
|---|---|---|
| `ZHIPU_API_KEY` | 智谱开放平台 API Key（GLM 调用），从 https://open.bigmodel.cn 获取 | 是（真实 LLM 调用） |
| `ZHIPU_MODEL` / `ZHIPU_MODEL_CORE` / `ZHIPU_MODEL_AUX` / `ZHIPU_MODEL_FAST` | 多模型矩阵（默认 / 核心章 / 辅助章 / 杂务） | 否（有默认值） |
| `BOCHA_API_KEY` | 博查 Bocha Web Search Key，从 https://open.bocha.cn 获取（形如 `sk-xxxx`） | 真实联网采集时必填 |
| `DOUYIN_COOKIE` / `BILIBILI_COOKIE` / `XHS_COOKIE` | 各平台舆情采集 cookie | 平台采集时按需 |
| `APP_PORT` | 后端端口（默认 8000，本地脚本用 8020） | 否 |
| `FRONTEND_ORIGIN` | 前端地址（CORS 白名单），默认 `http://localhost:3500` | 否 |

验证 LLM 是否打通：

```bash
curl http://localhost:8020/api/llm/ping
```

---

## 🔒 安全说明

- **所有密钥仅通过环境变量读取，绝不硬编码在代码中**（见 [backend/app/core/config.py](./backend/app/core/config.py)）。
- `.env` 及各类密钥文件已在 [.gitignore](./.gitignore) 中屏蔽，不会被提交。
- 本地数据库 `*.db` / WAL / SHM、运行日志 `.run-logs/` 均不入库。
- 提交代码前请再次确认：**没有任何真实的 API Key / Token / Cookie 被提交**。

---

## 📖 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 系统架构、模块划分、数据流、Deep Research 流水线 |
| [docs/AGENTS.md](./docs/AGENTS.md) | 48 专家分层、Agent 角色、消息协议、四条铁律 |
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | 本地部署、Vercel 部署、backend/api 同步约定 |
| [docs/系统升级实施方案.md](./docs/系统升级实施方案.md) | 完整设计与演进方案（含 AI 协作过程） |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 贡献指南、提交规范、分支管理 |

---

## 🤝 贡献

欢迎 Issue 与 PR。提交前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，遵循约定式提交（Conventional Commits）与代码风格规范。

## 📄 许可证

本项目采用 **[AGPL-3.0](./LICENSE)** 开源许可证。
这意味着：你可以自由使用、修改、分发本项目，但**任何修改后的版本（包括通过网络提供服务的形式）都必须以相同的 AGPL-3.0 许可证开源**。

# 常青圈 · 15 分钟生活圈智能体检

> 基于地图开放能力，给社区做一次「15 分钟生活圈」体检：测等时圈、数民生设施、找服务盲区、出诊断报告。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions%20%2B%20Gitee%20Go-blue)](./.github/workflows/ci.yml)

2026 上海开源软件应用创新大赛 · 百度地图命题一《基于地图开放能力的"15 分钟生活圈"智能体检与规划助手》。本项目 fork 自青野 Verda（AI 竞品情报工作台），保留其多 Agent 编排、全链路可观测与证据溯源内核，重构为**生活圈体检助手**。

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| 🗺️ 等时圈计算 | 渔网采样 + 百度批量算路（routematrix walking）+ IDW 反距离加权插值，产出 5/10/15/20 分钟可达圈 |
| 🏪 民生设施体检 | 8 类 POI（医疗/教育/菜市/养老/购物/金融/文体/政务）+ 三要素（菜市场/药店/小学）1km 覆盖判定 |
| 🚨 服务盲区识别 | 1km 网格扫描，聚合相邻盲点到灰区，标注缺失设施与最近可及点 |
| 📋 综合评分 | 类别覆盖 × 三要素 × 盲区三因子打分（0–100），附差异归因 |
| 👥 专家队诊断 | 从 48 位名册中按需组队（建议 8–13 人：空间定位师/网格规划师/各域顾问），按 GB50180 生活圈标准出具章节化报告，证据溯源可查 |
| ⚡ 智能体流水线 | `intake → plan → measure → collect → diagnose → report → audit`，SSE 实时流式展示（`useTaskStream`） |
| 📊 双社区对比 | 指标差异表 + 双雷达图，同一口径下量化设施覆盖差距 |
| 🔍 全链路可观测 | 每个专家/阶段的 Prompt、产出、参数、Event 可回放（Trace） |

另保留原 Verda 能力：竞品情报 Deep Research、48 专家编排、可信度计算、批注驱动二次调研、一页纸简报。

---

## 🏗️ 架构

```
前端（React 19 + Vite —— VITE_USE_MOCK 开关）
 ├─ 工作台：输入社区名/坐标 → 发起体检 → /workspace/:taskId（SSE 思维流）
 ├─ 生活圈地图：等时圈族 + 彩色 POI + 盲区灰区 + 右侧体检单（SVG 画布，零 AK 零依赖）
 ├─ 报告双层：指标速览（雷达/评分/盲区清单）+ 章节化诊断报告
 ├─ 双样例对比：指标差异表 + 双雷达
 └─ 历史 / 报告中心：/api/life-circle 真实记录归档

后端（FastAPI）
 ├─ living_circle 域（独立子域，A1）
 │   ├─ pipeline/living_circle.py   # 体检流水线（A2 独立编排，SSE 事件契约对齐 A4）
 │   ├─ pipeline/diagnosis_templates.py # D4 专家诊断规则模板（数据驱动，无散乱 if-else）
 │   ├─ living_circle/isochrone.py  # 渔网采样 + 批量算路 + IDW 等值线（自实现，不引 scipy/shapely）
 │   ├─ living_circle/poi.py        # 8 类 POI 采集清洗 + 类别统计
 │   ├─ living_circle/blindspot.py  # 1km 盲区扫描 + 灰区聚合
 │   ├─ living_circle/scoring.py    # 三因子评分
 │   ├─ living_circle/data_source.py# 三级数据源：Live(百度 AK+配额) / Offline(全国区划+距离模型) / fixture(内置演示)
 │   │                              #   + CachingDataSource 横切缓存（30 天落盘，无 AK 离线可查历史实时结果）
 │   ├─ living_circle/repository.py # SqliteCache 落盘缓存（lc_cache.db，WAL + busy_timeout）
 │   ├─ living_circle/geo_index/    # 全国省市区三级区划 + 区县中心坐标（离线地名定位，随仓库提交）
 │   └─ living_circle/baidu_client.py + request_guard.py  # 真实 API 调用 + 限流/退避（韧性）
 ├─ core/runner.py                  # 后台常驻任务调度（按 kind 分发，断连续跑，重连补帧）
 ├─ core/db.py                      # SQLite（含 living_circle_reports 独立文档）
 └─ main.py                         # REST + SSE 端点（/api/tasks、/api/life-circle、/api/life-circle/regions、/api/life-circle/{id}/share…）
```

> **三级数据源 + 离线兜底（T1-T6）**：有百度 AK/配额 → Live 真实路网测时 + 真实 POI（主链路，赛题 40% 实时性）；无 AK/预算耗尽 → 先查历史实时缓存（`served_from=cache`，30 天内离线可查），未命中走 **Offline 离线估算**（内置全国区划定位 + 复用等时圈引擎的「直线距离 × 绕行系数」距离模型，`data_origin=offline`，诚实标注不产出可比评分/盲区）；`fixture` 仅作演示/对比样例。前端按 `data_origin`+`served_from` 四态徽标标注（离线估算 / 历史实时 / 真实数据 / 演示数据），离线报告显示「评分待实时体检」占位，绝不冒充真实路网测时。

---

## 🚀 快速开始

### 方式 A：Docker 一键预览（推荐）

```bash
docker compose up --build
# 前端 http://localhost:3400  后端 http://localhost:8010
```

无需任何 AK：缺省走内置 fixture 演示（凯里老街 / 北京劲松双样例，等时圈零依赖可跑）。

### 方式 B：本地两命令

```bash
# 1) 后端（Python ≥3.9，建议 3.12）
cd backend && python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8010

# 2) 前端（Node ≥22）
cd frontend && npm install && npm run dev
# 前端 http://localhost:3400（vite 已代理 /api → :8010）
```

### 一键脚本（macOS/Linux）

**从零到跑全自动**（推荐，首次/换机/依赖缺失时用）：

```bash
./start.sh            # 环境自检 → 按需自动建环境装依赖 → 启动前后端 → 自动打开浏览器
./start.sh --check    # 只做自检，不启动不安装
./start.sh --no-install  # 跳过依赖安装直接启动（依赖已就绪时更快）
./start.sh --force    # 强制重装后端/前端依赖
./start.sh --no-open  # 启动但不自动打开浏览器
```

日常启动/重启/关闭：

```bash
./restart.sh   # 清理旧进程 → 后端(:8010) → 前端(:3400)
./stop.sh
```

---

## 🔑 百度地图 AK 配置（生活圈真实实跑）

1. 控制台 [百度地图开放平台](https://lbsyun.baidu.com/) → 应用管理 → 创建**服务端**与**浏览器端**两个应用。
2. **服务端应用**：启用 Geocoding/逆地理编码、地点检索、路线规划、坐标转换、批量算路 → `BAIDU_SERVER_AK`。
3. **浏览器端应用**：启用 JS API、地点搜索、地理编码；**Referer 白名单**填写：
   - `http://localhost:3400/*` `http://127.0.0.1:3400/*`（开发）
   - 线上域名按实际填写（AK 绑定域名后才生效）。
4. 复制模板写入：

```bash
cp backend/.env.example backend/.env
# backend/.env 填入：BAIDU_SERVER_AK=…  BAIDU_BROWSER_AK=…
# （可选）BAIDU_MAP_STYLE_ID=…  —— 百度控制台「个性化地图」发布的样式 ID，用于底图风格调适
```

缺 AK 时不影响演示（自动降级为静态画布并标注「内置快照」）；`BAIDU_BROWSER_AK` 供前端 BMapGL 渲染真实地图（地图页/对比页），经 `GET /api/life-circle/map-config` 下发（浏览器 AK 为公开键，靠 Referer 白名单限域，属设计内行为）。

**AK 脱敏三档**：本地 `.env` / `config.local.js`（gitignore，不入库）→ CI 从仓库 Secret 注入 → 代码占位符兜底（空值即降级，无密钥运行时零报错）。浏览器 AK 公开属设计内，靠 Referer 白名单限域；服务端 AK 只存于 `backend/.env`，接口层 `mask_effective` 脱敏，日志不落明文。

> 其余密钥（LLM / 搜索 / 平台 cookie）见 `backend/.env.example` 注释。所有密钥仅走环境变量，`.env` 已被 .gitignore 屏蔽。

---

## 🗺️ 真实地图渲染（评审对齐）

- **底图**：BMapGL v3.0 真实百度瓦片（可缩放/平移），应用「个性化地图」浅色样式（`BAIDU_MAP_STYLE_ID` 优先，空则内置低饱和 styleJson 模板），与项目浅色视觉一致。
- **强调（赛题 30%）**：底图仅作地理参照，**不取底层路网**——等时圈/耗时场完全由「渔网采样 → 分散点位批量算路测时 → IDW 插值」推导（见算法简述），与底图路网拓扑无关。
- **热力（赛题 40%）**：采样点耗时热力（按 0→20min 渐变着色；点数随档位与本次预算变，生效规格逐份写在报告 `sampling.spec`）+ 5/10/15/20min 等值线族叠加 + POI 真实坐标 Marker + 盲区灰区。
- **交互**：中心标记可拖拽（D2 确认流）、「定位到我」浏览器定位（BMapGL Geolocation 转 BD-09 + 逆地理）、点击 POI 弹详情。
- **降级**：无 AK / 离线 / 脚本加载失败 → 自动回退静态 SVG 画布 + 降级横幅（评审无网演示能力不退化）。
- **快照点位补采**：`cd backend && .venv/bin/python -m scripts.make_fixture_points` —— 只向权威快照附加 `poi.points`（真实坐标），不改动评分/等时圈/盲区等冻结字段（百度个人额度有限，建议低峰/次日运行）。

---

## 🧮 算法简述（提交材料背书）

- **等时圈**：中心 2.5km 渔网采样（默认 standard 档：粗扫 400m → 15min 边界带加密 150m；档位不同规格不同，**每份报告实际用了哪一套写在 `sampling.spec`**，预算不够时会如实标 `degraded`）→ 百度批量算路（一次 N×1 距离矩阵）→ IDW 反距离插值生成步行耗时场 → marching-squares 提取 5/10/15/20 分钟等值线。纯 numpy 自实现，不引 scipy/shapely 重依赖（AK 演示与镜像体积双赢）。
- **POI 清洗**：多关键词检索 → 去重/过滤 → 类别统计 + IDW 耗时回填最近设施。
- **盲区**：1km 网格扫描（三要素任一缺失判盲）→ 相邻聚合灰区 → 输出缺失清单与最近可及设施。
- **评分**：类别覆盖 / 三要素 / 盲区三因子加权（0–100），透明公式可解释。
- 详见 [docs/地图API调用策略与等时圈算法设计.md]、[docs/多源POI数据清洗与服务盲区识别算法.md]、[docs/真实社区对比测试报告.md]（M5 交付）。

---

## 🧪 数据模式：真实联调 / 演示

两种模式**运行时可切**：侧边栏「数据模式」即时生效，选择记在 localStorage
（`frontend/src/store/dataModeStore.ts`，默认**真实联调**）。

- 演示（fixture）：前端由 `src/mocks/fixtures/` 驱动、后端走内置双样例（凯里老街 / 北京劲松），
  离线可用、零 AK；等时圈在离线估算下为圆形近似。
- 真实联调（live）：区划选择、采集、等时圈、报告全部走后端 + 真实百度 AK。
- `VITE_USE_MOCK` 只是**首次打开的默认值**（`.env.development` 当前为 `0`），不是唯一开关；
  要改默认值就直接改那一行，不必用 sed。
- 两种模式的 SSE 事件契约完全一致（A4），前端 `useTaskStream` 无缝切换，联调零返工。

---

## 🧪 测试与 CI

```bash
# 后端（living_circle 域 + research 回归；镜像守卫在 api/ 缺失时自我 SKIP）
cd backend && .venv/bin/python -m pytest -q
# 前端（lint/typecheck/vitest/build）
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
```

CI（全 mock，不注入任何真实 AK）：
- GitHub Actions（唯一真源）：[.github/workflows/ci.yml](./.github/workflows/ci.yml) —— push/PR 自动跑后端+前端+Docker 构建。
- Gitee 侧：[.workflow/ci.yml](./.workflow/ci.yml) 是真源的**子集**（只有 backend + frontend 两个 job，
  不含 api/ 校验 step 与 docker 构建 job）。改真源时若有意不跟过去，需在那份文件里记明差异。

---

## 📖 文档

| 文档 | 内容 |
|---|---|
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | 本地部署、云端三路径、端口单一真值源、`api/` 镜像约定废止记录 |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 系统架构、两个产品域、地图链路、数据模式与降级 |
| [docs/AGENTS.md](./docs/AGENTS.md) | 专家分层、角色、消息协议、四条铁律 |
| [docs/系统升级实施方案.md](./docs/系统升级实施方案.md) | fork 前的完整设计演进（含 AI 协作过程） |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 贡献指南、提交规范 |

---

## 🤝 贡献

欢迎 Issue 与 PR。提交前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，遵循约定式提交与代码风格规范（前端 lint 必须 0 error）。

## ⚖️ 许可

[AGPL-3.0](./LICENSE)。随附/依赖的第三方组件及其许可证与署名义务见 [NOTICE](./NOTICE)
（其中 Apache ECharts 的 NOTICE 义务在该文件 §1 原文转述）。
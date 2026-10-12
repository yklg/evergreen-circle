# 常青圈 · 15 分钟生活圈智能体检

> 基于地图开放能力，给社区做一次「15 分钟生活圈」体检：测等时圈、数民生设施、找服务盲区、出诊断报告。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions%20%2B%20Gitee%20Go-blue)](./.github/workflows/ci.yml)

2026 上海开源软件应用创新大赛 · 百度地图命题一《基于地图开放能力的"15 分钟生活圈"智能体检与规划助手》。

> 仓库同时承载**两个产品域**（同一套 Agent 骨架，互不共享业务代码、只共享 `core/` 能力与 Trace/证据底座）：
> 赛题主命题的**生活圈体检**（产品本体），与**目的地调研**（攻略/评估——报告页与工作台思维流走这条）。
> 域边界见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) §2。

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| 🗺️ 等时圈计算 | 渔网采样 + 百度批量算路（routematrix walking）+ IDW 反距离加权插值，产出 5/10/15/20 分钟可达圈 |
| 🏪 民生设施体检 | 8 类 POI（医疗/教育/菜市/养老/购物/金融/文体/政务）+ 三要素（菜市场/药店/小学）1km 覆盖判定 |
| 🚨 服务盲区识别 | 1km 网格扫描，聚合相邻盲点到灰区，标注缺失设施与最近可及点 |
| 📋 综合评分 | 覆盖 / 可达 / 多样 / 均衡四维加权（0.40 / 0.25 / 0.20 / 0.15）+ 盲区扣分（封顶 12 分），附差异归因 |
| 👥 专家队诊断 | 从 48 位名册中按需组队（建议 8–13 人：空间定位师/网格规划师/各域顾问），按 GB50180 生活圈标准出具章节化报告，证据溯源可查 |
| ⚡ 智能体流水线 | `intake → plan → measure → collect → diagnose → report → audit`，SSE 实时流式展示（`useTaskStream`） |
| 📊 双社区对比 | 指标差异表 + 双雷达图，同一口径下量化设施覆盖差距 |
| 🧭 地标体检 | 在**攻略报告**里选一个景点就能以它为中心发起体检：来源（宿主类型/报告/景点）落进侧表 `report_spot_checks` 的 `origin` 三元组，体检台复用同一条确认流（未确认不建任务、不耗配额），攻略页回读显示该景点最近一次的体检 |
| 🔍 全链路可观测 | 每个专家/阶段的 Prompt、产出、参数、Event 可回放（Trace） |

---

## 🏗️ 架构

```
skip
├─ frontend/                        # React 19 + Vite 前端（数据模式运行时可切：live / fixture）
│   ├─ src/
│   │   ├─ pages/                   # 路由页：工作台（/workspace/:taskId，SSE 思维流）/ 生活圈体检台 / 报告 / 对比 / 简报 / 专家…
│   │   ├─ components/              # 组件：lifecircle/（等时圈地图 + 彩色 POI + 盲区灰区 + 右侧体检单）＋ 报告零件（V*）
│   │   ├─ lib/                     # api / bmap（BMapGL 唯一加载器；无 AK 降级 SVG）/ livingCircle（口径渲染器单一出口）/ geo
│   │   ├─ store/                   # zustand：dataMode（live / fixture）/ taskRegistry（任务流）/ annotation（划词批注）
│   │   ├─ mocks/                   # 内置演示数据：fixtures/（凯里老街 / 北京劲松 / 上海五角场 / 凯里下司等 5 样例）+ eventFlow
│   │   ├─ hooks/                   # useTaskStream（SSE 订阅）等通用 hooks
│   │   └─ layout/                  # AppLayout / VSidebar 全局框架
│   └─ tailwind.config.js           # 设计 token 主题映射
├─ backend/                         # FastAPI + 多 Agent 编排后端
│   ├─ app/
│   │   ├─ living_circle/           # 生活圈域（独立子域，A1）：isochrone（渔网采样+批量算路+IDW）/ poi / blindspot / scoring（四维加权+盲区扣分）/ data_source（Live/Offline/fixture 三级）/ baidu_client / geo_index…
│   │   ├─ core/                    # 两域共享底座：runner（任务调度）/ db / LLM / Trace / pipeline/（living_circle.py、diagnosis_templates.py、research/＝目的地调研域）
│   │   └─ main.py                  # FastAPI 入口（REST + SSE：/api/tasks、/api/life-circle…）
│   ├─ tests/                       # pytest 套件（含结构与契约守卫）
│   └─ requirements.txt
├─ docs/                            # 架构 / Agent 协议 / 部署 / 算法设计文档
├─ deploy/                          # 自管云部署（docker-compose + nginx + systemd）
├─ scripts/                         # CI 守卫与体检脚本（check_app_mirror / lc_healthcheck）＋ 一键演示 run-demo.sh
├─ cookie-export-helper/            # 浏览器扩展：Cookie 导出助手（抖音 / 小红书 / B站 → 模型配置·平台采集）
├─ make_brand_icon.py               # 品牌图标生成脚本（favicon.svg 单一源 → apple-touch-icon + 验收页）
├─ .github/                         # GitHub Actions CI：后端 / 前端 / 排版 e2e（＋ Docker 条件步）
├─ start.sh / restart.sh / stop.sh  # 一键启动（新设备自动建环境）/ 重启 / 停止 —— 端口真值源 .dev-ports.env
├─ Dockerfile + docker-compose.yml  # 本地一键预览（前端 3400 / 后端 8010）
├─ package.json                     # Vercel 构建入口（npm run build → 前端构建）
├─ railway.json / render.yaml / vercel.json   # 云端部署清单（见 docs/DEPLOYMENT.md）
└─ LICENSE (AGPL-3.0) / NOTICE / CONTRIBUTING.md
```

> **三级数据源 + 离线兜底（T1-T6）**：有百度 AK/配额 → Live 真实路网测时 + 真实 POI（主链路，赛题 40% 实时性）；无 AK/预算耗尽 → 先查历史实时缓存（`served_from=cache`，30 天内离线可查），未命中走 **Offline 离线估算**（内置全国区划定位 + 复用等时圈引擎的「直线距离 × 绕行系数」距离模型，`data_origin=offline`，诚实标注不产出可比评分/盲区）；`fixture` 仅作演示/对比样例。前端按 `data_origin`+`served_from` 四态徽标标注（离线估算 / 历史实时 / 真实数据 / 演示数据），离线报告显示「评分待实时体检」占位，绝不冒充真实路网测时。

---

## 🚀 快速开始

### 方式 A：Docker 一键预览（推荐）

```bash
docker compose up --build
# 前端 http://localhost:3400  后端 http://localhost:8010
```

无需任何 AK：缺省走内置 fixture 演示（凯里老街 / 北京劲松 / 上海五角场 / 凯里下司等 5 份内置样例，等时圈零依赖可跑）。

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

```bash
./start.sh       # 一键：自检 → 按需建 venv/装依赖 → 启动前后端 → 自动打开浏览器（新设备/首次用这个）
./start.sh --check       # 只做依赖自检与版本核查（不安装/不启动/不开浏览器）
./start.sh --no-install  # 跳过依赖安装直接启动
./start.sh --no-open     # 启动但不打开浏览器
./start.sh --force       # 强制重装后端/前端依赖
./restart.sh     # 日常纯重启（不查依赖、不开浏览器，更快）
./stop.sh        # 关闭服务
```

> 新设备从零：只跑 `./start.sh` 一条命令 —— 缺 venv / 缺 node_modules / 缺 `backend/.env`
> 都会自动补齐（pip 连不上默认源时自动改走清华镜像重试），依赖按内容指纹缓存、第二次起秒级跳过。
> ⚠️ 手动建环境前先读 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) §1：「本机 Python 解释器约束」
> 说明了为什么别照抄 `python3 -m venv` 那句就以为能起（细节只写在那一处，别在别处再抄）。

### 🎯 评审方无 Key 演示指南

**无需任何百度 AK / LLM API Key**，项目内置 fixture 数据可完整演示所有功能：

```bash
# 推荐方式：一键演示模式（零配置启动）
./scripts/run-demo.sh
```

演示模式特性：
- ✅ 自动检测 Node.js / Python / 前后端依赖并提示缺失项
- ✅ 强制使用内置快照数据（凯里老街 / 北京劲松 / 上海五角场等 5 样例）
- ✅ 禁用所有外部 API 调用（百度地图 / 智谱 LLM），确保零网络依赖
- ✅ 自动打开浏览器到工作台首页
- ✅ 提供清晰的演示路径指引（见下方"推荐演示路径"）

停止服务：`./stop.sh` | 查看日志：`tail -f .run-logs/backend-demo.log`

**推荐演示路径**（覆盖赛题全部评分点）：

1. **工作台**（首页）→ 点击「凯里老街」或「北京劲松」示例卡，观察三档体检模式（速览/标准/精细）
2. **体检地图页** → 查看 5/10/15/20min 四级等时圈（彩色多边形）、POI 分布（医疗/教育/养老/商业分色标注）、服务盲区（灰色区域 = 1km 内无菜市场/药店/小学）、拖动中心点体验新旧对比
3. **报告页** → 顶层体检单（总评分 + 雷达图 + 三要素结论）、下层章节（医疗/教育/养老/商业逐章诊断）、亮点卡（每章首部的关键读数要点）
4. **对比页**（导航栏「对比」）→ 双社区同图叠加、指标对比表 + 双雷达图、切换三态（同比例尺 / 同中心 / 叠加）
5. **历史页**（导航栏「历史」）→ 查看历次体检记录列表

⚠️ 演示模式下横幅会标注「内置快照 · data_origin='fixture'」，不调用任何外部 API，但功能链路与真实实跑完全一致。

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

### 用途与服务条款声明（对应[百度地图开放平台服务条款](https://lbsyun.baidu.com/index.php?title=open/law)）

先把两件事分开，别混：**本项目的代码**按 [AGPL-3.0](./LICENSE) 授权（见文末「许可」），
而**对百度地图开放服务的使用**是 2026 上海开源软件应用创新大赛 · 百度地图命题的参赛作品演示，
属**非商业目的** —— 对应条款 2.3／2.6 条（商业目的需付费或取得书面许可）。代码许可证与用途声明
互不覆盖：AGPL 授予的是代码的权利，不授予任何对厂商服务的商业使用权。

同时如实记录两条与本仓实现直接相关的边界（不是免责套话，它们决定了我们怎么做工程取舍）：

- **2.2 条**只禁止"直接存取/技术抓取内部数据"，**未明确界定** API 响应结果能否缓存、落库或再分发。
  ⇒ 本项目的留存范围是**派生指标与实测快照**（报告载荷、出厂夹具、探针回执），标注探针日期并留
  可重跑脚本，不保存厂商内部数据；`backend/app/living_circle/capability_manifest.json` 里那份等时圈探针回执即此纪律的样本。
- **2.10 条**规定次数/数据量/版本的限制**无须事先声明** ⇒ 运行时外部依赖比静态快照更脆弱。
  ⇒ 任何依赖厂商状态的能力都自带**可见的降级与时效标记**，不做静默回落：无 AK → 离线估算并标
  `data_origin=offline`（屏幕同时写明"圆形近似，非真实路网形状"）；命中复用 → 标 `served_from`
  与数据年龄；服务打不通 → 记成能力边界而不是悄悄放弃（例：官方等时圈实测 `status=240`
  「APP 服务被禁用」，现有个人免费 AK 无该服务权限）。

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
  **插值形态也是口径、逐份可举证**：每个格点取最近 `8` 个实测点、按 `1/距离²` 加权，两个数是有名常量（`isochrone.IDW_POWER` / `IDW_NEIGHBORS`）并随报告发在 `sampling.interpolation_power` / `interpolation_neighbors`（契约 B15 罚"半份声明"；这条口径生效前的存量件两半皆缺，属合法、不因此不可展示）。拿到载荷的人因此**能复算这个场**，而不是只能信一个方法名。
  **实测过的"动态"边界**（2026-10-06 真实调用核实，见 [docs/地图API调用策略与等时圈算法设计.md](./docs/地图API调用策略与等时圈算法设计.md) §1.5）：百度步行测时是**确定性几何函数** —— 同参数连跑两次、以及与 6 天前落库的同一批点对照，40/40 点逐位相同（含"当地午夜 vs 工作日上午"这组对照）。⇒ 上面这套流程可复现，但也**拿不到时刻/路况这根轴**：红绿灯、过街天桥、施工围挡不做直接建模，而是以「残差耗时 / 受阻代理」披露（`sampling.detour`，只按分钟、不指认因果、未乘进总分）。
- **POI 清洗**：多关键词检索 → 去重/过滤 → 类别统计 + IDW 耗时回填最近设施。
- **盲区**：1km 网格扫描（三要素任一缺失判盲）→ 相邻聚合灰区 → 输出缺失清单与最近可及设施。
- **评分**：覆盖 / 可达 / 多样 / 均衡四维加权（0.40 / 0.25 / 0.20 / 0.15）+ 盲区扣分（封顶 12），透明公式可解释。
- 详见 [docs/地图API调用策略与等时圈算法设计.md]、[docs/多源POI数据清洗与服务盲区识别算法.md]、[docs/真实社区对比测试报告.md]（M5 交付）。

---

## 🧪 数据模式：真实联调 / 演示

两种模式**运行时可切**：侧边栏「数据模式」即时生效，选择记在 localStorage
（`frontend/src/store/dataModeStore.ts`，默认**真实联调**）。

- 演示（fixture）：前端由 `src/mocks/fixtures/` 驱动、后端走内置双样例（凯里老街 / 北京劲松），
  离线可用、零 AK；等时圈在离线估算下为圆形近似。
- 真实联调（live）：区划选择、采集、等时圈、报告全部走后端 + 真实百度 AK。
  **复用是有条件且上屏的**：同参数 30 天内、或中心点 500m 内有既有报告时直接复用（`served_from`
  标 cache/nearby_cache 并挂横幅说明"未消耗百度额度"），报告与体检单同时给出**数据时点与年龄**
  和这三档窗口（30 天 / 辅材 7 天 / 500m）；图上那枚「重新体检」是唯一的强制重算入口
  （带 `force`，跳过复用但仍照走几何门与配额账；`force` 不参与缓存键也不进口径三元组）。
  ⚠️ 演示态不发复用窗口 —— fixture 链里没有任何复用，发出去就是承诺一条当下不成立的规则。
- `VITE_USE_MOCK` 只是**首次打开的默认值**（`.env.development` 当前为 `0`），不是唯一开关；
  要改默认值就直接改那一行，不必用 sed。
- 两种模式的 SSE 事件契约完全一致（A4），前端 `useTaskStream` 无缝切换，联调零返工。

---

## 🧪 测试与 CI

```bash
# 后端（living_circle 域 + research 回归；镜像守卫在 api/ 缺失时自我 SKIP）
cd backend && .venv/bin/python -m pytest -q
# 前端（typecheck/vitest/build）
cd frontend && npm run typecheck && npm run test && npm run build
```

> **lint 单独跑、别串进上面这条链**：`npm run lint` 目前存量约 111 个 error（CI 里也把它设成
> `continue-on-error` 非阻断诊断，阻断权交给 vitest 的 lint 棘轮）。用 `&&` 串进来会让它在第一步就
> 红掉、挡掉后面 typecheck/test/build 三步。想看清单就单跑 `cd frontend && npm run lint`。

CI（全 mock，不注入任何真实 AK）：
- GitHub Actions（唯一真源）：[.github/workflows/ci.yml](./.github/workflows/ci.yml) —— push/PR 自动跑后端 + 前端 + 排版 e2e（Playwright）+ Docker 构建（共 4 个 job）。
- Gitee 侧：[.workflow/ci.yml](./.workflow/ci.yml) 是真源的**子集**（只有 backend + frontend 两个 job，
  不含 api/ 校验 step、e2e 排版回归与 docker 构建 job）。改真源时若有意不跟过去，需在那份文件里记明差异。

---

## 📚 参考文献

> 本节汇集本项目的**文献与标准基础**（原文 PDF 存于本地 `参考文献/` 目录，因体积未随仓库分发，下表为著录清单）。
> **诚实说明**：项目正文对具体参数的引用多为匿名表述（如「文献指出…」），并未逐条点名以下条目；
> 这里是**主题级研究基础**，不是逐句引注。

### 一、政策文件与国家标准（代码 `caliber.py` / `category_rule.py` 具名引用）

1. 中华人民共和国住房和城乡建设部. 城市居住区规划设计标准：GB 50180—2018[S]. 北京：中国建筑工业出版社, 2018. —— 生活圈分级（5/10/15 分钟）与三要素配套口径来源。
2. 自然资源部. 城市社区生活圈规划指南：TD/T 1062[S]. —— 逐要素服务半径表（表 A.1 小学 500m、菜市/生鲜 500m、卫生服务中心 1000m；表 A.3 卫生服务站 500m、≥120㎡）出处。
3. 商务部等 11 部门. 关于推进城市一刻钟便民生活圈建设的意见：商务部〔2021〕247 号[Z]. 2021. —— 「步行约 15 分钟服务半径」政策表述与「基本保障类业态（含药店）」清单来源。

### 二、生活圈理论与标准解读

4. 于一凡. 从传统居住区规划到社区生活圈规划[J]. 城市规划, 2019, 43(5). —— 平均步行速度 3~4 km/h、15 min 出行量级。
5. 柴彦威, 于一凡, 王慧芳, 等. 学术对话：从居住区规划到社区生活圈规划[J]. 城市规划, 2019, 43(5).
6. 黄明华, 吕仁玮, 王奕松, 等. “生活圈”之辩——基于“以人为本”理念的生活圈设施配置探讨[J]. 规划师, 2020, 36(22).
7. 吴夏安, 徐磊青, 仲亮. 《城市居住区规划设计标准》中 15 分钟生活圈关键指标讨论[J]. 规划师, 2020, 36(8). —— 15 分钟生活圈 800~1000 m、非直线系数讨论。
8. 郭亚琪, 孙明. 历史街区低、多层高密度住宅指标分析与布局形式研究——基于对《城市居住区规划设计标准》的思考[J]. 遗产与保护研究, 2019, 4(1).
9. 夏巍, 郑彩云, 成钢, 等. 人本主义视角下的武汉社区生活圈规划研究[J]. 城市规划, 2018, 42(增刊 2).

### 三、15 分钟生活圈评估与可达性方法

10. 罗雪瑶, 张文佳, 柴彦威. 15 分钟生活圈的建成环境阈值效应研究[J]. 地理研究, 2022, 41(8). —— 建成环境阈值与步行可达性。
11. 周弦. 15 分钟社区生活圈视角的单元规划公共服务设施布局评估：以上海市黄浦区为例[J]. 城市规划, 2020(1)（总第 255 期）.
12. 韩增林, 董梦如, 刘天宝, 等. 社区生活圈基础教育设施空间可达性评价与布局优化研究——以大连市沙河口区为例[J]. 地理科学, 2020, 40(11): 1774-1783. —— UNA 工具包、教育设施可达性。
13. 翟石艳, 孔云峰, 宋根鑫, 等. 面向 15 min 生活圈的城市服务设施规划模型与实验[J]. 地理学报, 2023, 78(6). —— μCFLP 服务半径+覆盖率双约束模型。
14. 李帅. 上海市公共服务设施布局特征与生活圈优化研究——基于 POI 的城市生活便利度指数[J]. （期刊出处待核）. —— POI 便利度指数方法参照。
15. Sun Y, Luo S. A Study on the Current Situation of Public Service Facilities' Layout from the Perspective of 15-Minute Communities—Taking Chengdu of Sichuan Province as an Example[J]. Land, 2024, 13: 1110.
16. Xie H, Wang X, Wang Z, et al. Mismatch between infrastructure supply and demand within a 15-minute living circle evaluation in Fuzhou, China[J]. Heliyon, 2023, 9: e20130.

### 四、供需匹配与均等化

17. 常飞, 王录仓, 马玥, 等. 城市公共服务设施与人口是否匹配？——基于社区生活圈的评估[J]. 地理科学进展, 2021, 40(4). —— 15 min 为 1000 m 的圈层划定。
18. 郭念发, 王录仓, 常飞, 等. 基于社区生活圈的学前教育资源均等性评价及优化策略——以兰州市主城区为例[J]. 经济地理, 2024, 44(11).
19. 孔雪松, 宋璐, 黄雨蕾. 乡村社区生活圈公共设施供需评价与分区优化[J]. 经济地理, 2026, 46(4).

### 五、适老化与专项评估（学位论文）

20. 丁立坤. 健康公平视角下社区公共服务设施布局适老性评价及优化研究[D]. 杭州：浙江大学, 2022. —— 老年人 0.8 m/s、5/10/15 分钟适老步行圈层。
21. 梁伟研. 社区生活圈公共服务设施布局适老化评估体系研究——以广州市越秀区为例[D]. 广州：华南理工大学, 2020. —— 老年人 0.8 m/s、5~10 分钟高频设施布局。
22. 徐艺文. 城市社区公共服务设施区位研究[D]. 徐州：中国矿业大学, 2020.
23. 周碧茹. 基于生活圈的城市社区公共服务设施布局优化研究——以苏州市高新区为例[D]. 苏州：苏州科技大学, 2018.
24. 吴晨玮. 基于城市 POI 点的西安市中心城区公共服务设施空间布局优化研究[D]. 西安：西北大学, 2017.
25. 何振华. 旧城区社区公共服务设施规划研究——以重庆市江北区五里店街道为例[D]. 重庆：重庆大学, 2016.

### 六、在线文献

26. 人文地理（RWDL）2023 年第 4 期：<https://html.rhhz.net/RWDL/html/20230409.htm>
27. 人文地理（RWDL）2025 年第 1 期：<https://html.rhhz.net/RWDL/html/20250116.htm>



## 📖 文档

| 文档 | 内容 |
|---|---|
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | 本地部署、云端三路径、端口单一真值源、`api/` 镜像约定废止记录 |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 系统架构、两个产品域、地图链路、数据模式与降级 |
| [docs/AGENTS.md](./docs/AGENTS.md) | 专家分层、角色、消息协议、四条铁律；**§7「量的出处 · 术语表」**（两把互不换算的尺、派生的第三把「残差耗时/受阻代理」、`covered` 三义、措辞硬禁令） |
| [docs/地图API调用策略与等时圈算法设计.md](./docs/地图API调用策略与等时圈算法设计.md) | 调用策略与限量韧性、等时圈算法（渔网采样 + IDW + 等值线）、**§1.5 实测能力边界**（步行测时没有「时刻」这根轴、官方等时圈 `status=240` 无权限、零消费字段核实） |
| [docs/多源POI数据清洗与服务盲区识别算法.md](./docs/多源POI数据清洗与服务盲区识别算法.md) | 多词检索与查全判据、1km 判盲与盲区聚合、评分公式与参数全量披露 |
| [docs/真实社区对比测试报告.md](./docs/真实社区对比测试报告.md) | 凯里 vs 劲松 真实实跑对比（M5 交付）；顶部有**代次与尺名声明**，§9 补 10-05→10-06 的口径演进（残差耗时、数据时效与复用、插值形态的敏感性、可复现性实测依据） |
| [docs/系统升级实施方案.md](./docs/系统升级实施方案.md) | fork 前的完整设计演进（含 AI 协作过程） |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 贡献指南、提交规范 |

---

## 🤝 贡献

欢迎 Issue 与 PR。提交前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，遵循约定式提交与代码风格规范（前端 lint 必须 0 error）。

## ⚖️ 许可

[AGPL-3.0](./LICENSE)。随附/依赖的第三方组件及其许可证与署名义务见 [NOTICE](./NOTICE)
（其中 Apache ECharts 的 NOTICE 义务在该文件 §1 原文转述）。

# 系统架构 · Architecture

本文档描述常青圈 EvergreenCircle 的整体架构、两个产品域、地图链路与关键数据流。
部署与端口见 [DEPLOYMENT.md](./DEPLOYMENT.md)，Agent 分层与消息协议见 [AGENTS.md](./AGENTS.md)。

> **写作纪律**：本文只描述「结构」与「为什么这样切」，凡是会漂移的数字（模型名、并发、
> 配额、章节数、阈值）一律指向真值源文件，不在此复制。上一版架构文档就是因为把
> `MODE_CONFIG` 与旧 IA 抄进正文，代码演进后整篇变成假话。

---

## 1. 总览

前后端分离，**后端只有一份代码真相 `backend/`**（曾经的 Vercel Serverless 镜像 `api/` 已删除，
见 [DEPLOYMENT.md](./DEPLOYMENT.md) §5）：

- **前端** `frontend/`：React 19 + Vite 单页应用，经 REST + SSE 与后端通信。
- **后端** `backend/`：FastAPI + SQLite，内含多 Agent 编排、真实联网采集、等时圈几何计算、
  可信度评分、可观测 Trace 与口径（caliber）单一事实源。

```mermaid
graph TB
    subgraph Client["🖥️ 前端 React + Vite"]
        UI[页面 / 组件]
        Store[Zustand 状态<br/>数据模式·批注·偏好]
        SSE[useTaskStream]
        MapCfg[useMapConfig]
    end

    subgraph Server["⚙️ 后端 FastAPI"]
        API[main.py 路由面]
        subgraph LC["生活圈域 app/living_circle"]
            ISO[isochrone / contour]
            POI[poi / poi_collector]
            CAL[caliber 单一事实源]
            SCORE[scoring / blindspot / field]
            CONTRACT[report_contract / degrade_policy]
        end
        subgraph RES["目的地调研域 app/core/pipeline"]
            ENG[research/engine 流水线]
            LCT[living_circle.py / lc_team.py]
        end
        subgraph Core["core 能力模块"]
            LLM[llm.py 多模型]
            Search[search.py 博查]
            Fetch[fetcher.py 抓取]
            Cred[credibility.py]
            Trace[trace.py]
        end
        Baidu[(百度开放平台<br/>baidu_client)]
        DB[(SQLite db.py)]
    end

    UI --> Store
    Store -->|REST fetch| API
    SSE -->|EventSource| API
    MapCfg -->|GET /api/life-circle/map-config| API
    API --> LC
    API --> RES
    LC --> Baidu
    RES --> Core
    LC --> DB
    RES --> DB
    Core --> DB
```

---

## 2. 两个产品域

同一套 Agent 骨架承载两个域，**互不共享业务代码，只共享 `core/` 能力与 Trace/证据底座**：

| 域 | 代码位置 | 产出 |
|---|---|---|
| **生活圈体检**（产品本体） | `app/living_circle/`（21 模块）+ `app/core/pipeline/living_circle.py`、`lc_team.py`、`diagnosis_templates.py` | 等时圈、设施覆盖、盲区、0–100 评分与章节化诊断报告 |
| **目的地调研**（fork 继承能力） | `app/core/pipeline/research/`（`engine.py` 编排 + `collect/analyze/writer/spots/assemble/charts_build/perspective/planning/dispatch/modes/_util/runtime/errors`） | Deep Research 报告、证据溯源、结构化对象 |

### 生活圈域的关键切分

- **口径单一事实源 `caliber.py` / `caliber_index.py`**：出行方式、速度、绕行系数、网格粒度
  等"算法口径"只在这里定义，报告与评分都从这里取值并随报告落一份 `caliber` 举证对象 ——
  任何数字都要能回答「按什么口径算的」。
- **几何与采集分离**：`isochrone.py`（渔网采样 + 批量算路 + IDW 插值）与 `contour.py`（等值线）
  只产几何；`poi.py` / `poi_collector.py` 只产设施事实；`scoring.py` / `blindspot.py` /
  `field.py` 在其上做判定。
- **契约前移**：`report_contract.py` 在**落库前**判几何与举证契约（圈外点、采集半径、口径可举证），
  `degrade_policy.py` 决定降级形态 —— 不合格的报告不入库，而不是入库后再靠前端遮。
- **配额与闸**：`quota.py` + `request_guard.py` + `baidu_client.py` 构成进程级共享闸
  （唯一工厂拿闸，这条纪律由 `scripts/check_guard_construction.py` 在 CI 期机器校验）。

---

## 3. 目的地调研流水线

由 `app/core/pipeline/research/engine.py` 驱动：

```mermaid
flowchart LR
    intake[intake<br/>需求澄清] --> orchestrator[orchestrator<br/>组队/排计划]
    orchestrator --> collect[collect<br/>多角度真实采集]
    collect --> analyze[analyze<br/>论点/结构化分析]
    analyze --> write[write<br/>并行撰写章节]
    write --> audit{audit<br/>质检}
    audit -->|不达标| rework[rework<br/>补采/重分析]
    rework --> collect
    audit -->|通过| done[done<br/>签发报告]
```

三档调研模式（快速 / 深度 / 专家级）在搜索角度数、每角度抓取数、章节集、模型档位、
freshness 与写作深度上分档 —— 具体取值以 `pipeline/research/modes.py` 的 `MODE_CONFIG` 为准。

**依赖方向是机器校验的**（`check_guard_construction.py` 的 G-5/G-6/G-7）：流水线内层不得回握
`orchestrator`/`runner`；外壳只许依赖 `research.engine` 公共面；research 子模块不得回边 import
`engine`。违反即 CI 红，不靠人记。

---

## 4. 多模型编排

LLM 调用统一经 `app/core/llm.py`，按任务类型分档以利用各模型并发额度
（默认值真值源 `app/core/config.py`，切厂商只需改 base_url/key/model，或走「模型配置」页）：

| 档位 | 默认模型 | 用途 | 并发 |
|---|---|---|---|
| core | `glm-5.2` | 核心章（摘要/功能/定价/结论/创新章） | 10 |
| aux | `glm-5.1` | 辅助章（格局/画像/趋势/SWOT/风险） | 10 |
| fast | `glm-z1-air` | 杂务（intake/澄清/情感分类/单条重写） | 30 |

单次调用超时与重试同样以 `config.py` 为准（重型 JSON 产出耗时长，重试次数刻意压低以免
最坏情况叠加成 3×timeout）。写作阶段各章并行，单章独立 token 预算与模型，
**单章失败不影响其它章节**。

---

## 5. 地图链路（AK 与底图纪律）

**浏览器端 AK 只有一个来源**：后端 `GET /api/life-circle/map-config`
（`app/main.py` 的 `life_circle_map_config()`）下发 `BAIDU_BROWSER_AK` 与可选的
`BAIDU_MAP_STYLE_ID`；前端唯一入口是 `lib/bmap.ts` 的 `getMapConfig()`，
组件侧经 `hooks/useMapConfig.ts` 取用（模块级缓存，只缓存「取到的那一次」，
后端不可达时不固化失败结果）。

- 服务端 AK（`BAIDU_SERVER_AK`）只给后端调用（地理编码 / POI / 路线 / 批量算路），
  **不能用于 JS API**（服务类型与 Referer 白名单都不匹配）。
- 浏览器 AK 是公开键，靠百度控制台的 Referer 白名单限域。
- JSAPI 加载器全项目唯一：`loadBMapGL()`（必须带 `type=webgl`，否则百度返回经典版、
  `window.BMapGL` 永不存在 ⇒ 必然降级）。曾经报告侧另有一份私有加载器与另一套
  构建期变量，导致地图页有图、报告只有占位 —— 已收敛。
- **底图注记纪律活在代码里**：`lib/bmapStyle.ts` 内置 styleJson 模板整层关闭底图 POI 注记
  （保留路名与行政区名）。`setMapStyleV2` 的 `styleId` 与 `styleJson` 互斥二选一，
  默认不下发 styleId —— 第三方设施名与我们的 Marker 同款呈现会被读成自家数据，
  这是数据可信度问题而非配色偏好。

---

## 6. 数据模式与降级

三态，**运行时可切**（侧边栏「数据模式」，选择记在 localStorage）：

| 模式 | 数据来源 | 等时圈 |
|---|---|---|
| live（真实联调） | 后端 + 百度开放平台真实调用 | 真实路网批量算路 |
| fixture（演示） | 内置双样例（凯里老街 / 北京劲松） | 内置快照 |
| offline 估算 | 有中心无 AK / 配额受限 | 圆形近似，**报告须如实标注来源** |

降级不是"失败"而是"另一种诚实形态"：`degrade_policy.py` 决定形态，`data_source.py` 决定取数，
报告侧带 `data_origin` / `served_from` 徽标，让读者看得见这份数据从哪来。
`ENABLE_DEMO_FALLBACK` 控制无 LLM key 时是否走演示兜底。

---

## 7. 实时通信：SSE 思维流

工作台经 `GET /api/tasks/{task_id}/stream`（Server-Sent Events）接收流水线事件：
`node_update`（节点状态）· `thought`（思考/发现，带 kind 与 expert）· `message`（结构化消息，
含返工）· `evidence`（新证据）· `chart` / `image` · `progress` · `trace` ·
`report_ready` / `done` / `error`。

**执行与传输解耦**（`app/core/runner.py`）：任务生命周期不等于 HTTP 连接生命周期，
代理超时或断连只影响展示层，`runner` 在 worker 进程内独立驱动，前端重连 + 回放缓冲续看。
代价是 `runner._running` 为进程内存任务表 ⇒ **worker 必须单实例、`--workers 1`**（见
[deploy/README.md](../deploy/README.md) §7）。

---

## 8. 可观测性 Trace

每次 LLM 调用在 `app/core/trace.py` 落一条 `TraceSpan`：
`span_id · task_id · seq · agent_id · stage · purpose · model · prompt(摘要) · response(摘要) ·
token 三项 · latency_ms · decision · evidence_ids · ts`。

埋点是**无侵入**的（不要求给每个 `chat()` 改签名）。落 `traces` 表后有三个消费面：
工作台悬浮面板实时滚动、报告页「决策回放」按 `seq` 步进高亮对应 Agent 与引用证据、
独立 `/trace/:reportId` 页查询每个 Agent 的 Prompt/输出/Token/决策。

---

## 9. 数据持久化

SQLite（`app/core/db.py`），12 张表：

| 表 | 内容 |
|---|---|
| `tasks` | 任务、澄清答案、模式 |
| `reports` | 调研报告全文 JSON（sections/trace/metrics/structured/data_grid） |
| `living_circle_reports` | 生活圈体检报告 |
| `lc_cache` | 生活圈采集/算路缓存（省配额、可复现） |
| `evidences` | 全局证据溯源库（可信度、时效、来源） |
| `traces` | 可观测决策链路 |
| `subscriptions` | 监控订阅 |
| `report_feedback` | 人工修正反馈（→ 业务闭环指标） |
| `expert_stats` | 专家席位统计 |
| `destination_discovery_cache` | 目的地发现缓存 |
| `prefs` / `settings` | 用户偏好与运行时配置（运行时改配置走 `/api/settings`，落库持久） |

报告整份 JSON 一次下发（`GET /api/reports/:id`），前端零额外请求即可渲染 trace / metrics /
结构化对象。库路径由 `VERDA_DB_PATH` 决定（默认 `backend/app/data/verda.db`），已开 WAL。

---

## 10. 前端结构

```
src/
├── pages/        # 16 个页面
├── components/   # V 前缀通用组件；lifecircle/ 放地图与体检视图
├── layout/       # AppLayout（带侧边栏）/ VSidebar
├── store/        # Zustand：数据模式、批注、偏好、任务名册、UI
├── hooks/        # useTaskStream（SSE）· useMapConfig（地图 AK/styleId）
├── lib/          # api.ts（REST+SSE）· bmap.ts（JSAPI）· bmapStyle.ts（底图纪律）· caliber 消费面
├── __tests__/    # Vitest；helpers/bmapGLFake.ts 是全套件唯一 BMapGL 替身出口
└── dev/          # 取证探针页逻辑（不被入口引用 ⇒ 不进生产包，但进 tsc 与 eslint）
```

路由分两类（真值源 `src/App.tsx`）：带侧边栏的常规页（首页向导 / 生活圈地图 / 双样例对比 /
报告中心 / 专家团 / 历史 / 模型配置）与全屏沉浸页（澄清 / 工作台 / 报告 / 幻灯片 / 图谱 / Trace）。
`/library`、`/knowledge` 已移出主导航但保留深链。

品牌称谓唯一真源 `src/lib/brand.ts`，`index.html` 的 `<title>` 由 `brand.test.ts` 钉住不漂移。

设计令牌（`src/index.css` 的 `:root`，`--c-*` / `--r-*` / `--ease` / `--shadow-*`）命名刻意
**不含产品名**：令牌里一旦编进品牌名，每次改名都要重命名一遍整个 CSS 面，而漏改的那一处
不报错、不警告，只是静默丢色（2026-09-28 由 `--verda-*` 迁到 `--c-*`，见 §12 的 CSS 变量守卫）。

### 页面滚动所有权与舞台契约

同一个应用里并存**三种滚动模型**，各自都成立，但**必须有主人**——否则"控件随滚动消失"
这类症状会在每个新页面重犯（2026-10-04 生活圈体检台就是这么把图例弄丢的：地图被
`align-items: stretch` 拉到 1627px，锚在它顶边的图例一下滑就出屏）。

| 模型 | 谁在滚 | 用在哪 | 写法要点 |
|---|---|---|---|
| 整页滚 | `AppLayout` 的 `<main>`（`layout/AppLayout.tsx:8`） | 报告中心、首页等文档式页 | 页根 `min-h-full`，不接管滚动 |
| 面板内滚 | 每个面板自己 | 工作台三栏（`WorkspacePage.tsx:98`） | 三栏 `min-h-0` + 各栏 `overflow-y-auto` |
| 舞台式（体检台） | 只有右槽滚，地图与图例不进滚动链 | 生活圈体检台（`LcStage`） | 页根 `lg:h-full lg:overflow-hidden` + 两栏 `lg:grid-rows-[minmax(0,1fr)]` |

契约的**唯一真源**是 `components/lifecircle/stageContract.ts`（五组 utility + 为什么），
DOM 形状由 `components/lifecircle/LcStage.tsx`（`.Canvas/.Legend/.Panel`）持有，
页面只写 `<LcStage>` 与 `LC_PAGE_ROOT`。三条硬规矩：

1. **地图高度不许由内容决定。** BMapGL canvas 按父容器**像素高**撑开（`ComparePage.tsx:341`
   的注释记下过这条），所以两栏那一行必须锁成容器高（`minmax(0,1fr)`）；否则右栏越长地图越高。
2. **尺寸跟随交给 SDK。** 建图时调一次 `map.resize()`（GL 源码即 `this._watchSize()`）即可，
   **不要**再自建 `ResizeObserver` 做双份订阅。⚠ 厂商 API 的存在性只认厂商运行时：
   社区类型包 `@types/bmapgl` 里没有 `resize`，而 v1.0 的 `Map.prototype` 上确实有——
   凭类型包判"不存在"曾让我们撤掉一条真修复。
3. **图例浮层的 `z-10` 不是装饰。** 百度 GL 往容器注入 `.BMap_mask`（`z-index:9; pointer-events:auto`），
   压在它上面的浮层点不动；真机实测过 `elementFromPoint` 返回的是 mask。

新增同类"地图 + 侧栏"页时：套 `LcStage`，**并先给自己采一份结构基线**
（手法见 `__tests__/lcStageStructure.test.tsx` 文件头——它把"有没有多包一层"变成树形等式，
因为 jsdom 没有排版引擎、`lg:h-full` 这类百分比高度按父层解析，改层级在像素层不可验证）。

**为什么这类改动必须有成文的验证边界**：jsdom 不排版，而内置浏览器面板可能整页不出帧
（实测 `requestAnimationFrame` 3.6 秒 0 帧），此时"画布没跟随容器变高"这类观察
**既不能证实也不能证伪**。凡此均记在未验清单上（见 `生活圈-体检台布局落地计划-B-v1.md` §2.2），
不得拿单元全绿冒充已验。

---

## 11. 专家团与域包

48 位虚拟专家分三层（L3 决策 3 / L2 策略 9 / L1 执行 36），分层、角色与消息协议见
[AGENTS.md](./AGENTS.md)。两个域各有一份名册（`app/data/experts.json` 与
`experts_living_circle.json`），**同构、共用同一 48 id 空间**：id 是职能槽位，人设是域包内容，
所以同 id 在不同域可以是不同人设。

组队按域独立实现：目的地调研由编排引擎自动组队；生活圈由 `pipeline/lc_team.py` 从名册中
按需挑选 8–13 人（替代早先硬编码的固定名单）。口径绑定挂在**职能槽位**上而非人设上，
这样换一个领域只需换名册与绑定，不必改核心代码。

---

## 12. 测试与守卫（结构约束的机器化）

本仓的架构约束不靠文档约定，靠三类可执行守卫：

| 层 | 位置 | 守什么 |
|---|---|---|
| γ 静态守卫 | `backend/scripts/check_guard_construction.py`（AST，非正则） | 治理闸不得被绕过、断言不得读挂钟、`from_iso` 唯一出口、流水线 import 方向 |
| 等价类套件 | `backend/tests/test_guard_construction_lint.py` | 上述每条规则「违规必红 + 合法必绿」 |
| 元守卫自证 | `backend/tests/test_guard_selfvalidation.py`、`tests/test_api_mirror_guard.py`、`tests/test_semantic_residue.py` | **守卫在比对对象消失时必须报错或显式 SKIP，不得静默报绿** |
| 几何/像素层 | `frontend/e2e/*.spec.ts`（Playwright，两档视口 1440×900 与 1280×720） | jsdom 无排版引擎 ⇒ "真的不滚、真的常驻、容器变了画布真的跟"只能在真浏览器里钉。判据须由**变异测试**证明非空判（把产品改坏看它红），且**要看报错文本**——验法自身的副作用（改 `index.html` 触发 dev server 重启）会伪装成功能红 |

外加词表闸（`test_expert_caliber_refs.py`）、注册表单一真相源（`test_registry_single_source.py`）、
前后端夹具契约（`test_fixture_mirror.py`）、前端样式与色 token 完整性
（`tailwindClassIntegrity.test.ts`、`bmapStyle.test.tsx`、`roadContrast.test.ts`）。
`tailwindClassIntegrity.test.ts` 是**两段**判据：① 源码里的 Tailwind 颜色工具类必须来自调色板；
② 被消费的 CSS 自定义属性必须在 `index.css` 有定义 —— 扫描同时覆盖 `var(--x)` 与
`v('--c-x')` 这类"把令牌名当字符串传"的调用点，因为悬空 `var()` 与悬空工具类是**同一种**
静默失效（不报错、只掉色）。

判别力机器：`backend/scripts/mutation_check.py` —— 往生产代码注入变异，断言目标用例**转红**，
再按 sha256 校验还原。全绿只说明"当前代码让测试满意"，不说明"测试真的在检查东西"。

棘轮（ratchet）是本仓处理"存量债 + 不许再涨"的统一手法：把债**逐文件**记进一份账本
（`frontend/src/__tests__/fixtures/lintRatchetBaseline.json`、`tailwindClassIntegrity.test.ts` 的
`KNOWN_PROBE_DANGLING`），判据两个方向都红 —— 超线是新增违规，低于线要求**同笔把账本改小**。
只记总数会被"修 A 两条、B 新加两条"互相抵消糊过去，所以必须逐文件。
配套的一条 CI 规则：**诊断步与阻断步分开**。`npm run lint` 有 106 条存量 error（2026-10-04 干净
clone 实测），若让它阻断，`frontend` job 后面的 vitest 与 build 一行都不跑；现在它是
`continue-on-error: true` 的诊断，阻断权在 vitest 里的棘轮（`lintRatchet.test.ts`）。
判据只统计 `git ls-files` 认得的路径 —— 工作区里的在制品不算这条分支的债，也不该由别人替你改。

CI 侧有一条与守卫等价的**结构约束**：`.github/workflows/ci.yml` 里几何层是**独立 job**（`e2e`），
不并进 `frontend` job。原因是 step 按序终止 —— `frontend` 在 `lint` 步就长期红（HEAD 全仓 113 个
eslint error），并进去的防线**永远轮不到执行**，形式上"有"、实际上一行没跑。由此推出本仓通用的
一条纪律：**新防线不得排在已知长期红的步骤之后**，要么独立成 job，要么先把那道红治理成棘轮
（同 `tailwindClassIntegrity.test.ts` 的 `KNOWN_PROBE_DANGLING` 只减不增手法）。
另记：CI 无后端 ⇒ 地图取不到浏览器 AK 走降级分支，`画布跟随容器变高` 那条会**显式 SKIP** ——
所以"CI 绿"不代表 live BMapGL 的 resize 被看守过；同理 `npm run typecheck` 也把 `e2e/` 纳入
（`tsconfig.app.json` 的 include），新增 e2e 文件只跑浏览器不跑 tsc 会漏掉类型红。

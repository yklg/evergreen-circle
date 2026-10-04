# 生活圈体检台 · 布局落地计划 B-v1（右栏独立滚动方案）

选型来源：`preview-lc-layout-variants.html` 第 ③ 屏（方案 B），用户 2026-10-04 选定。
本文件是执行台账，**不是一次性写完再动工**：第 1 节已落码，第 2 节起为待办。

---

## 0. 选型依据（预览实测数字，1440×900 强制排版）

| 屏 | 地图框高 | 图例高 | 滚到底图例是否可见 | KPI |
|---|---|---|---|---|
| ① 现状 | **1627px**（= 右栏 1627px，坐实 `align-items:stretch` 传导） | 554px 浮层 | ❌ 偏移 −738px | 9 条行式 |
| ② A′ 定高+卡头图例 | 647px | 85px 卡头 | ❌ −750px（定高≠常驻） | 行式 |
| **③ B（已选）** | **800px（页不滚，右栏内滚 1351>800）** | 554px 浮层 + 收起 | ✅ 偏移恒 89px | 9 tile + 折叠 |
| ④ C 粘性 | 560px sticky | 554px 浮层 | ✅ 停在 29px | 9 tile + 折叠 |
| ⑤ A′+C | 647px sticky | 85px 卡头 | ✅ 停在 17px | 9 tile + 折叠 |

两条被实测改写的认识（同步进 `.qoder-cn/plans/rosy-cave-stag.md`）：

1. **A′ 单独用不满足需求 1** —— 定高把地图从 1627 压到 647，但整页仍滚，图例连卡头一起出屏。
2. **sticky 没被 overflow 废掉** —— 规划阶段依 CSS-Tricks 推断「`<main> overflow-y:auto` 会静默废掉粘性」，实测不成立；真正废掉它的是缺 `align-self:start`（格子被撑满即无可粘余量）。⑤ 因此是观感最优候选，本轮不采纳，留作 A/B 备选。

B 的**已接受代价**：必须给 `LcMap` 补一条仓库里原本不存在的 resize 通道（见 1.2）。

---

## 1. 已落码（4 文件，未提交）

### 1.1 `frontend/src/pages/LifeCirclePage.tsx`
- 页根 `:475`：`min-h-full` → 追加 `lg:h-full lg:min-h-0 lg:overflow-hidden`。**只在大屏接管滚动**，`<lg` 单栏维持原整页滚（本轮按约定不管小屏）。
- 两栏 `:673`：追加 `lg:min-h-0 lg:grid-rows-[minmax(0,1fr)]`。
  ⚠ 比预览多加的一条：预览靠 `.mapcell{height:100%} + .aside{height:100%}` 成立，但 auto 行仍可能被内容撑高；`grid-rows-[minmax(0,1fr)]` 把行高锁成「恰好等于容器」，杜绝右栏内容反向决定地图高度。
- 地图格 `:675`：追加 `lg:h-full lg:min-h-0`（`min-h-[480px]` 只在小屏生效）。
- 右栏 `:807`：追加 `lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-1`。
- 图例 `:701`：新增「收起/展开」按钮 + `legendOpen` 状态，**默认展开**。
  折叠用条件渲染（整块 body 出 DOM）。默认展开是硬约束：`judgeScaleToggle.test.tsx:107` 走 `getByRole('checkbox', { name: /判定尺/ })`，RTL 默认排除不可见元素 —— 出厂折叠会把该用例直接判红。
- 读数面：新增 `StatTile`（`rounded-btn border border-line bg-bg p-2.5` + 12px 半值），把 **POI 采集 / 采样点 / 15min 等时圈面积 / 服务盲区** 四条与 **测算口径五条** 共 9 条行式读数改成 `grid grid-cols-2 gap-2`。
  - label 与 value 文本**逐字未改**（`poiMetricLabel` 等出口不碰），只是不再一行一条 ⇒ 文本型断言不受影响。
  - `15min 等时圈面积` 保留完整 label（预览里我缩写成了「15min 等时圈」，以生产文本为准）。
  - `highlight`（悬停地图 15min 圈联动高亮）随迁到 tile，C8 行为不变。
  - 原 `StatRow` 已删（本文件内无剩余消费方；`LifeCircleReportView.tsx:205` 与 `dev/lcP5Probe.tsx:145` 各有自己的同名私有实现，互不依赖）。
- 台账卡调用点 `:946`：加 `foldable`。
- 盲区清单 `:955`：新增 `BLIND_TOP_N = 3` + `blindShowAll` 状态；超过 3 条才出「查看全部 N 处 / 只看前 3 处」按钮。
  现名册三份快照的盲区数是 kaili 0 / kaili-ev2 1 / beijing-jinsong 0 ⇒ 默认不会截断任何一份，`recordRowDisclosure.test.tsx` 的「盲区 2 处」是注入态且落在 3 以内。

### 1.2 `LcMap.tsx` + `lib/bmap.ts` —— 结论翻过三次，最终态：**建图时调一次 `map.resize()`，不自建 ResizeObserver**

这条链的判定过程本身就是本轮最需要留下的记录，三次状态：

1. **v1（直觉）**：加了 `ResizeObserver → map.resize?.()`。没核验 SDK 有没有这个方法就落码 —— 错。
2. **v2（半吊子核验，结论是错的）**：查社区类型包 `@types/bmapgl@0.0.7` 的 `Map` 面，里面没有 `resize` ⇒ 我据此判定"假通道"并整体撤除。**取证方法错了**：社区类型包是子集，不能拿来**否证**厂商 API。
3. **v3（现场直查真 SDK）**：在本仓实际加载的 `type=webgl&v=1.0`（`lib/bmap.ts:303`）上直查 `window.BMapGL.Map.prototype` —— 244 个方法，`resize` / `checkResize` / `enableAutoResize` / `disableAutoResize` **都是 function**，`willResize` 不存在；且 `resize` 源码是
   `function(){ if(!apiVersionIsGL()){console.warn("[BMap] resize is only for GL version, use checkResize instead")} this._watchSize() }`
   ⇒ 它的语义不是"手动重画一帧"，而是**打开 SDK 自己的尺寸监听**。

**最终落码**：`LcMap` 建图后立刻 `map.resize()`（一次即可），**不自建 ResizeObserver** —— 否则等于双份监听，还得自己管卸载。`lib/bmap.ts` 的 `BMapMap` 声明 `resize(): void`（非可选，附来源注释），`bmapGLFake` 的替身做成**记账版**（空桩会让这条链在测试里免疫）。`__tests__/lcMapResizeGuard.test.tsx`(3 例) 钉住：接口有声明 + 加载的是 GL 版、live 建图 `resize` 恰调一次、源码不得再出现 `new ResizeObserver`（并附正对照）。

**仍未证的一条（诚实标注，别当成已验）**：「容器变高后画布是否真的跟随」。现场实验做过两次（撤除态与调用态），画布都停在 478px 不动 —— 但**两次都在 `visibilityState=hidden` 的标签页里做**，SDK 的尺寸监听挂在渲染步上，隐藏页里 RO/rAF 会被抑制 ⇒ 这个结果**不能作数**，既不能证伪也不能证实。要结案必须让页面真正可见（打开浏览器面板或真机），看 `host` 改高后 `canvas` 尺寸是否跟随。

**方法论收获（值得进 `docs/AGENTS.md`）**：① 厂商 API 的存在性只认厂商运行时，社区类型包只能作正面证据、不能作否证；② 渲染相关实验不能在 hidden 页里下结论。

### 1.3 `CellsLedgerCard.tsx`
- 新增 `foldable?: boolean`。拆出 `head` / `body` 两个 JSX 变量：`foldable` 走 `<details><summary>{head}</summary>{body}</details>`（出厂折上），否则维持原 `<div class="…p-4">` 面 ⇒ 报告页/探针等既有消费方零像素变化。
- 折叠不改 DOM 存在性：`rect[data-cell]` 仍在，`judgeScaleToggle.test.tsx` 的 `n²` 格数判据不会因折叠空过。

### 1.4 已跑的校验
- `npx tsc --noEmit -p tsconfig.app.json`：**8 条错误，0 条落在本轮 4 个文件**。全部来自你未提交的 WIP：`src/__tests__/eventFlowNumbersMatchFixture.test.ts`（`team`/`facility_merge`/`spec`/`cells_blind` 等字段未进 `types.ts`）与 `src/dev/lcHitSurfaceProbe.tsx:194-195`。⇒ **`npm run typecheck` 基线就是红的**，属你那条在飞的同源测试，本轮不动它。
- `npx eslint` 4 文件：1 error + 2 warning，均在**未改动的位置**（`LcMap.tsx:114` react-refresh、`LcMap.tsx:1175` 冗余 disable、`LifeCirclePage.tsx:214` flowCallbacks 依赖），非本轮引入。

---

## 1.5 架构评审结论（architecture-first-fix · 判定：**需返工**）

三条硬标尺：**根因层级 = 部分通过**（只触达单页布局，未触达「尺寸/滚动所有权」与「图例、读数面单一实现」这三处跨页契约）；**非遮盖 = 有一处假修复风险**（`resize` 未核验 + 三层可选调用 + 测试内零执行 ⇒ 可能空转）；**不引入耦合 + 提升性 = 不通过**（`StatTile` 成第 4 份读数实现；图例仍两处不同形态；滚动契约靠每页各写 `lg:` class）。

**评审挖出的 P0（本文件初稿没看见的真根因）**：页面根改 `lg:h-full lg:overflow-hidden` 之后，页面上方那块**内容驱动、条数无界**的实时横幅区（`:639-672` 的 `roundLines.map`，每轮取证追加一行，无 `max-h` 无内部滚动）与 `.split{flex-1 min-h-0}` 抢同一定高容器。flex 项默认 `min-height:auto` 不收缩 ⇒ 横幅越长，地图 + 右栏被压向 0 高，而 `overflow-hidden` 让整页**没有滚动可逃**。
真实触发路径是**真实模式跑一次体检**（fixture 态不显这块），所以预览第 ③ 屏根本没覆盖到它 —— 这是「预览与真实改动不一致」的实例。
⇒ 结构解：页面分三层并显式声明各层对高度的主张（`header` `shrink-0` / `notice` 有界且内部滚 / `stage` `flex-1 min-h-0`），而不是让"除了右栏都定高"成为巧合假设。

**架构级建议（超出本轮授权，需另批确认）**

| # | 建议 | 消掉的是哪条根因 |
|---|---|---|
| A | 新增 `components/lifecircle/LcStage.tsx`：面板件自持 `h-full min-h-0 overflow-hidden` + `head/legend/body` 插槽，右槽内部滚由它保证 | 尺寸/滚动所有权无主人；顺带让 2.3「镜像页不能照搬」自动消失 |
| B | 图例收归地图层（`LcLegend`）：`z-index > .BMap_mask` 与折叠态自持，**折叠=视觉收起、不销毁可交互控件** | 图例两处不同实现；避免 `:695-700` 那条 z-index 教训换个方向复发 |
| C | `StatTile` 并进 `ui/index.tsx` 的 `VStatCard` 作第四面（`tileCompact`），并迁移 `LifeCircleReportView.tsx:205` / `dev/lcP5Probe.tsx:145`；守卫判据从「禁 `font-serif text-[26\|32]px` 指纹」升级为「标签+值形状仅一处实现」 | `statCardSingleSource.test.ts` 被绕的是指纹不是职责，「调一档字号改四处」原封不动 |
| D | resize 通道先核验后留：真 AK 下 `typeof map.resize`；存在则 `bmap.ts` 改**必选**，给 `bmapGLFake.ts` 加 `resize` 记录，stub `ResizeObserver` 补一条「容器变高 ⇒ resize 被调一次」的测试 | 三层可选 = 用未证实的 SDK 能力换布局收益 |
| E | `docs/ARCHITECTURE.md` 增「页面滚动所有权」一节（整页滚 vs 面板内滚的适用条件与实现契约），并记入本轮实测：粘性需配 `align-self:start` 才有余量、`<main> overflow-y:auto` 不废粘性 | 三套滚动模型并存无约定；外部推断顶替自家真机证据 |
| F | `BLIND_TOP_N` 删除或补契约：三份真实快照盲区数是 0/1/0 ⇒ 现方案为不存在的场景加复杂度；若保留，须断言「完整计数与截断状态同屏」 | 防重演「0 处盲区被读成全圈没问题」 |

**若 D 核验不通过**：架构上退回第 ⑤ 屏（定高 + 粘性 + 卡头图例）更优 —— 纯 CSS 达到同样的常驻收益、零新增第三方能力依赖。这会推翻本轮选型，需用户再拍一次。

---

## 1.6 三维架构评审结论（tech-solution-review · 判定：**有条件落地**，P0×3）

**实测证据**：`npx vitest run` 全量 **115 文件全绿 / 1005 例**；定向 9 个最 exposed 文件 55 例全绿（`lifeCirclePage` / `judgeScaleToggle` / `cellsLedgerCard` / `lcMapCellClick` / `lifeCircleReportView` / `statCardSingleSource` / `tailwindClassIntegrity` / `bmap` / `visitorUnrated`）。
**但这条绿不提供本次改动的核心证据**：jsdom 不排版、无 `ResizeObserver` ⇒ 「整页不滚 / 右栏内滚 / 图例常驻 / 容器变高重绘」四条主张**全部落在测试能力之外**，目前仅由预览件在强制 1440×900 下量过一次，真实页面未验。

### 可扩展空间（生长性）——弱项两条

| 可扩展点 | 现状 | 代价 |
|---|---|---|
| 新增「地图+面板」页 | ❌ 需重抄 4 组 `lg:` class | 同类症状会在任何新面板页重演 |
| 调读数字号/密度 | ❌ StatTile + `LifeCircleReportView:205` + `lcP5Probe:145` + `VStatCard` 四面并存 | 「调一档改四处」原封不动 |
| 图例新增图层 | 部分（色单源 ✅，渲染面两处） | 两处各改一次 |
| 地图高度策略切换 | ❌ 被 `resize` SDK 能力锁死 | 改回定高要删整条 effect |
| 数据契约 | ✅ 未动 `LivingCircleReport` | — |

### 健壮性风险清单

| # | 严重度 | 位置 | 风险 | 触发场景 |
|---|---|---|---|---|
| R1 | **高** | `LifeCirclePage.tsx:639-672` + `:480` | 无界横幅与 `flex-1 min-h-0` 的 `.split` 抢定高容器；flex 项默认不收缩 ⇒ 地图/右栏压向 0 高且 `overflow-hidden` 无滚动可逃 | 真实模式跑体检（`roundLines` 每轮追加）；或 1280×720 叠多条横幅 |
| R2 | **高** | `lib/bmap.ts:303`（v1.0）+ `LcMap.tsx:516-525` | `Map.resize()` 存在性未核验；三层可选 ⇒ 最坏**静默空转**：真机不重绘/灰边而代码看似已修 | 窗口变高、或 R1 引起的高度中途变化 |
| R3 | 中 | `LcMap.tsx:516-525` | `observe()` 立即以初始尺寸回调一次，与 `:1009-1013` 的 `setViewport`/`centerAndZoom` 竞态；`ComparePage` 定高容器白捡一次 `resize()` | 首屏建图 |
| R4 | 中 | `LifeCirclePage.tsx:722-724` | 折叠用条件渲染 ⇒ 判定尺/证据域勾选一起出 DOM，`:695-700`「假入口」纪律反向复发 | 用户收起后用勾选 |
| R5 | 中 | 测试层 | 115 全绿对本次核心主张零证明力 | 提交/演示前 |
| R6 | 低 | `:92,986` `BLIND_TOP_N=3` | 真实快照 0/1/0 ⇒ 为不存在的场景加复杂度 | 未来高密度盲区样区 |
| R7 | 低 | typecheck 基线 | 8 条错误来自你未提交的 WIP，CI 现红（非本轮引入，但会掩盖本轮回归） | 每次 CI |

### 跨模块回归影响

| 受影响模块 | 类型 | 概率 | 严重度 | 说明 |
|---|---|---|---|---|
| `ComparePage.tsx:341,356`（共用 `LcMap`） | 行为契约 | 高 | 中 | RO 一并生效，多一次初始 `resize()` |
| `LifeCircleReportView.tsx:525,530`（`ReportPage` 内） | 行为契约 | 高 | 中 | 吃到 RO 却拿不到布局收益；它在 `ReportPage.tsx:415-417` 自有滚动模型里 ⇒ 2.3 同步范围必须收窄 |
| `AppLayout.tsx:6` 其它路由页 | 无 | — | 低 | 未动外层容器，`lg:` 只作用本页子树 |
| `__tests__` 115 文件 | 测试 | — | 低 | 实测全绿（守卫各自按预期放行） |
| `docs/ARCHITECTURE.md` | 文档契约 | 高 | 中 | 三套滚动模型无约定，本轮又加第四种 |
| `skip/preview-lc-layout-variants.html` | 一致性 | 高 | 中 | 预览缺可无界增长的横幅区 ⇒ ③ 屏结论对真实模式不成立 |

### 优化 / 规避建议（分级 + 成本）

| # | 优先级 | 问题 | 最小改动路径 | 成本 | 需补测试 |
|---|---|---|---|---|---|
| S1 | **P0** | R1 挤压 | 页根分三层显式定约：`header shrink-0` / `notice max-h-[22vh] overflow-y-auto` / `stage flex-1 min-h-0`。**禁止**用去掉 `overflow-hidden` 糊过去（会退回原 bug） | 低-中 | 真机 1280×720 + 5 行 roundLines |
| S2 | **P0** | R2 未核验 | 真 AK 控制台 `typeof map.resize`。不存在 ⇒ 撤第 2 笔、选型改回 ⑤（定高+粘性+卡头，纯 CSS 零新依赖）；存在 ⇒ `bmap.ts` 改必选 + `bmapGLFake` 记 `resize` | 低 | stub `ResizeObserver` 断言调一次 |
| S3 | **P1** | R4 销毁控件 | 折叠改「视觉收起」：色块可隐藏，两个勾选留 DOM（配 `aria-expanded`） | 低 | 折叠态 `getByRole('checkbox')` 仍可达 |
| S4 | **P1** | 三页各写一套 | 抽 `LcStage`（§1.5-A） | 中 | 组件契约测试 + 源码守卫 |
| S5 | **P1** | 第 4 份读数面 | StatTile 并入 `VStatCard` 新面 `tileCompact`，迁 `LifeCircleReportView:205`/`lcP5Probe:145`，守卫判据升级为「形状唯一实现」（§1.5-C） | 中 | 守卫扩一条 |
| S6 | P2 | R3 时序 | RO 回调内比较尺寸确有变化再调 `resize()` | 低 | 同 S2 |
| S7 | P2 | R6 空转复杂度 | 删 `BLIND_TOP_N`，或断言完整计数常驻 | 低 | 可选 |
| S8 | P2 | 文档缺契约 | `docs/ARCHITECTURE.md` 补「页面滚动所有权」，记入本轮实测两条 | 低 | — |

### 结论与前置条件

- **可落地范围**：第 1 笔（布局 + 图例折叠 + tile + Top-N + `foldable`）补完 S1 后可落；**第 2 笔（RO + `resize` 类型）在 S2 核验前不落**。
- **前置条件**：①真机验四条主张；②真实模式 5 行 `roundLines` + 1280×720 不塌；③`resize` 通道有测试或被证实存在；④两笔分开提交（§3 回滚点）。
- **P0**：R1 / R2 / R5（对应 S1、S2、及补测）。
- **补充建议**：引入一次性真机截图基线（或最小 Playwright 用例守「地图高度 == 视口高度」），否则排版类改动每次都是「测试全绿但没人知道对不对」。

### 结论的执行状态（2026-10-04）

| 项 | 状态 |
|---|---|
| R1 / S1 无界横幅压塌 stage | ✅ **已修**：`LifeCirclePage.tsx:648` 那列加 `lg:max-h-[22vh] lg:overflow-y-auto`（界加在会增长的那一列，左图标与进度条留在原位）；TC-11 由红钉转普通 `it` |
| R2 / S2 `resize()` 存在性 | ✅ **已核验：存在**。现场直查 `window.BMapGL.Map.prototype`（v1.0）：`resize`/`checkResize`/`enableAutoResize` 均为 function，`resize` 源码 = `this._watchSize()`。⚠ 中途我曾凭社区类型包判它"不存在"并撤除 —— 那是**取证方法错误**，详见 §1.2 的三次翻案 |
| R3 RO 与建图竞态 | ✅ **消失**（不是"随撤除消失"，而是换了解法）：监听交给 SDK 的 `_watchSize()`，我们不再持有观察器，也就不存在"我们的 RO 首帧回调 vs `centerAndZoom` 先后"这个问题 |
| R5 主张无证据 | 部分：净增 17 例把「有没有调、有没有重复订阅」钉住了；**「容器变高后画布是否跟随」仍未证** —— 两次现场实验都发生在 `visibilityState=hidden` 的标签页里，渲染步被抑制，结果不能作数（既不能证实也不能证伪）。B 的观感主张同样需要一次可见页验证 |
| R4 / S3 折叠销毁判读控件 | ✅ **已修**：折叠只收色块段（`{legendOpen && …}` 的范围缩到补点处方那行为止），证据域 / 判定尺两个勾选**常在**，按钮加 `aria-expanded`。TC-05 由 `it.fails` 转正并扩成「折叠→勾选仍可点且状态不被洗掉→再展开色块回来」 |
| 2.3 镜像页勘察 | `LifeCircleReportView.tsx:529` 那份图例是**纯色块、无勾选**，且该页**不使用** `CellsLedgerCard` ⇒ S3 / foldable 无处可同步。剩下的只有读数面，而照搬 tile 会造出第 4 份实现（正是 S5 要收的债）⇒ **建议与 S5 合并做**，不在本轮单挑 |
| S4 / S5 / S8（`LcStage`、读数面收敛、文档契约） | ❌ 未做，跨页结构改动，等确认 |

---

## 1.7 第一批 P0 测试已落地（2026-10-04 执行）

覆盖评估文档的第一批全部生成并跑绿，**未改任何生产源码**：

| 新文件 / 改动 | 内容 |
|---|---|
| `src/__tests__/helpers/resizeObserverStub.ts`（新） | 可手动触发的 RO 替身：`observe` 记账、`fireResize(el)` 由测试决定何时回调、`roStats.created` 供反向判据、`resetResizeObservers()` 防串台。语义与旧 no-op 桩一致（不自动回调），所以 `VWordCloud` 等既有消费方不受影响 |
| `vitest.setup.ts`（改） | 把原先的局部 no-op 桩换成上面那份共享替身（沿用本文件既有的 localStorage 补水先例：环境缺口在测试边界补，不动生产码） |
| `src/__tests__/helpers/bmapGLFake.ts`（改） | 加**记账版** `resize()`（真 SDK 源码 = `this._watchSize()`）。空桩会让「容器变高画布不重绘」这类回归免疫 —— 本文件开档写过的教训，中途我还真差点把它当成"假通道"删掉 |
| `src/__tests__/lcMapResizeGuard.test.tsx`（新，3 例） | 最终态守卫（文件头完整记了三次翻案）：正对照「`bmap.ts` 声明 `resize(): void` 且加载 `type=webgl`」、live 建图 ⇒ `resize` **恰调一次**、源码不得再出现 `new ResizeObserver` 且 `roStats.created === 0`（防有人手搓双份监听） |
| `src/__tests__/lcLedgerFoldable.test.tsx`（新，4 例） | TC-16 `foldable` 两态：出厂折上但 `rect[data-cell]` 仍 == n²（折叠≠卸载，否则 `judgeScaleToggle` 的格数判据会静默空过）；点 summary 展开后读数链通；未传 `foldable` 的消费方形状串逐字不变（TC-17 的一半） |
| `src/__tests__/lcLayoutContract.test.tsx`（新，10 例） | TC-18 四组布局 utility + 图例 `z-10` **各出现恰一次**（0 次=漂移，2 次=有人复制了滚动契约），含「正对照」防空过；TC-12 九条读数 + 三要素 chips + 判定尺句 **逐字等于** `poiMetricLabel` 等生产函数输出（ev-2 真跑件与 kaili 冻结件都跑）；TC-11 已由红钉转普通 `it`（S1 落地），**TC-05 也已转正**（S3 落地：折叠只收色块、勾选常在 + `aria-expanded`）|

**实测**：全量 `npx vitest run` **118 文件 / 1022 通过 + 1 todo**（起点 115 / 1005 ⇒ 净增 3 文件 17 例，无回归）；`tsc` 错误数 = 基线 **8**（全部来自你未提交的 WIP，本轮新文件 0 错）；`eslint` 对本轮新增/改动文件 **0 error**。

**红钉 ≠ 已修**：S1（压塌 stage）本轮已真修；TC-05 只是把 S3（折叠销毁判读控件）钉成可见事实，缺陷本身还在。

---

## 1.8 第二轮落实：S5 收敛 + S4 第一步 + 未证项的环境结论（2026-10-04）

### S5 · 读数面收敛（已完成，并当场多收一份）

「标签 + 文本值」这一形状原本散落 **5 份**：`LifeCirclePage` 的 `StatTile`（本轮上一批引入）、
`LifeCircleReportView.tsx:205` 与 `dev/lcP5Probe.tsx:145` 各一份私有 `StatRow`、
**外加 `ComparePage.tsx:323` 直接内联在 `.map()` 里的一份** —— 这第 5 份是新闸门首次运行抓出来的
（内联实现没有函数名，靠读代码数不清，正是"没有结构性防线"的样子）。

- 单一实现：`components/ui/index.tsx` 新增 **`VStatLine`**，两面 `row`（原行式，逐字沿用旧 class 串）/
  `tile`（原体检台紧凑面，逐字沿用）⇒ **五处消费点换件而不改像素**。
- 为什么不是塞进 `VStatCard` 的第五个 surface：那三面是**大数字面**（`font-serif text-[26|32]px`、
  `value: number`），这里要放的是字符串读数（`采集 194 · 圈内 108 · 已展示 108`），
  硬并要改共享件契约、连累既有消费方。两种形状各留一处单一实现。
- 新闸门 `__tests__/statLineSingleSource.test.ts`(3 例)：扫 `src/**`（排除 `__tests__`），
  任一面指纹出现在 `ui/index.tsx` 之外即红。**独立成文件**而不是扩 `statCardSingleSource` 的判据 ——
  那条守卫自己文件头写明"别把这条守卫偷偷扩成全能闸"，尊重它声明的边界。

### S4 · 只做第一步：契约有单一来源，不碰 DOM 层级

新增 `components/lifecircle/stageContract.ts`，把五组 utility（页根 / 两栏 / 地图格 / 右栏 / 图例）
收成命名常量 + 成文规矩（为什么 `z-10`、为什么只在大屏接管、为什么 `minmax(0,1fr)`）。页面全部改为消费常量。
TC-18 随之改为：五组串只在契约文件里各恰一次、页面必须引用常量且**不得内联副本**；
判据故意自带字面量副本（若 import 常量，"契约被改"就永远不会让这条红）。

**完整抽件（包一层 `LcStage`）本轮不做，且是有意的**：`lg:h-full` / `min-h-0` 这类百分比高度按**父层**解析，
包一层就改解析结果；而当前环境渲染步停摆（见下），改完无法验证。等能在真浏览器量尺寸时再做。

### 未证项的环境结论（从"没测到"升级为"知道为什么测不到"）

面板一度 `visible`（531×593），但进入实验又转 `hidden`；关键测量：**3.6 秒里 `requestAnimationFrame`
0 帧**。⇒ 这个标签页根本不产生渲染步，SDK 的尺寸监听（挂在渲染步上）不可能被触发，
"画布没跟随"从此**可证明是环境产物**，既不能证实也不能证伪这条主张。
结案只剩两条真路子：① 在正常窗口打开 `http://localhost:5199/life-circle/kaili-ev2`，拉窗口高度看有没有灰边（30 秒）；
② 批准引入 Playwright，把它钉成自动回归（我没擅自装依赖）。

### 本轮实测

全量 `npx vitest run` **119 文件 / 1025 通过 + 1 todo**；`tsc` = 基线 **8**（仍全在你 WIP，本轮文件 0 错）；
`eslint` 逐个文件：本轮 8 个文件里 7 个 **0 error**，`dev/lcP5Probe.tsx` 12 条（HEAD 上是 14 条，只减不增，既存债）。

---

## 1.9 S4 完整抽件已落（LcStage），靠结构基线而不是靠眼睛（2026-10-04）

2.4b 的阻塞理由是"看不见，改几何等于闭眼"。这个前提被**换掉了**：像素量不了，
但 jsdom 拿得到**树**，而"抽件会不会多包一层"恰恰是个纯树形问题。于是先采基线再重构。

- **新件** `components/lifecircle/LcStage.tsx`：复合组件 `<LcStage>` / `.Canvas` / `.Legend` / `.Panel`，
  类名全部取自 `stageContract.ts`。**刻意不用 props API** —— 那要把页面里几百行 JSX 抽出来重传，
  一次纯机械的大搬迁；换标签写法则子节点原地不动，而组件本身不产生 DOM 节点 ⇒ 树形逐字不变。
- **基线** `__tests__/fixtures/lcStageStructure.json`（45 个节点，depth ≤3）+
  `__tests__/lcStageStructure.test.tsx`(2 例)：记「从 `main`（AppLayout 滚动容器）到两栏容器的祖先链」
  + 两栏子树，逐节点比对 tag / 完整 class / 关键 aria 属性。祖先链就是百分比高度的解析上下文，
  **包一层立刻红**。
- 采集条件：fixture 态、`kaili-ev2`、外套一层与 `AppLayout.tsx:6-9` 同构的滚动外壳。
  连跑三遍确认可复现后才动结构。

### 采集踩了两次坑，都值得记（否则基线就是假的）

1. **就绪门用"或"不稳定**：`LcMap` 是异步的 —— `boot` 态渲染 live 容器（带 `data-lc-map`），
   拿不到 AK 后**改渲染降级 SVG 画布**，`data-lc-map` 消失。第一版门写作
   「有容器 或 有画布」，早一秒晚一秒取到的是两棵不同的树 ⇒ 同一份代码采的基线比不过。
   现在只认**已落定的降级画布**，并显式断言 `[data-lc-map]` 不在。
2. **基线太薄等于没守**：depth 2 只有 13 个节点，比"半棵树"还容易漏判。加深到 3 层（45 节点），
   并让正对照断言在节点数 < 40 时直接红（阈值写的是意图：三层=两栏→槽→槽内首层）。

### 本轮实测

`npx vitest run` 全量 **120 文件 / 1027 通过 + 1 todo**（起点 119/1025）；结构护栏在重构前后都绿，
这是"没有多包一层"的**证据**而非断言。`tsc` = 基线 8；`LcStage.tsx` / `LifeCirclePage.tsx` /
两个测试文件 eslint **0 error**。

### 还没做的那一半（说清楚，别让"抽件完成"冒充全部）

只有体检台采用了 `LcStage`。`LifeCircleReportView`（`grid-cols-[1.6fr_1fr]` + 快照图例）与
`ComparePage`（两块定高小图 + `OverlayLegend`）结构不同，套用前**必须各自先采一份结构基线**，
否则拿体检台的基线去比对别的树，红了也不知道是谁的错。它们的像素表现也仍卡在 2.2（需要能出帧的环境）。
2.4b 因此改标为"体检台侧完成，跨页推广待各采基线"。

---

## 1.10 #12 落地：`card` 悬空类、裸 token 名守卫、架构文档一节（2026-10-04）

**真缺陷（不是洁癖）**：`ComparePage.tsx:333,346` 两块等时圈对比卡写的是 `className="card"`，
而 `card` 只是 `borderRadius`/`colors` 的 **token 名**，全仓没有任何 CSS 定义 `.card`
（`index.css` 只有 `.v-card`）⇒ Tailwind 一个字都不生成，这两块卡**一直没有卡面**（圆角/描边/底色/阴影）。
已改为与其它卡一致的 `rounded-card border border-line bg-card shadow-card`。

**为什么颜色守卫看不见它**：`tailwindClassIntegrity` 第一段只认带前缀的颜色类（`text-`/`bg-`/…），
裸 `card` 不在其形制内；第二段管 `var()`。⇒ 补**第三段守卫**：
- 名单是封闭集合（config 里 `colors/borderRadius/fontSize/boxShadow/maxWidth/fontFamily` 的键名），
  所以不会误报 `flex`/`grid`/`truncate` 这些原生工具类，也不会报 `rounded-card`/`bg-card/90`；
- 三条断言：① 名单与扫描面非空（防空转）；② 检测器认得出被修掉的 `card` 且**不被模板串里的
  数据值误报**（`` `…${ b.tone === 'info' ? … }` `` 里的 `'info'` 不是类名 —— 这条是探测器初版
  真实误报过的形状，写成了反面对照）；③ 发货码零命中；
- 范围取舍写明，不是免检：`__tests__` 不扫（守卫会扫到自己的探针串）；`src/dev/**` 的 3 处悬空类
  （`intelCenterProbe → chip`、`roadContrastProbe → card`、`lcHitSurfaceProbe → warn`）
  进 `KNOWN_PROBE_DANGLING` **点名且只许减少**——修它们要现写一串 utility，而探针页本轮没有可验环境，
  闭眼改样式正是这次反复踩的坑。其中一处还是用户未提交的 WIP。

**架构文档**：`docs/ARCHITECTURE.md` §10 新增「页面滚动所有权与舞台契约」——三种滚动模型各自的
适用面与写法、契约唯一真源 `stageContract.ts` + `LcStage`、三条硬规矩（高度不许由内容决定 /
尺寸跟随交给 SDK 且**厂商 API 只认厂商运行时** / `z-10` 的来由），并要求新页**先自采结构基线**。
末尾写明本轮反复出现的病根：**没有渲染步时，观察既不能证实也不能证伪，不得拿单元全绿冒充已验**。

**实测**：全量 **120 文件 / 1031 通过 + 1 todo**（起点 120/1027 ⇒ 守卫净增 4 例）；`tsc` = 基线 8；
`tailwindClassIntegrity.test.ts` 的 3 条 eslint error 在 HEAD 上就是 3 条（净增 0）。
⚠ 顺带发现既存事实：`npx eslint .` 全仓 **113 error**，即 lint 当前不构成 CI 闸门 —— 不属本轮范围，但值得单独决策。

---

## 1.11 排版层自动回归已建（Playwright），#10 结案（2026-10-04）

`playwright.config.ts` + `e2e/lifeCircleStage.spec.ts`（7 例 × 两档视口 = **14 例全绿**，Chromium 1.63）。
npm 脚本 `npm run test:e2e`；`webServer` 自起 vite（复用已开的 5199）；数据态用 `localStorage` 钉 fixture，不依赖后端。
`test-results/` 等产物已进 `.gitignore`；`tsconfig.app.json` 的 include 加了 `e2e` ⇒ `npm run typecheck` 现在也管它（e2e 0 错）。

### 主张逐条结案（量到的数，不是推的）

| 主张 | 1440×900 | 1280×720 | 结论 |
|---|---|---|---|
| ① 整页不滚 | `main` scroll 900 = client 900 | 720 = 720 | ✅ |
| ② 右栏内滚 | client 800 / scroll 1398，`scrollTop` 可到 598 | 620 / 1398 | ✅ |
| ③ 滚到底图例仍在视野 | 图例 89–613 全在 `main` 内，**真指针 click 勾得上判定尺** | 同样成立 | ✅ |
| ④ 地图格高由视口决定 | 798px（≪ 右栏 1398） | 620px | ✅ 原 bug（1627px）不复现 |
| ⑤ 折叠只收色块 | 勾选仍在原位且 `check()` 生效 | 同 | ✅ S3 的像素层补强 |
| 画布跟随容器变高 | host 798→320→798，canvas 同步 798→320→798 | 同（±1px 扰动亦自愈） | ✅ **BMapGL `resize()` = `_watchSize()` 确实工作** |

### 过程中两次"假信号"，都记下来（它们比绿灯更值钱）

1. **我自己的断言错了**：首版写 `expect(canvas).toBeCloseTo(host)`，在 1280×720 红出 48px 差。
   追下去不是产品缺陷 —— **CJK 字体约 700ms 落地交换**，表头从两行收回一行，地图格随之 572 → 620px；
   我在切换两侧各测了一次，跨在了那一跳上。改成"轮询到稳定后相等（容差 2px = 那一圈 1px 边框）"，
   并**另加一条落定后不再抖**的用例（1.5s 内高度差 ≤2px）——把瞬态从"意外"变成"被钉住的行为"。
2. **`toBeCloseTo(h, -1)` 是错的用法**（精度参数不是百分比），第一次跑没暴露是因为它恰好通过；
   换成显式 `Math.abs(a-b) <= 2` 才有可读的失败信息。

### 新开一条（真缺陷，未修）

**首屏字体交换造成 48px 布局跳动**（仅 ≤1280 一档出现；1440 那一行不换行所以无感）。
影响是打开瞬间地图格会"长一次"，观感是内容跳一下。可选解法：表头预留两行高（`min-h`）、
或让那几个场景 chip 不随字体宽度重排（固定 chip 宽度/缩短文案）、或字体 `size-adjust` 预对齐。
另记一条量测：1280×720 下图例展开态高 **524px**，占屏 73% —— 折叠口正是为此，
但"矮视口是否该默认折起"仍属未决（本轮约定不管小屏/矮视口）。

---

## 1.12 「进 / 修 / 可以」三件事的结案（CLS 修复 · 真实态收手 · e2e 进 CI）（2026-10-04）

§1.11 那条台账写的是 **7 例 × 2 档 = 14 例**；本轮之后是 **`lifeCircleStage` 8 例 × 2 档 = 16 例，另加 `lifeCircleRunning` 1 例 × 2 档（显式 fixme）**，套件总数 18 条。下面的数都是重跑过的。

### 修 · 首屏 48px 跳动：改成字体 `display=optional`，并用 CLS 把它钉住

- 落点：`frontend/index.html` 的 Google Fonts URL 由 `&display=swap` 改 `&display=optional`，注释里写明"别改回去"并指向回归网。
- 新增 e2e 用例「首屏零布局跳动（CLS）」：用 `context.addInitScript` 从第一个脚本起装
  `PerformanceObserver({type:'layout-shift', buffered:true})`，累计非输入的 shift 分数，阈值 **< 0.01**。
  这比"采两个时刻比高度"严 —— 它覆盖首屏**所有**来源的跳动，不只是我们已知的那一次。
- **变异测试验过这条守卫不是空判**：临时改回 `display=swap` ⇒ 1280×720 报
  「首屏 CLS = 0.4584，超过 0.01」并红；**1440×900 照绿**（那一行不换行，没有跳动可测）。
  由此把上一版写在注释里的估算"约 0.066"更正为实测 0.4584，并把"两档必须都跑"写进用例。
- §1.11「首屏落定后不再抖」保留不动 —— 它管的是"落定后还在动"，这条管"落定前跳过"，两者不互相冒充。

### 可以 · 真实态取证横幅那条（2.2c）：**收手并标 `fixme`，不留假绿也不留假红**

`frontend/e2e/lifeCircleRunning.spec.ts` 走通了 `page.route` 那半段：POST `/api/tasks`（响应必须是
camelCase **`taskId`** —— 用 `task_id` 会得到「创建体检任务失败（HTTP 200）」，这是本轮踩的实测坑）
+ 5 个 `round` 命名事件的 SSE 流 + catch-all `**/api/**` 注册在前。
但**横幅要求的是任务注册表进入 `running`**（`runActive` 不是"收到过 EventSource 事件"），
纯 mock 到不了那个状态。按项目既有纪律标成 `test.fixme`，原因与两条收口路径写在码里：
① CI 里起真后端；② 在 `lifeCircleFlow` 上开一个 registry 级注入口。
**S1 那条限高目前仍只有源码钉（TC-11）在守** —— 这条不伪称已像素级验证。

### 进 · e2e 接入 CI：`.github/workflows/ci.yml` 新增独立 `e2e` job

- **为什么是独立 job 而不是塞进 `frontend`**：那条 job 在 `lint` 步骤就已是红的（HEAD 全仓 113 个
  eslint error），step 按序终止 ⇒ 塞进去等于让排版防线**永远轮不到跑**。这条与"lint 是否该当闸门"
  是两件事，后者仍未决（见 §2 新行 2.9）。
- 步骤：checkout → setup-node 22（npm cache）→ `npm ci` → `npx playwright install --with-deps chromium`
  → `npm run test:e2e`（`webServer` 自起 vite:5199）→ **失败时**上传 `test-results/` + `playwright-report/`。
- **CI 条件已在本地复现过**（不是推断）：把 dev server 的 `VITE_PROXY_TARGET` 指向死端口模拟"无后端"，
  全套 **exit=0，14 passed / 4 skipped**。那 4 条 skip 的成分要点明：2 条是「画布跟随容器变高」
  在无 AK 时降级自跳、2 条是 `lifeCircleRunning` 的 fixme。
  ⇒ **CI 绿不等于 live BMapGL 的 resize 被看守过**；那条只在有 AK 的本地态跑（§1.11 实测已跑通）。
- 两份 YAML 用 `backend/.venv/bin/python` + pyyaml 解析校验通过；job 序 `backend / frontend / e2e / docker`。
- Gitee 侧 `.workflow/ci.yml` **有意不跟**并按它的约定在头部记明差异：那仍是惰性配置（无 Gitee 远端），
  且 `npmbuild@1` 镜像能否 `--with-deps` 装到 Chromium 系统库在这台机器上验证不了 ——
  不拿从没跑通的安装步骤冒充防线。

### 本轮我自己制造并当场抓到的两件事（不美化）

1. **新 CLS 用例把 `typecheck` 打破了**：首版写 `e.value`，而 `list.getEntries()` 的基面是
   `PerformanceEntry`（本档 lib.dom 不保证有 `LayoutShift`）⇒ `TS2339`。
   于是 §1.11 里那句「`tsconfig.app.json` 加了 `e2e` ⇒ typecheck 也管它，e2e 0 错」**在新用例落地的那一刻就不成立了**，
   是我自己写的账自己没复核。修法是不引 `@types` 也不 `as any`，就地声明观察者读到的那两个字段：
   `const shift = e as unknown as { value?: number; hadRecentInput?: boolean }`。
   修后 `npm run typecheck` = **8 错，全部在你 WIP 的 `eventFlowNumbersMatchFixture.test.ts`**（回到基线，e2e 0 错这条重新成立）。
   纪律补一条：**新增 e2e/测试文件必须立刻跑 `npm run typecheck`**，只跑 Playwright 不够 —— 闸门是 tsc，不是浏览器。
2. **变异重跑时 desktop 那档的红是"假红"，但不是产品假红**：`sed` 改 `index.html` 会让 vite 整站重启，
   desktop 报的是 `page.goto: net::ERR_ABORTED`，**不是** CLS 超阈。laptop 档报的仍是
   `首屏 CLS = 0.4584，超过 0.01` —— 与改写记账逻辑**前**逐字相同 ⇒ ① 记账等价、② 守卫非空判这两点都复核过了。
   教训写死：**变异测试要看报错文本，不能只数红绿**；验法的副作用会伪装成功能回归。
3. 复跑两态各一次并留数：**有后端 16 passed / 2 skipped**，**无后端（模拟 CI）14 passed / 4 skipped、exit=0**。

### 一条新记下的未证风险（写在这里，免得 CI 首跑被当成"应该没问题"）

所有像素阈值是在 **macOS Chromium 1.63** 量出来的，CI 跑的是 **Linux Chromium**，字体度量会变。
逐条估过余量：④ 地图格实测 620–798px 而判据是 >45% 视口（324/405px），② 右栏 1398 vs 判据 client+200，
① 与落定后 ≤2px 是结构性等式 ⇒ 不预期被字体打碎。但这是**估算**，本机 docker daemon 未起、
我没跑成 Linux 容器实测，所以按未证处理：**第一次真实 CI 跑完要回来看这 6 条的数**，
红了就按"换 OS 的度量差异"归因，不许先放松阈值。

---

## 1.13 2.9 结案：lint 降级为诊断 + 逐文件棘轮接管阻断权（2026-10-04）

### 先更正我上一轮报错的定性

我之前把 lint 与 typecheck 混着说成"两道长期红的闸门"，**不对**。用 `git clone` 出一份**干净 HEAD**
（`2590d44`）实测：

| 判据 | 干净 HEAD（= CI 看到的） | 本机工作区（含你未跟踪的在制品） |
|---|---|---|
| `npm run typecheck` | **0 error** | 8 error，全在 `src/__tests__/eventFlowNumbersMatchFixture.test.ts`（未跟踪） |
| `npm run lint` | **106 error** | 113 error（多的 7 条在未跟踪的 `dev/lcHitSurfaceProbe.tsx`） |

⇒ CI 里长期红的**只有 lint 一道**；typecheck 的红是本机现象，不冤枉 CI，它继续当阻断步。

### 106 条债落在哪一页（账本逐文件记，不只看总数）

| 归属 | error | 说明 |
|---|---|---|
| `src/dev/*Probe.tsx` 探针 | **51** | 调试页，不是发货码；`lcCovCaliberProbe` 15、`lcP5Probe` 12、`lcTabProbe` 8… |
| 测试与测试工具 | **39** | 12 个测试文件 + `testUtils/canvasMock.ts` |
| 发货码（pages/components/lib） | **16** | `BMapBlock` 4、`ClarifyPage` 4、`VStructured` 2、`wordcloudLayout` 2、`LcMap`/`VTracePanel`/`HomePage`/`ReportPage` 各 1 |

### 已落的两处

1. **CI（`.github/workflows/ci.yml:62-64`）**：`npm run lint` 改 `continue-on-error: true`，注释写明
   "它一红 ⇒ vitest(1027 例) 与 build 一行都不跑"。阻断权移到 `npm run test` 里面。
2. **棘轮（新增 3 个文件）**：`src/__tests__/lintRatchet.test.ts`(6 例) + 纯判据
   `src/__tests__/helpers/lintRatchet.ts` + 逐文件账本 `src/__tests__/fixtures/lintRatchetBaseline.json`。
   规则两条都红：`实测 > 账本` ⇒ 新增违规；`实测 < 账本` ⇒ **还了债必须同笔把账本改小**
   （手法同 `tailwindClassIntegrity` 的 `KNOWN_PROBE_DANGLING` 只减不增）。
   三个设计决定值得记：
   - **逐文件而非总数** —— 否则"修 A 两条 + B 新加两条"互相抵消就溜过去了；
   - **只统计 `git ls-files` 认得的路径** —— 你的在制品不算这条分支的债，也不由我替改；
     CI 里 checkout 全为已跟踪，两侧同口径（已用干净 clone 对账：eslint 合计 **106 == 账本合计**）；
   - **进 vitest 而不是新加一个 npm script** —— 单独脚本要有人"记得调它"，而"没人调"正是这次要修的病。
     代价实测 **全套 15.0s → 18.2s**（`beforeAll` 只 spawn 一次 eslint）。

### 判据非空判的证据（双向变异，都按预期红）

- 账本 `lcCovCaliberProbe` 15 → **14**：红「lint 棘轮：新增违规 1 个文件（已入库共 106 error；另有在制品 7 条不计入判据）… 账本 14 → 实测 15」。
- 账本 15 → **16**：红「1 个文件的债比账本少 —— 还了债请同笔把账本改小… 账本 16 → 实测 15」。
- 还原用 `cmp` 逐字节核对一致，6 例回到全绿；全量 **121 文件 / 1037 通过 + 1 todo**。
- 未跟踪排除这道栅栏是**实测生效**的：变异输出里那句「在制品 7 条」正是你 `lcHitSurfaceProbe.tsx` 的数。

### Gitee 侧

`.workflow/ci.yml` 的 goals 串**去掉** `npm run lint`（它在那条链里只会让后面三道真闸门一行不跑），
按头部约定记明差异与残余差异：真源还额外跑一次 lint 打印诊断，本侧不跑 —— 因为
`npmbuild@1` 是否支持"失败不中断"我在这台机器上验证不了。

### 还没做的（别把"接了棘轮"读成"债还清了"）

- **存量 106 一条没清**。要不要清、清哪一层，是独立决策：探针那 51 条属调试页，清了没收益；
  真正值得先动的是发货码 16 条。棘轮的作用是**从此不再增加**，不是自动减少。
- 2.10（Linux 阈值首跑复核）仍待你拍路径：push 触发真 CI / 本地起 Playwright 容器 / 把两条绝对阈值改写成相对判据。

---

## 1.14 2.10 结案：Linux 阈值风险改成实测，并顺手量出一个真缺陷 2.11（2026-10-04）

不 push、不在你机器上起 Docker，也能把"换 OS 会不会打碎阈值"变成实测：
新增 `frontend/e2e/lifeCircleStageFontStress.spec.ts` —— **同一份判据**（阈值与 locator 的真源抽进
`e2e/stageChecks.ts`，主守卫与压力档共用，漂不了）在六档度量下重跑。

### 六档 × 两视口的读数（10 passed / 2 skipped，全部现打）

| 档 | 地图格（720 档） | 图例高 | 折行标签 | 右栏超出 | 判据 |
|---|---|---|---|---|---|
| ① 基线 | 572 | 539.765625 | 6 行 | 826px | 绿 |
| ② 拦掉全部 webfont | 572 | **539.765625（逐位相同）** | 6 行 | 826px | 绿 |
| ③ rem 间距 1.25× | 561 | 592.15625 | 7 行 | — | **红（fixme）** |
| ④ ②+③ | 561 | 592.15625 | 7 行 | — | **红（fixme）** |
| ⑤ 字宽 +5% | 572 | **555.15625** | **7 行** | 874px | 绿，**余量只剩 4.8px** |
| ⑥ 字宽 +8% | 572 | 555.15625 | 7 行 | 874px | 绿 |

**结论**：地图格那条在六档里都 ≥ 视口 **79.4%**（判据下限 45%，余量 34.4pt），右栏余量 598–874px
⇒ 换 OS 换不动这两条；**唯一脆的是图例浮层**，它没有高度上限。2.10 于是从"推断不会碎"变成
"知道会红在哪一条、为什么红、还剩几像素"。

### 本轮三处自我更正（都写进码里了，不只是这里）

1. **③ 不是字体代理**。第一版把 `root font-size:20px` 当"比任何字体替换都狠"的代理，**错了**：
   本仓字号 token 是 **px 定值**（`fontSize.tag = ['11px',{lineHeight:'1.4'}]` ⇒ 行高恒 15.4px 与字体无关），
   换 CJK 字体只动**字面宽度**，后果只有一条路径 —— **某行标签折行**（+15.4px/行）。
   所以补了 ⑤⑥ 用 `letter-spacing` 直接顶这个面；③④ 保留，它钉的是另一条真实暴露面（浏览器缩放/紧凑间距）。
2. **正对照写成了硬依赖网络**。`document.fonts.size > 0` 被写成断言后，这台机器连不上
   fonts CDN 的这段时间里 5 条压力档全红在"基线档 CSS 没到"上 —— **红的是网络，不是布局**。
   改成：只有"拦住了"（`=== 0`，route abort 与网络无关）可以硬断言；基线档**只记录**，
   `fontFaces=0` 时该档自动等价于 ②，日志里明写"CSS 没到 ⇒ 本档等价②"。
   顺带一条同类事实：**断网时 CLS 那条是空跑**（没有换面可测），它的强度取决于跑的人能否取到 webfont。
3. **`document.fonts.check()` 的语义与直觉相反**，第一版探针用它判断"webfont 有没有被拦住"，
   结果正好反：CSS 被拦 ⇒ 没有 `@font-face` ⇒ check() 转去问系统有没有这族（macOS 装了）⇒ 返回 true。
   换成 `document.fonts.size`（= `@font-face` 条数），量的才是要控制的开关。

### 新发现的真缺陷 2.11（已按纪律 `test.fixme`，不留假绿）

**图例浮层高度无界**：`LcStage.Legend` 是 `absolute left-3 top-3` + 内容自然高。
720 档基线余量 **20.2px**；字宽 +5% 折出一行 ⇒ 余量 **4.8px**；rem 间距 1.25× ⇒ 图例
`171.0 + 592.2 = 763.2` vs main 下沿 `720` ⇒ **溢出 43.2px**（这一档 fixme 钉住）。
它同时就是 §1.11 里那条"1280×720 图例占屏 73%"未决问题的量化答案。
修复候选与逐屏对比见预览 **`skip/preview-lc-legend-fit.html`**（1:1 尺寸，图例高度直接钉 e2e 实测数；
已用 Playwright 渲染核对过五屏几何：① 539.8/② 555.2/③ 溢出 44.2/④ 框 546 且 `scrolls=true` + 勾选 `sticky`/⑤ 折起 143）。

---

## 1.15 2.11 按方案 A 落地：图例高度改挂同源容器（2026-10-04）

你拍的是 **A**。落点三处，全部走契约单一来源，页面不留字面量副本：

| 文件 | 改动 |
|---|---|
| `stageContract.ts` `LC_LEGEND` | 加 `overflow-y-auto` + **`lg:max-h-[calc(100%-1.5rem)]`**（顶 12 + 底 12）⇒ 高度由**地图格**决定，与字体度量解耦 |
| `stageContract.ts` `LC_LEGEND_JUDGE`（新） | `sticky bottom-0 -mx-3 -mb-3 … border-t bg-card/95` ⇒ 图例内滚之后 S3 那条「勾选常在」才成立（否则勾一次判定尺要先滚到底） |
| `LifeCirclePage.tsx` | 两个判读 `<label>` 收进 `<div className={LC_LEGEND_JUDGE}>`；证据域那条的分割线从 `border-t` 改成 `border-b`（**没有尺**时不会留一条孤线） |

**版式有一处真实变化，说清**：两个勾选之间那条分隔线挪到了证据域下方（原来各带一条 `border-t`），
折叠语义、勾选位置、文案一字未动。

### 判据侧同步做了三件事

1. **新增一条同源正判据**（`e2e/stageChecks.ts`）：图例底边**不许越出地图格**。
   它与"图例不许出 main 视野"不同 —— 是**同源比较**，与字体无关，越界只有"max-h 失效"一种解释。
2. **TC-18 从五串扩到六串**，判据里的字面量副本同步更新（这条守卫本来就是"契约改了必须红"）。
3. **结构基线重采**，并把采集口做进测试：`LC_STAGE_CAPTURE=1 npx vitest run src/__tests__/lcStageStructure.test.tsx`
   —— 采集时**先打印结构差分再落盘**，"重采"从此是一次可见记账（上一轮只能靠临时脚本，那件事只有当时的人知道）。
   本次差分恰 4 处：图例 class 一条 + 两个 `LABEL` 换成一层 `DIV`（`split/DIV[0]/DIV[14]`、`LABEL[15]` 少一子节点）。

### 验收证据（都是跑出来的）

- **两条 fixme 变成真通过**：修复前 720 档 ③④ 溢出 43.2px 只能 `test.fixme`；现在
  ③ 图例 **503px**（cell 535）、⑤⑥ 图例 **546px** = `572 − 24` ⇒ **max-h 正在挡**（日志直接打"可视/内容"两值）。
  全套 e2e **28 passed / 2 skipped / 0 failed**（53.8s；剩下 2 条 skip 只有 `lifeCircleRunning` 的 fixme）。
- **变异测试**：把 `lg:max-h-[calc(100%-1.5rem)]` 从契约里摘掉 ⇒ 720 档 ③④ 立刻红，⑤⑥ 仍绿
  （自然高 555.16 ≤ 572，与 §1.14 量的 4.8px 余量吻合）⇒ 新判据不是空判，且它挡的正是那条缺陷。
  还原用 `cmp` 逐字节核对。
- **jsdom 侧**：121 文件 / 1037 通过 + 1 todo；`tsc` 非 WIP 0 错；`eslint` 我碰过的文件 0 error。
- **顺手还掉一点债**：`wordcloudLayout.ts` 两条 `prefer-const` 清掉，棘轮账本 **106 → 104**
  （这是那条守卫第一次走通"还债 ⇒ 同笔改小账本"）。
  另清掉 `LcMap.tsx:1167` 一条**失效的** `eslint-disable`（它是 warning，不计 errorCount —— 我一开始按 3 条记，被自己的账本抓回来改成 2 条）。
  发货码剩下的 14 条分三类：`no-explicit-any` 4（要补类型）、`react-refresh/only-export-components` 3（要拆文件）、
  `react-hooks/set-state-in-effect` 5 + `refs` 1（**行为问题**，不是风格问题，得单独一轮）。

---

## 1.16 2.2c 结案：真实模式那块横幅终于有像素级验收了（2026-10-04）

**两个前提被现场推翻**（都记下来，因为它们决定这类用例能不能复用）：

1. 我上一版写在码里的判断"光把事件喂进 `EventSource` 不足以进入 running"是**半错的**：
   `subscribeLifeCircleTask` 第一行就 `seedRegistry(taskId)` 写 `status:'running'`
   （`src/lib/lifeCircleFlow.ts:138`）。真正卡住的是**传输层** —— `route.fulfill` 只能一次性给完
   body，连接随即关闭 ⇒ 客户端 `onError` → `markFailed` ⇒ 横幅刚挂上就被卸载。
   ⇒ "任务停在 running"没法靠伪造一个响应体做到，只能有一个**真保持打开的 SSE**。
2. 更关键的一条：真实模式下若 `GET /api/life-circle` 是空列表，页面只渲染「还没有体检记录」，
   **两栏舞台根本不存在**（实测 `main [class*="lg:grid-rows-"]` 计数 0）—— 那块横幅住在报告分支里
   （`LifeCirclePage.tsx:627`）。所以必须先有一条"上次体检已有记录"的历史态，否则无从测起。

**落法（生产码零改动）**：`e2e/support/lcRunningApi.mjs` 一个最小 mock 后端 —— 建任务、
**会保持打开的 SSE**（progress/message/N 个 round + 心跳）、任务状态轮询、以及一份历史报告
（**直接读仓里那份 fixture** `src/mocks/fixtures/livingCircle/kaili-ev2.json`，不抄副本）。
`playwright.config.ts` 因此从单 `webServer` 变成三个（5199 / mock 8799 / 5200），
其中 5200 用 `VITE_PROXY_TARGET` 把 `/api` 代理到 mock，并新增第三个 project
`running 1280×720（真 SSE）`。页面走的仍是生产那条
`createLivingCircleTask → subscribeLifeCircleTask → taskRegistry → 横幅` 链。

**为什么回合数要能调**（`GET /api/e2e/rounds?n=`）：限高是 `lg:max-h-[22vh]`，720 档 = 158px，
而真机上最多的 5 轮只有约 150px —— **只测 5 轮等于没压到**，摘掉限高也不会红。
所以第二条用例按到 12 行：实测横幅列**可视 158 / 内容 365** ⇒ 它真在有界内滚，
同时地图格 420px（58.3% 视口）、右栏 420/1398 都还在。

**变异验证踩了一次"无效证据"，也记下来**：第一次摘掉 `lg:max-h-[22vh]` 确实红了，但红因是
`[class*="22vh"]` **选择器找不到元素**（30s 超时）—— 那只能证明"这个 class 是承重的"，
证明不了几何断言在量什么。换成结构锚点 `[role="status"] > div.min-w-0`（进度条那个 div 不带
`min-w-0`，不会误匹配）后重做，报的是
**「横幅列高 365px 超过 22vh 上限 160px ⇒ 限高失效」** —— 带数、可归因。

**数字**：本地全套 **30 passed / 0 skipped**（53.8s）；模拟 CI（`/api` 代理指死端口）
**28 passed / 2 skipped**，那 2 条全是无 AK 时降级自跳的 live 画布 ⇒
**真实模式这两条在 CI 里是被执行的**，不依赖后端。jsdom 121 文件 / 1037 例；tsc 非 WIP 0 错；
`eslint e2e/ playwright.config.ts` 0 error。CI 那段注释里过时的"14 passed / 4 skipped"已改成实测值。

---

## 2. 待办（按顺序，逐项要证据）

| # | 事项 | 完成判据 |
|---|---|---|
| 2.0 ~~P0~~ **已完成** | **实时横幅挤压**：`:648` 那列加 `lg:max-h-[22vh] lg:overflow-y-auto` | 源码与 TC-11 已钉；**仍需**真机在 1280×720 + 5 行 `roundLines` 下确认地图与右栏仍有可用高度（属 2.2） |
| 2.0 ~~P0~~ **已完成** | **核验 `resize` 存在性** | ✅ **存在**（现场直查 `Map.prototype`，v1.0）。中途凭社区类型包判"不存在"是错误结论，已更正。最终落码：建图时 `map.resize()` 一次，不自建 RO；`lcMapResizeGuard.test.tsx` 钉住 |
| 2.0 **P0** | **「变高后画布是否跟随」还没证**：必须在一个**可见**页面里量 `host` 改高前后 `canvas` 的 style/attr 尺寸 | 打开浏览器面板（或真机）后跑一次；hidden 标签页里的两次实验已作废（渲染步被抑制，不能作数） |
| 2.0 **P1** | **GL 自愈能力真机验**（B 能否定稿就卡这条）：真 AK 下把窗口/容器改高，画布是否自动重绘、有无灰边 | 若不自愈：显式 `enableAutoResize()`，或把地图格改回定高（预览第 ⑤ 屏）。**不许**再造 `resize()` 调用 |
| 2.0 ~~P0~~ **已完成** | resize 通道的最终形态与测试 | ✅ 建图时 `map.resize()` 一次（GL 源码 = `this._watchSize()`）；`lcMapResizeGuard.test.tsx` 3 例钉「恰调一次 + 源码不得出现 `new ResizeObserver`」；地图替身改记账版 |
| 2.1 **已完成** | 跑测试 | 全量 **119 文件 / 1025 例绿**（起点 115 / 1005）。⚠ 这条绿**不覆盖排版主张**（jsdom 无排版引擎）；缺口与补案见 `生活圈-布局改动测试覆盖评估-v1.md` |
| 2.2 ~~P0~~ **已完成（Playwright）** | 真机验 B 的五条主张 | ①整页不滚 ②右栏内滚 ③滚到底图例仍可见（含真指针点击）④容器变高画布跟随 ⑤真实模式 5 行 `roundLines` 不塌 —— **五条全部有像素级验收**：①-④ 在 `lifeCircleStage`（8 例 × 两档），⑤ 在 `lifeCircleRunning`（含 12 轮压力档，§1.16）。另有 2.10 的六档字体度量压力试验（§1.14）与 2.11 的图例同源判据（§1.15） |
| 2.2b ~~P2~~ **已完成** | 首屏 CJK 字体交换造成 48px 布局跳动（仅 ≤1280 档：表头两行收回一行 ⇒ 地图格 572 → 620） | ✅ 选的是第四种解法：字体 URL 从 `display=swap` 改 **`optional`**（到位就用、没到这趟不换 ⇒ 一次定形）。新增 e2e「首屏零布局跳动 CLS<0.01」，**变异测试**验过非空判 —— 改回 swap 时 1280 档报 CLS=0.4584 红、1440 档照绿（详见 §1.12） |
| 2.2c ~~P2~~ **已完成（真 SSE + 自带 mock）** | 把 ⑤ 做成像素级：真实模式下把取证回合喂进横幅，量地图格与右栏是否仍有可用高度 | ✅ 结案见 §1.16。`e2e/support/lcRunningApi.mjs`（含会保持打开的 SSE 与一份真 fixture 报告）+ 第三个 project `running 1280×720`；两条用例：5 轮（真机最大量级）与 **12 轮压过 22vh**（实测横幅列可视 158 / 内容 365、地图格 420px=58.3% 视口、右栏 420/1398）。变异：摘掉 `lg:max-h-[22vh]` 报「365px 超过 22vh 上限 160px」。CI 里也执行（不依赖后端） |
| 2.3 ~~待办~~ **已完成** | 镜像页 / 对比页 / 探针的读数面：5 处私有实现全换成 `VStatLine`（`row` 面对旧消费方零像素变化） | `statLineSingleSource.test.ts` 3 例绿；`lifeCircleReportView.test.tsx` 10 例绿；`ComparePage` 相关用例绿 |
| 2.4 **部分完成** | `ComparePage.tsx:333,346` 的**未定义** `className="card"` ✅ 已修（两块对比卡此前一直没有卡面）+ 裸 token 名守卫已补（§1.10）。**剩下的**：`:341` `h-[440px]`、`:356` `h-[400px]` 两处写死定高是否收成共享常量 | 定高收口需与用户确认（改了要重采 ComparePage 结构基线）；守卫断言"发货码零命中 + 探针 3 处只减不增"已绿 |
| 2.4b ~~P2~~ **体检台侧已完成** | S4 完整抽件 `LcStage`（`.Canvas/.Legend/.Panel`）。阻塞被换掉的路子：像素量不了，但"有没有多包一层"是纯树形问题 ⇒ 先采**结构基线**再重构（见 §1.9） | `lcStageStructure.test.tsx`(2 例) 在重构前后都绿；全量 120 文件 / 1027 例绿。**剩下的**：`LifeCircleReportView` 与 `ComparePage` 采用前须各自采一份基线（树不同，拿体检台的基线比是空判） |
| 2.5 | 更新预览与实现的一致性说明 | 五处偏差需改齐或登记：① summary 文案；② 折叠从"整块收起"改成"只收色块、勾选常在"（S3 结果，预览第 ③ 屏要跟着改）；③ label 全称 vs 预览缩写；④ 预览外壳顶栏上方缺那块可无界增长的横幅 ⇒ ③ 屏"不挤压"结论对真实模式不成立；⑤ 图例折叠用条件渲染 vs 预览的 CSS 隐藏 |
| 2.6 ~~待办~~ **已完成** | 提交划分 | 按批准的四笔落地：`0a88694` fix（`index.html` + CLS 例同笔）、`e04dc06` test(e2e)（`lifeCircleRunning.spec.ts` 的 fixme）、`df3ffd8` ci（两份 yml）、`8b29d86` docs（两份台账 + `ARCHITECTURE.md`）。⚠ 你 WIP 的 8 处（`docs/多源POI…md`、`gen-living-circle-fixtures.mjs`、`eventFlow.json`、`livingCircleMock.ts`、删 `start.sh`、`preview-lc-hit.html`、`eventFlowNumbersMatchFixture.test.ts`、`lcHitSurfaceProbe.tsx`）**一笔都没进暂存区**，`git status` 核过。本行的提交状态回写是第 5 笔（只动这一段记账，无代码）。 |
| 2.7 ~~P2~~ **已完成** | `docs/ARCHITECTURE.md` §10 新增「页面滚动所有权与舞台契约」：三种滚动模型的适用面、契约唯一真源、三条硬规矩（高度不许由内容决定 / 尺寸跟随交给 SDK 且厂商 API 只认厂商运行时 / `z-10` 来由），并要求新页先自采结构基线 | 文档成文；末尾写明"没有渲染步时观察既不能证实也不能证伪，不得拿单元全绿冒充已验" |
| 2.8 ~~待办~~ **已完成** | e2e 接入 CI：`.github/workflows/ci.yml` 新增独立 `e2e` job（`npm ci` → `playwright install --with-deps chromium` → `npm run test:e2e` → 失败时上传现场） | **独立成 job 的理由已写进 yml**：`frontend` job 在 `lint` 步就红，step 按序终止 ⇒ 塞进去的排版防线永远轮不到跑。CI 条件已本地复现（`VITE_PROXY_TARGET` 指死端口）：**exit=0 / 14 passed / 4 skipped**；Gitee 侧按它的约定在头部记明"有意不跟"的理由。两份 yml 用 pyyaml 解析校验过 |
| 2.9 ~~未决~~ **已按推荐落地（存量未清）** | `npm run lint` 与 `npm run typecheck` 该不该继续当闸门 | ✅ 定性已更正并实测（干净 HEAD clone）：**typecheck 0 error**（本机那 8 条全来自你未跟踪的在制品），**lint 106 error** 才是 CI 里唯一长期红的一道。落法：lint 降为 `continue-on-error` 诊断（`ci.yml:62-64`），阻断权交给 vitest 里的**逐文件棘轮** `src/__tests__/lintRatchet.test.ts`(6 例) + `fixtures/lintRatchetBaseline.json`。双向变异实测都红、口径与 CI 对账一致、全套 121 文件 / 1037 例绿（15.0s→18.2s）。**剩下的不是闸门问题而是债**：存量 106 一条没清（探针 51 / 测试 39 / 发货码 16），要清就从发货码那 16 条起 |
| 2.10 ~~待观察~~ **已改成实测（不用 push、不用 Docker）** | 阈值全部在 macOS Chromium 1.63 量得，CI 是 Linux Chromium，字体度量会变（§1.12 末估过余量，属推断非实测） | ✅ 结案见 §1.14：`e2e/lifeCircleStageFontStress.spec.ts` 六档度量 × 两视口重跑**同一份判据**（阈值真源抽进 `e2e/stageChecks.ts`，主守卫与压力档共用一份，漂不了）。地图格那条六档全 ≥ 视口 79.4%（下限 45%，余量 34.4pt）、右栏余量 598–874px ⇒ 换 OS 换不动这两条；**唯一脆的是图例浮层** ⇒ 转成 2.11 |
| 2.11 ~~P1~~ **已按方案 A 落地（§1.15）** | **图例浮层高度无界**：`absolute left-3 top-3` + 内容自然高。720 档基线余量 20.2px，字宽 +5% 只剩 4.8px，rem 间距 1.25× 溢出 43.2px | ✅ `LC_LEGEND` 加 `overflow-y-auto` + `lg:max-h-[calc(100%-1.5rem)]`（挂地图格=视口同源），判读块收进新常量 `LC_LEGEND_JUDGE` 并 `sticky bottom-0`。e2e 新增**同源正判据**「图例不许越出地图格」；两条 fixme 变成真通过（③ 503px、⑤⑥ 恰好 546px=572−24 ⇒ max-h 在挡）；变异测试（摘掉 max-h ⇒ 720 档 ③④ 红）证明非空判。全套 e2e **28 passed / 2 skipped / 0 failed**，jsdom 121 文件 / 1037 例。结构基线已重采（差分 4 处，采集口 `LC_STAGE_CAPTURE=1` 已内建）；TC-18 扩到六串 |

---

## 3. 回滚点

- S5 收敛（`VStatLine` 五处换件）与滚动接管任一失衡可单独回滚，互不牵连：前者只改消费点，后者只改 utility 串。
- 舞台契约自本轮起住在 `components/lifecircle/stageContract.ts`（**单一来源**）；回滚滚动接管 = 改那一个文件里的 `lg:` 前缀即可，页面不再散着字面量。
- 尺寸跟随 = `LcMap` 建图后那一行 `map.resize()`（SDK 内部 `_watchSize()`）。删掉这一行即回到"容器变高不重绘"的旧行为，**没有**其它残留（我们不自建 ResizeObserver，也没有观察器要卸载）。
- CI 的 `e2e` job 是**纯增**：删掉那一个 job 块即回到原状，`backend/frontend/docker` 三个 job 与 `npm run test:e2e` 脚本本身都不依赖它（本地照跑）。Gitee 侧本就没跟，无需回滚。
- `display=optional` 与 CLS 用例是**一对**，回滚要同时撤：只把 URL 改回 `swap` 会让「首屏零布局跳动」在 1280 档稳定红（实测 CLS=0.4584），那不是回归而是记账对了。若要保留跳动换回字体落地率，就得把判据改成显式阈值并在此处登记理由。
- 真实模式那两条（2.2c）是**纯测试基建**：`e2e/lifeCircleRunning.spec.ts` + `e2e/support/lcRunningApi.mjs` + `playwright.config.ts` 的第三个 project 与两个额外 `webServer`，删掉即回到"只有源码钉 TC-11"的状态，**没有生产码需要一起回滚**。⚠ 但三处要一起撤：只删用例不删 config，会留下一个没人访问的 5200 dev server 与一个空转的 mock 后端。
- 图例收口（2.11 / 方案 A）的回滚点是**两个常量**：`stageContract.ts` 里删掉 `LC_LEGEND` 的 `lg:max-h-[calc(100%-1.5rem)] overflow-y-auto` 与整条 `LC_LEGEND_JUDGE` 即回到"内容决定浮层高度"。⚠ 同笔必须一起改三处判据，否则红的是记账：TC-18 六串（`lcLayoutContract.test.tsx` 里那份字面量副本）、结构基线（`LC_STAGE_CAPTURE=1` 重采）、e2e 那条同源正判据「图例不许越出地图格」（`e2e/stageChecks.ts`）。

## 4. 本轮明确不做

- 小屏 / 矮视口断点（用户已拍：本轮不管）。
- 外层 `AppLayout.tsx:6` 的滚动容器（用户已拍：先不改）。
- 不引入新布局库，不动 `LivingCircleReport` 数据结构，不动 `MiniRadar` 尺寸推导（`docs/雷达图遮挡修复-落地记录与后续项.md:47` 禁固定宽）。
- 不顺手改用户 WIP 的 `eventFlowNumbersMatchFixture.test.ts` / `lcHitSurfaceProbe.tsx` 类型问题。

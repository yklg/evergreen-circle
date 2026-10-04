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

## 2. 待办（按顺序，逐项要证据）

| # | 事项 | 完成判据 |
|---|---|---|
| 2.0 ~~P0~~ **已完成** | **实时横幅挤压**：`:648` 那列加 `lg:max-h-[22vh] lg:overflow-y-auto` | 源码与 TC-11 已钉；**仍需**真机在 1280×720 + 5 行 `roundLines` 下确认地图与右栏仍有可用高度（属 2.2） |
| 2.0 ~~P0~~ **已完成** | **核验 `resize` 存在性** | ✅ **存在**（现场直查 `Map.prototype`，v1.0）。中途凭社区类型包判"不存在"是错误结论，已更正。最终落码：建图时 `map.resize()` 一次，不自建 RO；`lcMapResizeGuard.test.tsx` 钉住 |
| 2.0 **P0** | **「变高后画布是否跟随」还没证**：必须在一个**可见**页面里量 `host` 改高前后 `canvas` 的 style/attr 尺寸 | 打开浏览器面板（或真机）后跑一次；hidden 标签页里的两次实验已作废（渲染步被抑制，不能作数） |
| 2.0 **P1** | **GL 自愈能力真机验**（B 能否定稿就卡这条）：真 AK 下把窗口/容器改高，画布是否自动重绘、有无灰边 | 若不自愈：显式 `enableAutoResize()`，或把地图格改回定高（预览第 ⑤ 屏）。**不许**再造 `resize()` 调用 |
| 2.0 ~~P0~~ **已完成** | resize 通道的最终形态与测试 | ✅ 建图时 `map.resize()` 一次（GL 源码 = `this._watchSize()`）；`lcMapResizeGuard.test.tsx` 3 例钉「恰调一次 + 源码不得出现 `new ResizeObserver`」；地图替身改记账版 |
| 2.1 **已完成** | 跑测试 | 全量 **119 文件 / 1025 例绿**（起点 115 / 1005）。⚠ 这条绿**不覆盖排版主张**（jsdom 无排版引擎）；缺口与补案见 `生活圈-布局改动测试覆盖评估-v1.md` |
| 2.2 **P0（环境阻塞）** | 真机验 B 的五条主张 | ①整页不滚 ②右栏内滚 ③滚到底图例仍可见 ④容器变高画布跟随无灰边 ⑤真实模式 5 行 `roundLines` + 1280×720 不塌。**已实证**当前面板 `requestAnimationFrame` 3.6 秒 0 帧 ⇒ 渲染步停摆，需正常窗口或 Playwright |
| 2.3 ~~待办~~ **已完成** | 镜像页 / 对比页 / 探针的读数面：5 处私有实现全换成 `VStatLine`（`row` 面对旧消费方零像素变化） | `statLineSingleSource.test.ts` 3 例绿；`lifeCircleReportView.test.tsx` 10 例绿；`ComparePage` 相关用例绿 |
| 2.4 **P2** | 地图定高先例收口：`ComparePage.tsx:341` 写死 `h-[440px]`、`:356` `h-[400px]`；另 `:335,346` 用了**未定义**的 `className="card"` 工具类（既存缺陷，与 `tailwindClassIntegrity` 的 token 纪律相悖） | 与用户确认是否处理；`card` 那条建议单独一笔小修，不与布局重构混做 |
| 2.4b ~~P2~~ **体检台侧已完成** | S4 完整抽件 `LcStage`（`.Canvas/.Legend/.Panel`）。阻塞被换掉的路子：像素量不了，但"有没有多包一层"是纯树形问题 ⇒ 先采**结构基线**再重构（见 §1.9） | `lcStageStructure.test.tsx`(2 例) 在重构前后都绿；全量 120 文件 / 1027 例绿。**剩下的**：`LifeCircleReportView` 与 `ComparePage` 采用前须各自采一份基线（树不同，拿体检台的基线比是空判） |
| 2.5 | 更新预览与实现的一致性说明 | 五处偏差需改齐或登记：① summary 文案；② 折叠从"整块收起"改成"只收色块、勾选常在"（S3 结果，预览第 ③ 屏要跟着改）；③ label 全称 vs 预览缩写；④ 预览外壳顶栏上方缺那块可无界增长的横幅 ⇒ ③ 屏"不挤压"结论对真实模式不成立；⑤ 图例折叠用条件渲染 vs 预览的 CSS 隐藏 |
| 2.6 | 提交划分 | 已提交 `8a4630a`（fix）+ `21f737e`（docs）。**本轮 S5 / S4 第一步 / 文档尚未提交**，等你批准 |
| 2.7 **P2** | `docs/ARCHITECTURE.md` 补「页面滚动所有权」一节（S8） | 现契约只活在 `stageContract.ts` 头注释与测试判据里，读架构文档的人看不到三套模型并存的取舍 |

---

## 3. 回滚点

- S5 收敛（`VStatLine` 五处换件）与滚动接管任一失衡可单独回滚，互不牵连：前者只改消费点，后者只改 utility 串。
- 舞台契约自本轮起住在 `components/lifecircle/stageContract.ts`（**单一来源**）；回滚滚动接管 = 改那一个文件里的 `lg:` 前缀即可，页面不再散着字面量。
- 尺寸跟随 = `LcMap` 建图后那一行 `map.resize()`（SDK 内部 `_watchSize()`）。删掉这一行即回到"容器变高不重绘"的旧行为，**没有**其它残留（我们不自建 ResizeObserver，也没有观察器要卸载）。

## 4. 本轮明确不做

- 小屏 / 矮视口断点（用户已拍：本轮不管）。
- 外层 `AppLayout.tsx:6` 的滚动容器（用户已拍：先不改）。
- 不引入新布局库，不动 `LivingCircleReport` 数据结构，不动 `MiniRadar` 尺寸推导（`docs/雷达图遮挡修复-落地记录与后续项.md:47` 禁固定宽）。
- 不顺手改用户 WIP 的 `eventFlowNumbersMatchFixture.test.ts` / `lcHitSurfaceProbe.tsx` 类型问题。

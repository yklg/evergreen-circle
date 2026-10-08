/**
 * 体检台舞台契约（评审 S4 的第一步：先让契约有单一来源，再谈抽件）
 *
 * ## 这里放的是什么
 *
 * 「谁决定地图高度、谁负责滚动」这件事，在代码里就是下面这几串 utility。它们**不是**样式细节，
 * 而是一份跨层契约：BMapGL 的 canvas 按父容器**像素高**撑开（`ComparePage.tsx:340` 的注释记下过
 * 这条物理约束），而 CSS grid 默认 `align-items: stretch` 会让"左格的高"由"右栏内容的多寡"决定 ——
 * 体检台原先正是这样，地图被拉到 1627px，锚在它顶边的图例一下滑就出屏。
 *
 * ## 为什么先收常量、不先抽组件
 *
 * 抽 `<LcStage>` 这种面板件必然要多包一层 DOM，而 `lg:h-full` / `min-h-0` 这类百分比高度是
 * **按父层解析**的 —— 层级一变，解析结果就变。在没有可见渲染环境（本轮实测：内置面板里
 * `requestAnimationFrame` 3.6 秒 0 帧，渲染步被停掉）的情况下做这种重构，等于闭眼改几何。
 * 所以本步只做"字符串有主人"，包层重构留到能在真浏览器里量尺寸时再做。
 *
 * ## 三条规矩
 *
 *  1. 这些串只许出现在本文件；改任何一条都算改契约，需同时改 `statLineSingleSource` 同级的
 *     布局守卫（`__tests__/lcLayoutContract.test.tsx` TC-18 会红）。
 *  2. `LEGEND` 里的 `z-10` 不是装饰：百度 GL 往地图容器注入 `.BMap_mask`（`z-index:9`），
 *     压在其上的浮层点不着 —— 现场实测过一次（`LifeCirclePage.tsx` 图例注释记着）。
 *  3. `lg:` 前缀刻意的：大屏才接管滚动。小屏/矮视口维持原整页滚，那是另一套模型，
 *     本轮未处理，别把它当响应式方案。
 */

/** 页根：大屏下把滚动交给本身体，`overflow-hidden` 让"内容撑高整页"这条路径彻底断掉 */
export const LC_PAGE_ROOT =
  'mx-auto flex min-h-full max-w-[1240px] flex-col gap-4 px-6 py-6 lg:h-full lg:min-h-0 lg:overflow-hidden'

/** 两栏：行高锁成容器高（`minmax(0,1fr)`），右栏内容再多也不许反向决定左格高度 */
export const LC_SPLIT =
  'grid flex-1 grid-cols-1 gap-4 lg:min-h-0 lg:grid-cols-[1fr_320px] lg:grid-rows-[minmax(0,1fr)]'

/** 地图格：大屏下高度=容器高；小屏仍按 `min-h-[480px]` 参与整页滚 */
export const LC_MAP_CELL =
  'relative min-h-[480px] overflow-hidden rounded-card border border-line bg-card shadow-card lg:h-full lg:min-h-0'

/** 右栏（体检单）：大屏下自己滚 —— 图例与地图控件因此永不进滚动链 */
export const LC_ASIDE =
  'flex flex-col gap-4 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-1'

/** 图例浮层：`z-10` 见上方规矩 2。
 *  `lg:max-h-[calc(100%-1.5rem)]`（顶 12px + 底 12px）+ 内滚是**契约的一部分**，不是美化：
 *  浮层原先由内容决定高度，1280×720 基线余量只有 20.2px，字宽 +5% 只剩 4.8px，
 *  rem 间距 1.25× 直接溢出 main 下沿 43.2px（台账 2.11，六档压力实测见
 *  `e2e/lifeCircleStageFontStress.spec.ts`）。挂 `max-h` 之后高度与**同源容器**绑定 ⇒ 与字体度量解耦。 */
export const LC_LEGEND =
  'absolute left-3 top-3 z-10 flex max-w-[190px] flex-col gap-1.5 overflow-y-auto rounded-btn border border-line bg-card/90 p-3 backdrop-blur lg:max-h-[calc(100%-1.5rem)]'

/** 图例里的**判读控件块**（证据域 / 判定尺两个勾选）：图例内滚时必须吸底。
 *  规矩 3（S3）说"折叠只收色块，勾选常在"—— 有了内滚之后"常在"就得靠 sticky 才成立，
 *  否则勾一下判定尺要先把浮层滚到底。负外边距让这条块铺满浮层内宽并盖住下内边距，读起来像 footer。 */
export const LC_LEGEND_JUDGE =
  'sticky bottom-0 -mx-3 -mb-3 flex flex-col gap-1.5 rounded-b-btn border-t border-line/70 bg-card/95 px-3 pb-3 pt-1.5 backdrop-blur'

/* ══ 报告页的两栏行（2026-10-05，同一类症状第三次复发才收进来的）════════════════
 *
 * 三次症状：主图下方空白 248px → 台账卡右侧幽灵栏 560px → 配对地图下方空白 219px，
 * 且**选中一格后台账长出读数表（实测 629→794），留白跟着涨到 384px**。三次不是三个 bug，
 * 是同一个缺失：报告页每一行都没说过"谁的高说了算"，于是某一栏内容的多寡反向决定另一栏的高。
 * 体检台早就为这件事立过规矩（上面 `LC_SPLIT`/`LC_MAP_CELL`/`LC_ASIDE` 三条；当时地图被
 * 右栏拉到 1627px），报告页没参与那份契约 ⇒ 症状换个方向又长回来。
 *
 * 政策（与体检台同一条，只是落在文档流里的一行上）：
 *  1. **行高由一个与两栏内容都无关的显式值决定**（`lg:h-[640px]`）；
 *  2. **地图格铺满行**（`lg:h-full` + 槽 `lg:flex-1`）⇒ 卡下留白在结构上不可能出现；
 *  3. **会变高的那一栏自己滚**（台账是文档，滚它自己，不许撑行）；
 *  4. 小屏维持堆叠与显式 px；打印必须放开高与滚动，否则导出 PDF 把读数表整段截掉。
 *
 * `LC_REPORT_SPLIT` 被报告页**两行共用**（体检单行、台账配对行）：两行的竖向分栏缝因此
 * 由构造对齐。上一版一行写 `1.6fr_1fr`、一行等宽，缝差 144px，就是用户说的"不统一"。
 * 判据：`__tests__/lcLayoutContract.test.tsx`（字面量逐字钉）+ `e2e/lcReportLocalMap.spec.ts`
 *（几何：选格前后行高不变、地图无留白、台账可内滚）。 */

/** 报告页两行共用的分栏模板：地图在左，与体检单行同一侧、同一比例 */
export const LC_REPORT_SPLIT = 'lg:grid-cols-[1.6fr_1fr]'

/** 台账 ↔ 配对地图那一行：行高锁死，与两栏内容的多寡无关 */
export const LC_REPORT_PAIR_ROW =
  'mt-4 grid grid-cols-1 gap-4 lg:h-[640px] lg:min-h-0 print:h-auto'

/** 配对地图格：大屏铺满整行 */
export const LC_REPORT_MAP_CELL =
  'relative flex flex-col overflow-hidden rounded-card border border-line bg-card shadow-card lg:h-full lg:min-h-0'

/** 地图槽：小屏固定 360px，大屏吃掉卡内除图注外的全部高度 */
export const LC_REPORT_MAP_SLOT =
  'h-[360px] shrink-0 print:hidden lg:h-auto lg:min-h-0 lg:flex-1'

/** 台账格：内容会长（选中一格多出整张读数表）⇒ 大屏自己滚，打印放开 */
export const LC_REPORT_DOC_CELL =
  'lg:h-full lg:min-h-0 lg:overflow-y-auto print:overflow-visible print:h-auto'

/**
 * nar-3 分章局部地图（静态 SVG）的两颗格子。为什么不复用上面那三件套：
 *  - `LC_REPORT_MAP_SLOT` 自带 `print:hidden`（它装的是 GL canvas，打印本来就不出图，
 *    PDF 里由 `IsochroneSnapshot` 那张静态快照顶替）。分章图**就是静态 SVG**，
 *    套上那颗等于把它从 PDF 里抹掉 —— 正是 P0-6 那个缺口的反面。
 *  - `LC_REPORT_PAIR_ROW`/`LC_REPORT_MAP_CELL` 带 `lg:h-[640px]`+`lg:h-full` 那套行高政策，
 *    服务对象是"地图 ↔ 台账"两栏一行；分章图在文档流里独占一行，套上去会让它去问一个
 *    不存在的高度。所以这里给显式 px，小屏短一点、大屏长一点。
 */
export const LC_REPORT_CHAPTER_MAP_CELL =
  'mt-4 overflow-hidden rounded-card border border-line bg-card shadow-card'

/** 分章地图槽：显式像素高（文档流里没有"右栏说了算"那个上下文，就不假装有一个） */
export const LC_REPORT_CHAPTER_MAP_SLOT = 'h-[280px] sm:h-[340px]'

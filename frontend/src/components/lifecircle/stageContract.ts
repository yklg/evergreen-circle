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

/** 图例浮层：`z-10` 见上方规矩 2 */
export const LC_LEGEND =
  'absolute left-3 top-3 z-10 flex max-w-[190px] flex-col gap-1.5 rounded-btn border border-line bg-card/90 p-3 backdrop-blur'

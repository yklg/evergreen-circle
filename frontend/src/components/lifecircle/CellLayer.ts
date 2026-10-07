/**
 * 选中格图层（两档共用）· 一份几何、两个薄渲染器。
 *
 * 形状照 `ShapeSectorOverlay.ts`（它那行注释「闭合多边形…可直接喂给 `bmap.Polygon` / SVG `points`」
 * 就是本域给这类分叉开的药方）：本文件只出**地理坐标与半径**，不含 `bmap.*`、不含 JSX。
 *
 * ## 为什么要有这一层
 * `LcMap` 是两棵渲染树（live 侧造 overlay、降级侧画 SVG 图元）。"选中格"此前**只在 live 那半**存在，
 * 于是报告页那句「选中格与右侧台账卡互指，图上带该格的判定尺圆」在没 AK 的机器上是半真话，
 * 而全套件一条都抓不到 —— 判定尺当年就是只补了 live 一半（那颗开关在降级态点下去没反应），
 * 口径对照环、形状扇面又各写了一遍。清单不同源才是根因；这一层把它收成一处。
 *
 * ## 判定尺圆为什么给 `center + radiusM` 而不是插好的多边形
 * live 那侧必须继续用 `bmap.Circle`：它带着三条真机验过的纪律（只描边 `fillOpacity: 0`、
 * `enableClicking: false`、不进 `fitPts`），迁移时顺手改成 Polygon 就等于把已验的东西重新变成未验。
 * 降级那侧本来就要按 `lcRing` 逆投影成 polygon —— 画布横纵比例不同，用 SVG 正圆会纵向多出约 39%
 * （`lib/livingCircle.ts:263` 那条 P0 记录）。**同一份数、两种基元**，与判定尺那层同一套做法。
 */
import type { LngLat, LivingCircleReport } from '../../types'
import { cellCenter, cellsLedgerOf, lcFromMeters } from '../../lib/livingCircle'

export interface CellLayerPlan {
  /** 格界四角（真实米制下的方框；`<polygon>` 自动闭合，live 的 Polygon 也吃这四角） */
  corners: LngLat[]
  /** 该格判定尺圆的圆心 */
  center: LngLat
  /** 该格判定尺圆的半径（米）—— 取自台账声明，不许在渲染面写死 */
  radiusM: number
}

/**
 * 拿不到台账、或索引越界 ⇒ `null` = **整层不画**（缺席即不渲染，不是画个灰框打码）。
 * 判据半边同一条：脱敏态由调用方（`desensitize`）在这之前就挡住，两档共用同一颗 predicate。
 */
export function cellLayerPlan(
  lc: Pick<LivingCircleReport, 'caliber'>,
  cell: [number, number] | null,
): CellLayerPlan | null {
  if (!cell) return null
  const led = cellsLedgerOf(lc)
  if (!led) return null
  const [i, j] = cell
  if (i < 0 || j < 0 || i >= led.n || j >= led.n) return null
  const half = led.step_m / 2
  const c = cellCenter(led, i, j)
  return {
    corners: [[-half, -half], [half, -half], [half, half], [-half, half]]
      .map(([dx, dy]) => lcFromMeters(c, dx, dy)),
    center: c,
    radiusM: led.radius_m,
  }
}

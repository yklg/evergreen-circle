/**
 * 形状扇区图层的**几何层**（笔三 S13）：把 `isochrones[].shape.bins_m` 画成 8 个方位楔形。
 *
 * 为什么单独成模块而不内联进 `LcMap.tsx`（81KB、13 层）：照 `HeatFieldOverlay.ts` /
 * `NormalizedOverlay.ts` 的先例 —— 投影与画法是能被单测钉死的东西，混在那个文件里就只能
 * 靠人眼。这里**只出坐标、不碰地图实例**，`LcMap` 负责把多边形贴到 BMapGL 上。
 *
 * 两条硬口径：
 *  1. **原点恒为 `report.scene.center`**，不许用 `customCenter ?? scene.center`。
 *     等时圈环走绝对坐标（`LcMap.tsx:700-704`），本来就不随拖拽移动；楔形若跟着
 *     拖拽后的选点跑，就会出现"扇区从一个中心发射、环在另一个中心"的自相矛盾图面。
 *     而形状键本身就是按 `scene.center` 量的（`shape.origin` 随键声明）。
 *  2. 逆投影只走 `lcFromMeters`（全仓唯一实现）。它的历史事故就是把度当弧度，
 *     环放大 57.3 倍 —— 抄一份就会再犯一次。
 */
import { lcFromMeters } from '../../lib/livingCircle'
import type { LngLat, ShapeCaliber } from '../../types'

/** 一个楔形：圆心 + 一段弧上的点。渲染时按 [center, ...arc, center] 闭合成多边形。 */
export interface ShapeSector {
  index: number
  word: string
  radiusM: number
  /** 闭合多边形（首尾同点），可直接喂给 `bmap.Polygon` / SVG `points` */
  ring: LngLat[]
}

const ARC_STEPS = 6

/** 自北顺时针的方位角 → 米偏移（x 东、y 北，与 `lcMeters` 同侧）。 */
function offsetOf(azDeg: number, radiusM: number): [number, number] {
  const a = (azDeg * Math.PI) / 180
  return [Math.sin(a) * radiusM, Math.cos(a) * radiusM]
}

/**
 * 8 个方位楔形。`bin_deg`/`bin_phase` 从键里读，不在这里假设：
 * 中心分相 ⇒ 第 k 箱覆盖 `[k·45 − 22.5, k·45 + 22.5)`。
 */
export function shapeSectors(center: LngLat, shape: ShapeCaliber): ShapeSector[] {
  const step = shape.bin_deg
  const half = step / 2
  return shape.bins_m.map((radiusM, k) => {
    const az0 = k * step - half
    const arc: LngLat[] = []
    for (let i = 0; i <= ARC_STEPS; i++) {
      const [mx, my] = offsetOf(az0 + step * (i / ARC_STEPS), radiusM)
      arc.push(lcFromMeters(center, mx, my))
    }
    return {
      index: k,
      word: shape.bins_word[k],
      radiusM,
      ring: [lcFromMeters(center, 0, 0), ...arc, lcFromMeters(center, 0, 0)],
    }
  })
}

/** 第 k 箱的**中心射线**（图上那条"最弱方向"标注线用，避免各处各算各的）。 */
export function shapeSectorRay(center: LngLat, shape: ShapeCaliber, index: number): [LngLat, LngLat] {
  const [mx, my] = offsetOf(index * shape.bin_deg, shape.bins_m[index])
  return [lcFromMeters(center, 0, 0), lcFromMeters(center, mx, my)]
}

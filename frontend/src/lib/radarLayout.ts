/**
 * 雷达图布局 —— 纯函数、确定性、可单测（无 DOM）。
 *
 * 根治的是什么：原 `MiniRadar.tsx` 把 `cx / cy / r / 1.18 / viewBox` 当 5 个互不约束的
 * 手调常量内联在渲染函数里，而**标签内容是数据驱动的**（后端
 * `app/living_circle/category_rule.CATEGORY_RULES[].label` → 报告分数里雷达数组的
 * `dimension` 字段）。
 * 画布是常量、内容是变量，于是任一类新增或改名就静默裁切：8 维时顶部「菜市场」上探
 * 出界 5.22 单位、底部「养老」下探 182.07 > viewBox 高 172 整行丢失。
 *
 * ⚠️ 上面那句刻意不写成「分数路径.雷达数组」的原始字面量：
 * `__tests__/visitorUnrated.test.tsx` 是**按源码文本**扫「谁在读报告分数」的，本文件只是
 * 纯几何、没有「未评」分支，一旦命中那个字面量就会被误登进回归面基线（实测 `extra` 变红）。
 *
 * 这里的不变量是反过来的：**画布由标签包围盒的并集决定**。
 * 因此不存在"改标签要顺手改画布"这件事。
 *
 * 已用真实 Chrome `getBBox()` 校验（n=8 真实标签 → viewBox 0 0 242 215，
 * 四边余量 5.99–33.26、标签到外环净空 5.99–17.99）。
 */

import { estimateTextBox } from './textMetrics'

export interface RadarDim {
  dimension: string
  score: number
}

export type RadarAnchor = 'start' | 'middle' | 'end'

/** 标签：基线点 + 锚点 + 字形盒（viewBox 坐标系，`[x0,y0,x1,y1]`） */
export interface RadarLabel {
  text: string
  x: number
  y: number
  anchor: RadarAnchor
  bbox: readonly [number, number, number, number]
}

export interface RadarRing {
  k: number
  points: string
}

export interface RadarSpoke {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface RadarLayout {
  /** 恒为 `0 0 W H`，W/H 有限且 > 0（含 n=0） */
  viewBox: string
  width: number
  height: number
  cx: number
  cy: number
  radius: number
  /** 标签锚点到外环的绝对间距，由度量派生 */
  labelGap: number
  fontSize: number
  pad: number
  /** 恒为 3 条，与 n 解耦 */
  rings: RadarRing[]
  spokes: RadarSpoke[]
  /** n=0 时为 `''` */
  dataPoints: string
  labels: RadarLabel[]
}

export interface RadarLayoutOptions {
  radius?: number
  ringPad?: number
  fontSize?: number
  pad?: number
  strokeHalf?: number
}

export const RADAR_DEFAULTS = {
  radius: 74,
  /** 标签带与外环之间的期望净空 */
  ringPad: 6,
  fontSize: 11,
  /** 派生画布四边留白 */
  pad: 6,
  strokeHalf: 1,
} as const

/** 网格环层级；导出以便测试把「polygon 数 = 3 + 1」钉成不变量而非字面量。 */
export const RADAR_RING_LEVELS: readonly number[] = [0.33, 0.66, 1]

/** |cos| 超过该阈值即认为标签在左右两侧，锚点朝外展开。 */
export const RADAR_ANCHOR_COS_THRESHOLD = 0.25

const round2 = (v: number) => Math.round(v * 100) / 100

export function anchorOf(cos: number): RadarAnchor {
  if (cos > RADAR_ANCHOR_COS_THRESHOLD) return 'start'
  if (cos < -RADAR_ANCHOR_COS_THRESHOLD) return 'end'
  return 'middle'
}

export function layoutRadar(
  dims: readonly RadarDim[],
  opts?: RadarLayoutOptions,
): RadarLayout {
  const radius = opts?.radius ?? RADAR_DEFAULTS.radius
  const ringPad = opts?.ringPad ?? RADAR_DEFAULTS.ringPad
  const fontSize = opts?.fontSize ?? RADAR_DEFAULTS.fontSize
  const pad = opts?.pad ?? RADAR_DEFAULTS.pad
  const strokeHalf = opts?.strokeHalf ?? RADAR_DEFAULTS.strokeHalf

  const n = dims.length

  // n=0 也要给出**有效** viewBox：`ComparePage` 的卡片直接映射用户选的任意历史体检
  // 记录，离线记录进雷达是线上路径，`0 0 NaN NaN` 就是可见破图。
  if (n === 0) {
    const side = 2 * radius + 2 * pad
    return {
      viewBox: `0 0 ${side} ${side}`,
      width: side,
      height: side,
      cx: side / 2,
      cy: side / 2,
      radius,
      labelGap: 0,
      fontSize,
      pad,
      rings: RADAR_RING_LEVELS.map((k) => ({ k, points: '' })),
      spokes: [],
      dataPoints: '',
      labels: [],
    }
  }

  /**
   * 标签带偏移由度量派生，不留手调间距。
   *
   * 字形盒以基线为轴**上下不对称**：圆心**下方**的标签向圆内探出的是 ascent（实测 11.99），
   * 上方只探出 descent（4.07）。旧的 `radius × 1.18` 等效间距 13.3，于是底部标签顶缘
   * 到外环净空只剩 0.3 —— 静态算不出来，是预览实测抓到的。
   * 同时它也不随 radius 等比缩放：半径缩小时字高是绝对值。
   */
  const box0 = estimateTextBox('', fontSize)
  const labelGap = box0.ascent + strokeHalf + ringPad
  const L = radius + labelGap

  const angleAt = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n

  // 在「以圆心为原点」的局部系里求并集，最后整体平移到 (pad, pad)。
  // 这样画布由内容决定，且天然支持负原点（无需为越界特判）。
  let minX = -(radius + strokeHalf)
  let minY = -(radius + strokeHalf)
  let maxX = radius + strokeHalf
  let maxY = radius + strokeHalf

  const placed = dims.map((d, i) => {
    const a = angleAt(i)
    const cos = Math.cos(a)
    const x = cos * L
    const y = Math.sin(a) * L
    const anchor = anchorOf(cos)
    const box = estimateTextBox(d.dimension, fontSize)
    const x0 = anchor === 'start' ? x : anchor === 'end' ? x - box.w : x - box.w / 2
    const bbox: [number, number, number, number] = [
      x0,
      y - box.ascent,
      x0 + box.w,
      y + box.descent,
    ]
    minX = Math.min(minX, bbox[0])
    minY = Math.min(minY, bbox[1])
    maxX = Math.max(maxX, bbox[2])
    maxY = Math.max(maxY, bbox[3])
    return { text: d.dimension, x, y, anchor, bbox }
  })

  // ceil 而非 round：亚像素余量不许把标签切掉。
  const width = Math.ceil(maxX - minX + 2 * pad)
  const height = Math.ceil(maxY - minY + 2 * pad)
  const cx = pad - minX
  const cy = pad - minY

  const pointAt = (i: number, k: number): [number, number] => {
    const a = angleAt(i)
    return [cx + Math.cos(a) * radius * k, cy + Math.sin(a) * radius * k]
  }
  const ringPoints = (k: number) =>
    dims.map((_, i) => pointAt(i, k).map(round2).join(',')).join(' ')

  return {
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    cx: round2(cx),
    cy: round2(cy),
    radius,
    labelGap: round2(labelGap),
    fontSize,
    pad,
    rings: RADAR_RING_LEVELS.map((k) => ({ k, points: ringPoints(k) })),
    spokes: dims.map((_, i) => {
      const [x, y] = pointAt(i, 1)
      return { x1: round2(cx), y1: round2(cy), x2: round2(x), y2: round2(y) }
    }),
    // 不钳位 score：值域由 `poi.py:172/312` 的 min(1.0, …) 与 `_cat_score` 双向保证，
    // 越界属于上游契约违规，应当画成可见的坏图而不是在几何层静默归一。
    dataPoints: dims
      .map((d, i) => pointAt(i, d.score / 100).map(round2).join(','))
      .join(' '),
    labels: placed.map((p) => ({
      text: p.text,
      x: round2(p.x + cx),
      y: round2(p.y + cy),
      anchor: p.anchor,
      bbox: p.bbox.map((v, j) => round2(v + (j % 2 === 0 ? cx : cy))) as [
        number,
        number,
        number,
        number,
      ],
    })),
  }
}

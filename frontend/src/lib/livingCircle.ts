/**
 * 常青圈 · 生活圈工具库（类型无关的纯函数 + 常量）。
 *
 * 单一实现来源：地图页 / 报告页快照 / 对比页共用同一套投影与配色，
 * 避免各页面各自复制一份「m 等距投影 → 像素」逻辑造成画布不一致。
 * M 阶段 BMapGL 接入后仅替换渲染层，投影语义保持不变。
 */
import type { LngLat } from '../types'

/* 画布几何：研究范围 5km × 5km → 画布 W×H（m 等距投影局部近似，单一真相源） */
export const LC_CANVAS = { R: 2500, W: 860, H: 620 } as const

/** POI 类别配色（常青圈地图图例，报告快照共用） */
export const LC_CAT_COLOR: Record<string, string> = {
  market: '#C2642E',
  medical: '#E0483F',
  education: '#2F7FBF',
  shopping: '#8A6BD1',
  elderly: '#C09A2E',
  finance: '#5F8A6A',
  recreation: '#2FA09A',
  service: '#7C6670',
}

/** 类别 label 兜底（与 fixture 的 label 对齐，缺省回退） */
export const LC_CAT_LABEL: Record<string, string> = {
  market: '菜市场',
  medical: '医疗',
  education: '教育',
  shopping: '购物',
  elderly: '养老',
  finance: '金融',
  recreation: '文体',
  service: '政务',
}

/** 等时圈分级配色（5→20 分钟由深到浅）；报告/地图共用 */
export const LC_ISO_COLORS = [
  { fill: 'rgba(124,152,133,0.55)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.34)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.20)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.10)', stroke: '#5F7B69' },
]

/** 中心点 → 米制偏移（等距局部近似，仅用于渲染尺寸，不做地理结算） */
export function lcMeters(center: LngLat, lng: number, lat: number): [number, number] {
  const dLat = lat - center[1]
  const dLng = lng - center[0]
  const mx = dLng * 111320 * Math.cos((center[1] * Math.PI) / 180)
  const my = dLat * 111320
  return [mx, my]
}

export function lcToPx(center: LngLat, lng: number, lat: number): [number, number] {
  const { R, W, H } = LC_CANVAS
  const [mx, my] = lcMeters(center, lng, lat)
  return [W / 2 + (mx / R) * (W / 2), H / 2 - (my / R) * (H / 2)]
}

/** 环 → SVG polygon points */
export function lcPolyPts(center: LngLat, ring: LngLat[]): string {
  return ring.map(([lng, lat]) => lcToPx(center, lng, lat).map((v) => v.toFixed(1)).join(',')).join(' ')
}

/** 环上最靠右的顶点（放 "N min" 标注，避开中心文字） */
export function lcRightmost(center: LngLat, ring: LngLat[]): [number, number] {
  let best = ring[0]
  let bestX = -Infinity
  for (const p of ring) {
    const x = lcToPx(center, p[0], p[1])[0]
    if (x > bestX) {
      bestX = x
      best = p
    }
  }
  return lcToPx(center, best[0], best[1])
}

/** 评分档位文案（体检单 / 历史页共用口径） */
export function scoreGrade(total: number): { label: string; color: string } {
  if (total >= 85) return { label: '优', color: '#2F8F6B' }
  if (total >= 70) return { label: '良', color: '#5f8a6a' }
  if (total >= 55) return { label: '中', color: '#C09A2E' }
  return { label: '差', color: '#C2642E' }
}

export const LC_CAT_LABEL_OF = (key: string, fallback?: string) => LC_CAT_LABEL[key] ?? fallback ?? key
/**
 * 地图图层名册（生产侧唯一清单）· R1。
 *
 * ## 它治的病
 * `LcMap` 有两棵渲染树（live 造 BMapGL 覆盖物、降级画 SVG 图元）。加一个图层就得在两处各写一次
 * 门槛，而**少写一处不会有任何东西报警** —— 本域为这件事写过四次勘误：判定尺当年只补 live 一半
 * （那颗开关在降级态点下去没反应，全套件没人发现）、口径对照环两档各写一遍、形状扇面，以及
 * 10-07 的选中格（图注两档同印「图上带该格的判定尺圆」，降级档其实一枚都没画）。
 *
 * ## 为什么放在生产侧而不是测试里
 * 一份手写的「图层 × 两档」矩阵仍然是第二份清单：加一层时照样得记得去测试里补一行。
 * 这里把**"这一层该不该画"的判定收成一颗函数**，两档的绘制点都必须消费它的返回值 ⇒
 * 声明与实际画出来的东西同源，判据才有资格问"两档是不是同一组层"。
 *
 * ## 申报口（为什么 live 半边能被判据问到）
 * canvas 覆盖物不进 DOM ⇒ 任何 `querySelector` 型判据在 live 档天然失明（10-07 实测踩过：
 * 整页问 `[data-lc-layer]` 在 fallback 全绿、live 必红）。所以由组件把名册**写回 DOM**：
 * live 根节点上的 `data-lc-layers` 记的是"这条 effect 真的建出来了哪些层"（不是猜测），
 * 降级根节点记的是"这棵树按同一份判定渲染出了哪些层"。
 *
 * ⚠️ 名册只收录**已经两档齐**的层；未登记的层不许混进来（否则判据会把"没迁"读成"一致"）。
 */
import type { LngLat, LivingCircleReport, ShapeCaliber } from '../../types'
import { cellLayerPlan } from './CellLayer'
import { isoCompareOf, judgeRulerM } from '../../lib/livingCircle'

/** 已入册的图层。加一层＝在这里加一个名字，并让**两档**的绘制点都消费 `layerRoster`。 */
export const LC_LAYERS = ['judge-ruler', 'iso-compare', 'shape-sectors', 'selected-cell'] as const
export type LcLayer = (typeof LC_LAYERS)[number]

/** 名册的输入：三类信息各管各的 —— 开关（用户意图）、对照态/脱敏（闸）、数据在场性（有没有东西可画）。 */
export interface RosterInput {
  /** 对照态（`compareReport`）：四类解释层在对照图上一律不画 */
  secondary: boolean
  /** 脱敏态（分享链接）：逐格地理边界不许上屏（P0-5） */
  desensitize: boolean
  showJudgeScale: boolean
  showIsoCompare: boolean
  shapeOn: boolean
  /** 数据在场性，逐层一条（取不到尺 / 环未闭合 / 没形状键 / 没台账或越界 ⇒ false） */
  hasRuler: boolean
  hasCompareRing: boolean
  hasShape: boolean
  hasCell: boolean
}

/**
 * 唯一判定：这一层该不该画。两档的绘制点都问它，不再各自把条件抄一遍。
 * 「开关开了但数据取不到」＝整层不出现（缺席即未发生，不摆勾了没反应的入口，也不画 0 半径圈）。
 */
export function layerRoster(i: RosterInput): LcLayer[] {
  if (i.secondary) return []      // 对照图只画四档色阶本体，解释层整批退场
  const out: LcLayer[] = []
  if (i.showJudgeScale && i.hasRuler) out.push('judge-ruler')
  if (i.showIsoCompare && i.hasCompareRing) out.push('iso-compare')
  if (i.shapeOn && i.hasShape) out.push('shape-sectors')
  if (!i.desensitize && i.hasCell) out.push('selected-cell')
  return out
}

/** 排序后的逗号串：稳定、可直接写进 `data-lc-layers`，也让判据能逐字符比较两份申报。 */
export function layerAttr(list: readonly LcLayer[]): string {
  return [...new Set(list)].sort().join(',')
}

/** 读回申报串。未知名字一律丢掉（宁可漏读，也不让脏值冒充一层）。 */
export function parseLayerAttr(raw: string | null | undefined): LcLayer[] {
  if (!raw) return []
  return raw.split(',').map((s) => s.trim()).filter((s): s is LcLayer => (LC_LAYERS as readonly string[]).includes(s))
}

/** 在已建集合上增/删一层，返回新的申报串（live 侧 effect 用它把"真的建出来了"写回 DOM）。 */
export function withLayer(raw: string, name: LcLayer): string {
  return layerAttr([...parseLayerAttr(raw), name])
}
export function withoutLayer(raw: string, name: LcLayer): string {
  return layerAttr(parseLayerAttr(raw).filter((n) => n !== name))
}

/** 对照环的"有东西可画"不止"键在"：环未闭合/点数不足时 live 与降级都不该画（两档同判据）。 */
export function compareRingPresent(lc: LivingCircleReport): boolean {
  const cmp = isoCompareOf(lc)
  if (!cmp) return false
  const ring = cmp.geojson.coordinates[0] ?? []
  return ring.length >= 4 && Math.abs(
    (ring[0] as LngLat)[0] - (ring[ring.length - 1] as LngLat)[0],
  ) < 1e-9 && Math.abs(
    (ring[0] as LngLat)[1] - (ring[ring.length - 1] as LngLat)[1],
  ) < 1e-9
}

/** 数据在场性一次算齐，供 `layerRoster` 用（两档共用同一次计算的结果）。 */
export function rosterFactsOf(
  lc: LivingCircleReport,
  shapeCal: ShapeCaliber | null,
  selectedCell: [number, number] | null,
): Pick<RosterInput, 'hasRuler' | 'hasCompareRing' | 'hasShape' | 'hasCell'> {
  return {
    hasRuler: judgeRulerM(lc) !== null,
    hasCompareRing: compareRingPresent(lc),
    hasShape: shapeCal !== null,
    hasCell: cellLayerPlan(lc, selectedCell) !== null,
  }
}

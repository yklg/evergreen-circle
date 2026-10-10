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
import { cellLayerPlan, cellsGridPlan } from './CellLayer'
import { shapeSectors } from './ShapeSectorOverlay'
import { isoCompareOf, judgeRulerM, shapeOfZone } from '../../lib/livingCircle'

/** 已入册的图层。加一层＝在这里加一个名字，并让**两档**的绘制点都消费 `layerRoster`。 */
export const LC_LAYERS = ['judge-ruler', 'iso-compare', 'shape-sectors', 'selected-cell', 'cells-grid'] as const
export type LcLayer = (typeof LC_LAYERS)[number]

/** 名册的输入：三类信息各管各的 —— 开关（用户意图）、对照态/脱敏（闸）、数据在场性（有没有东西可画）。 */
export interface RosterInput {
  /** 对照态（`compareReport`，同图叠加那一支）：只有 `SECONDARY_LAYERS` 白名单里的层能画 */
  secondary: boolean
  /** 脱敏态（分享链接）：逐格地理边界不许上屏（P0-5） */
  desensitize: boolean
  showJudgeScale: boolean
  showIsoCompare: boolean
  shapeOn: boolean
  /** 整幅格阵（笔3b）：把台账那一页的五档结论画到地图上。与"选中格"是两层，别混。 */
  showCellsGrid: boolean
  /** 数据在场性，逐层一条（取不到尺 / 环未闭合 / 没形状键 / 没台账或越界 ⇒ false） */
  hasRuler: boolean
  hasCompareRing: boolean
  hasShape: boolean
  hasCell: boolean
  hasGrid: boolean
}

/**
 * 唯一判定：这一层该不该画。两档的绘制点都问它，不再各自把条件抄一遍。
 * 「开关开了但数据取不到」＝整层不出现（缺席即未发生，不摆勾了没反应的入口，也不画 0 半径圈）。
 *
 * 对照态（`secondary`）不再整批退场，改成问白名单 —— 见下面 `SECONDARY_LAYERS` 那段。
 */
export function layerRoster(i: RosterInput): LcLayer[] {
  const out: LcLayer[] = []
  const allow = (n: LcLayer) => !i.secondary || SECONDARY_LAYERS.includes(n)
  if (allow('judge-ruler') && i.showJudgeScale && i.hasRuler) out.push('judge-ruler')
  if (allow('iso-compare') && i.showIsoCompare && i.hasCompareRing) out.push('iso-compare')
  if (allow('shape-sectors') && i.shapeOn && i.hasShape) out.push('shape-sectors')
  if (allow('selected-cell') && !i.desensitize && i.hasCell) out.push('selected-cell')
  // 格阵与选中格同一条脱敏闸：逐格地理边界在分享态一律不许上屏（P0-5）。
  if (allow('cells-grid') && !i.desensitize && i.showCellsGrid && i.hasGrid) out.push('cells-grid')
  return out
}

/**
 * 对照态（同图叠加那一支）的白名单 —— 笔 3c。
 *
 * 为什么只有这三层进得来：
 *  · `judge-ruler` —— 这一支今天根本没有第四颗勾（`ComparePage` 不给 `showJudgeScale` 传值），
 *    白名单里放它等于放一层"永远画不出"的东西。**2026-10-10 已拍：不加勾，留在白名单外**（结案）。
 *    理由与横幅那两句同源：两份件的判定尺不同，本质是**口径不同**，该由横幅/差异表那句人说
 *    （`compareCaliberNotices` 已按四根轴各一句），而不是靠图上多一个圆；而加勾是新增用户可见
 *    交互面，不是补一个缺失的显示。要重开这条，先回答"读者在叠图上看这把尺要做什么决定"。
 *  · `selected-cell` —— 它的格界是真实米制（P0-5 那条闸管的就是这个），且"点一格"在两张报告
 *    叠在一起的图上归属未定；选中格留在对照态之外。
 *  · 其余三层是"把已有的结论画在已有坐标上"，与 A/B 双色等时圈同性质。
 */
export const SECONDARY_LAYERS: readonly LcLayer[] = ['iso-compare', 'shape-sectors', 'cells-grid']

/** 同框图上一颗图层的**实例**：画几枚、这几枚各归哪一侧、几何出自哪一侧。 */
export interface FrameInstance {
  layer: LcLayer
  /** 这一枚服务哪几侧。`['a','b']` ＝ 两侧同值、只画一枚（`merged`）。 */
  sides: Array<'a' | 'b'>
  /** 几何出自哪一份载荷（合枚时取 A 侧 —— 同值才合，取哪侧画出来一样）。 */
  source: 'a' | 'b'
}

export interface FramePlan {
  /** 绘制清单：两档（live 覆盖物 / 降级 SVG 图元）都必须照这一份画，不许各自再判一次。 */
  instances: FrameInstance[]
  /** 逐侧申报（写进 `data-lc-layers-a` / `-b`）：合枚那枚同时算进两侧。 */
  declared: Record<'a' | 'b', LcLayer[]>
  /** 某一侧整层不出现（没发这一层）⇒ 图注要显式写"没发"，不许被读成"这一侧没有"。 */
  absent: Array<{ layer: LcLayer; side: 'a' | 'b' }>
}

/** 开关与选中态：`framePlanOf` 按侧各问一次 `layerRoster`，所以吃的是同一组输入。 */
export interface FrameSwitches {
  showJudgeScale: boolean
  showIsoCompare: boolean
  shapeOn: boolean
  showCellsGrid: boolean
  selectedCell: [number, number] | null
}

/** 两侧申报属性名：一张图一份申报在对照态就不够用了（层名不再能说归谁）。 */
export const LAYER_ATTR_BY_SIDE: Record<'a' | 'b', string> = {
  a: 'data-lc-layers-a',
  b: 'data-lc-layers-b',
}

/** 画出来的几何是否同位同值 —— 只比**这一层真正会画的东西**，不比整份载荷。 */
function sameDrawnGeometry(layer: LcLayer, a: LivingCircleReport, b: LivingCircleReport): boolean {
  const key = (v: unknown) => JSON.stringify(v)
  if (layer === 'iso-compare') {
    const ca = isoCompareOf(a)
    const cb = isoCompareOf(b)
    return ca !== null && cb !== null && key(ca.geojson.coordinates[0]) === key(cb.geojson.coordinates[0])
  }
  if (layer === 'shape-sectors') {
    const sa = shapeOfZone(a, 15)
    const sb = shapeOfZone(b, 15)
    return sa !== null && sb !== null
      && key(shapeSectors(a.scene.center, sa)) === key(shapeSectors(b.scene.center, sb))
  }
  if (layer === 'cells-grid') {
    const ga = cellsGridPlan(a)
    const gb = cellsGridPlan(b)
    return ga !== null && gb !== null && key(ga) === key(gb)
  }
  return false      // 白名单之外的层不参与合枚（走到这里＝调用方给错了层，宁可各画各的）
}

/**
 * 同框图的绘制清单。`b === null` 时是普通单图（每层一枚、只归 A）；
 * 有 `b` 时每层按"两侧各自该不该画 + 画出来是否同值"决定一枚还是两枚。
 *
 * 为什么要"同值只画一枚"：这一支今天已经有一处两侧同形 —— A 绿四档先铺、B 蓝四档后画，
 * 重合处屏上只剩蓝（`LcMap:740` 的绘制顺序）。解释层若照同样手法画两枚，"换色区分两侧"
 * 买到的是零信息，还得为同一枚形状再造一套结论色（五档色表是语义表，见 `CellLayer`）。
 */
export function framePlanOf(
  a: LivingCircleReport,
  b: LivingCircleReport | null,
  sw: FrameSwitches,
  desensitize: boolean,
): FramePlan {
  const rosterOf = (lc: LivingCircleReport, secondary: boolean): LcLayer[] =>
    layerRoster({
      secondary,
      desensitize,
      showJudgeScale: sw.showJudgeScale,
      showIsoCompare: sw.showIsoCompare,
      shapeOn: sw.shapeOn,
      showCellsGrid: sw.showCellsGrid,
      ...rosterFactsOf(lc, shapeOfZone(lc, 15), sw.selectedCell, sw.showCellsGrid),
    })
  const ra = rosterOf(a, b !== null)
  if (b === null) {
    return {
      instances: ra.map((layer): FrameInstance => ({ layer, sides: ['a'], source: 'a' })),
      declared: { a: ra, b: [] },
      absent: [],
    }
  }
  const rb = rosterOf(b, true)
  const instances: FrameInstance[] = []
  const absent: FramePlan['absent'] = []
  for (const layer of LC_LAYERS) {
    const inA = ra.includes(layer)
    const inB = rb.includes(layer)
    if (!inA && !inB) continue
    if (inA && inB) {
      if (sameDrawnGeometry(layer, a, b)) instances.push({ layer, sides: ['a', 'b'], source: 'a' })
      else instances.push({ layer, sides: ['a'], source: 'a' }, { layer, sides: ['b'], source: 'b' })
    } else if (inA) {
      instances.push({ layer, sides: ['a'], source: 'a' })
    } else {
      instances.push({ layer, sides: ['b'], source: 'b' })
    }
    if (inA && !inB) absent.push({ layer, side: 'b' })
    if (inB && !inA) absent.push({ layer, side: 'a' })
  }
  const declaredFor = (side: 'a' | 'b') =>
    instances.filter((i) => i.sides.includes(side)).map((i) => i.layer)
  return { instances, declared: { a: declaredFor('a'), b: declaredFor('b') }, absent }
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
  showCellsGrid = false,
): Pick<RosterInput, 'hasRuler' | 'hasCompareRing' | 'hasShape' | 'hasCell' | 'hasGrid'> {
  return {
    hasRuler: judgeRulerM(lc) !== null,
    hasCompareRing: compareRingPresent(lc),
    hasShape: shapeCal !== null,
    hasCell: cellLayerPlan(lc, selectedCell) !== null,
    hasGrid: showCellsGrid && cellsGridPlan(lc) !== null,
  }
}

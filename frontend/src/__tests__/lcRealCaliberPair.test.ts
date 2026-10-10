/**
 * 真件对（代次前存量件 × 当代重跑件）· 3c 三态与横幅措辞的常驻判据。
 *
 * ## 为什么要有这份文件
 * 3c 把对照态名册从"整批退场"换成白名单后，三条规则（同值合枚 / 一侧没发 / 不同值各一枚）
 * 的证据只有两种：出厂夹具（两份都是代次后的件）与合成件（`lcLayerRoster` 里那枚
 * `SHIFTED_RING`）。2026-10-10 真跑三发之后，库里出现了**一对真实会点到的同框件**：
 * `lc-29eab473`（09-30，代次前）× `lc-59cc764b`（当天重跑，`rc-1/cov-1/sh-2`）。
 * 这一把把三种态一次占全 —— 现在钉进 CI，不再依赖"某次真跑还在库里"。
 *
 * ## 裁剪与自证
 * `helpers/realCaliberPair.json` 是两份真件的**裁剪副本**（40KB vs 原件 317KB，删的是
 * `sampling` 等大数组）。下面"前提"那组断言先钉住裁剪没把语义钉丢：A 确实没发
 * `iso_compare`、三根戳确实是 None、两份格阵位阵确实逐字节相同、两份 15min 环确实不同值。
 * 而 `gapDesc` 与 `instances` 那两句**逐字**是在未裁剪的原件上实测过一遍才抄下来的
 * （见 `预览-对照态两侧同框-2026-10-10/取证结论.md`）—— 前提一旦被改，
 * 这三条里必有一条先红，不会静默换成自证。
 */
import { describe, expect, it } from 'vitest'
import pair from './helpers/realCaliberPair.json'
import { CALIBER_AXES, caliberGapDesc, compareCaliberNotices, type CaliberAxis } from '../lib/livingCircle'
import { framePlanOf } from '../components/lifecircle/lcLayers'
import type { LivingCircleReport } from '../types'

const A = pair.a as unknown as LivingCircleReport
const B = pair.b as unknown as LivingCircleReport
const SW = { showJudgeScale: false, showIsoCompare: true, shapeOn: true, showCellsGrid: true, selectedCell: null }

describe('真件对的前提（裁剪件必须还是那对真件，否则下面的判据全在自证）', () => {
  it('A 是代次前那份：没发对照环，三根戳一律 None', () => {
    expect(A.iso_compare, 'A 现在带着对照环 ⇒ 这份裁剪件已不是 09-30 那件').toBeFalsy()
    for (const k of ['reach_caliber_version', 'coverage_caliber_version', 'shape_caliber_version'] as const)
      expect(A.caliber?.[k] ?? null, `A 的 caliber.${k} 不再是"根本没发这个键"`).toBe(null)
  })
  it('B 是当代那份：对照环与三根戳都发齐', () => {
    expect(B.iso_compare?.area_km2, 'B 的对照环读数漂了').toBe(0.255)
    expect([B.caliber?.reach_caliber_version, B.caliber?.coverage_caliber_version, B.caliber?.shape_caliber_version])
      .toEqual(['rc-1', 'cov-1', 'sh-2'])
  })
  it('两份格阵同尺同格且**七张位阵逐字节相同**（这才是"合枚"的依据，不是猜的）', () => {
    const la = A.caliber!.cells_ledger as unknown as Record<string, string[]>
    const lb = B.caliber!.cells_ledger as unknown as Record<string, string[]>
    expect([la.n, la.step_m, la.center]).toEqual([lb.n, lb.step_m, lb.center])
    const bits = Object.keys(la).filter((k) => Array.isArray(la[k]) && (la[k] as string[]).every((row) => /^[01]+$/.test(row)))
    expect(bits.length, '位阵张数不是七张 ⇒ 台账结构换代，本文件的锚要重取').toBe(7)
    for (const k of bits) expect(la[k], `位阵 ${k} 两份不再相同`).toEqual(lb[k])
  })
  it('两份 15min 环**不同值**（面积 1.562 vs 1.568）：等时圈那一层该各画各的', () => {
    const za = A.isochrones.find((z) => z.minutes === 15)!
    const zb = B.isochrones.find((z) => z.minutes === 15)!
    // 裁剪件没留 `geojson`（那是 91 个顶点的大数组），所以这里钉的是**读数**不同值；
    // 逐顶点是否重合由未裁剪原件那次实测背书（见文件头与取证结论.md）。
    expect([za.area_km2, zb.area_km2]).toEqual([1.562, 1.568])
    expect(za.area_km2).not.toBe(zb.area_km2)
  })
})

describe('真件对 · 横幅那句不可比（代次前 × 当代）', () => {
  it('三根轴全报，且顺序恒为登记表的顺序 —— 不是只报第一根', () => {
    expect(caliberGapDesc(A, B)).toBe(
      '不可比 · 评分口径已升级（点数 → 门槛项）、可达口径已升级（耗时场新增常态绕行与残差解释）、形状口径已升级（等时圈新增八方位诊断尺）',
    )
  })
  it('反过来问同一句（横幅不该按 A/B 顺序变词序）', () => {
    expect(caliberGapDesc(B, A)).toBe(caliberGapDesc(A, B))
  })
  // ↓ 2026-10-10 L0 现形的缺口补的这条：行出口 `caliberGapDesc` 早就是四根轴全报，
  //   页出口 `compareCaliberNotices` 却只拼 ev + cov ⇒ 真件对打开时横幅少两句，
  //   而这一对**正是**用户真会点到的态（两份 ev 相同、cov/rc/sh 三根不同）。
  //   判据写成"整串逐字 + 数量"而非"包含某句"：少一句、多一句、串了序都要红。
  it('横幅真出口在这对上给三句（评分/可达/形状），且**不报判盲那句**（两份都是 ev-2）', () => {
    const notices = compareCaliberNotices(A, B)
    expect(notices.map((n) => n.slice(0, 8))).toEqual(['两侧评分口径不同', '两侧可达口径不同', '两侧形状口径不同'])
    expect(notices.join('')).not.toContain('判盲')
  })
  it('新补的这两句里"升级了什么"那半句逐字来自登记表（cov/ev 那两句是登记表之前的手写措辞，本次没动）', () => {
    const notices = compareCaliberNotices(A, B)
    for (const ax of ['rc', 'sh'] as CaliberAxis[]) {
      const clause = CALIBER_AXES.find((s) => s.axis === ax)!.clause
      expect(notices.some((n) => n.includes(clause)), `横幅缺 ${ax} 那根轴的登记子句`).toBe(true)
    }
  })
})

describe('真件对 · 3c 按侧清单（三种态被同一对真件占全）', () => {
  const fp = framePlanOf(A, B, SW, false)
  it('格阵两侧逐字节相同 ⇒ 合一枚、归两侧；对照环与方位形状只有 B 侧发得出 ⇒ 各一枚且记缺席', () => {
    expect(fp.instances.map((i) => `${i.layer}:${i.sides.join('+')}`))
      .toEqual(['iso-compare:b', 'shape-sectors:b', 'cells-grid:a+b'])
  })
  it('两侧申报各自成立（A 那份只有格阵，B 那份三层齐）', () => {
    expect(fp.declared.a).toEqual(['cells-grid'])
    // 清单顺序恒为 `LC_LAYERS` 的顺序（写进 DOM 时才由 `layerAttr` 排序去重）
    expect(fp.declared.b).toEqual(['iso-compare', 'shape-sectors', 'cells-grid'])
  })
  it('缺席是"没发这一层"，不是"这一侧没有"：两条缺席记录点名到层', () => {
    expect(fp.absent).toEqual([{ layer: 'iso-compare', side: 'a' }, { layer: 'shape-sectors', side: 'a' }])
  })
  it('判定尺与选中格仍旧不进对照态白名单（这一对 A 侧有盲区、B 侧也有 ⇒ 若放开就该出现）', () => {
    expect(A.blindspots.length).toBeGreaterThan(0)
    expect(fp.instances.map((i) => i.layer)).not.toContain('judge-ruler')
    expect(fp.instances.map((i) => i.layer)).not.toContain('selected-cell')
  })
})

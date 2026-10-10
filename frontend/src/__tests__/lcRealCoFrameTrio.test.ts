/**
 * 真件三件（同中心重跑 × 东移 2486 m × 代次前存量）· **真实态同框那一支**的常驻判据。
 *
 * ## 为什么要有这份文件
 * 对比页走"一张图叠加"还是"两张图各居其城"，只看两份件中心距是否 ≤ `LC_CO_LOCATED_M`(4000 m)。
 * 2026-10-10 之前库里选择器可见的四份**两两最近 14,014 m**（现算，haversine）⇒ 3c 那套
 * "同值只画一枚 / 没发显式缺席 / 不同值各一枚"在**真实数据**上从没被走到过，只有 jsdom 合成件
 * 与演示态夹具背书。当天 `force=true` 真跑两发（绕 `CachingDataSource` 的就近复用）造出三件 ≤4 km 的件，
 * 三对正好各占一态 —— 这一把把它钉进 CI，不再依赖"某次真跑还在库里"。
 *
 * ## 三对与各自钉住的那一态
 * | 对 | 中心距 | 钉住 |
 * |---|---|---|
 * | `a`(09-30 存量) × `b`(同中心重跑) | 0 m | 七张位阵逐字节全等 ⇒ **格阵合一枚且归两侧**；a 没发对照环与形状 ⇒ 那两层只有 b 一枚 |
 * | `b` × `c`(东移件) | 2486 m | 两侧都发三层、格阵**不同几何**（step 195.3 vs 175.5）⇒ **每层各一枚**，无缺席 |
 * | `a` × `c` | 2486 m | 合枚与缺席**同屏**：格阵各一枚，环与形状只有 b |
 *
 * ## 裁剪与自证
 * `helpers/realCoFrameTrio.json` 是三份真件的裁剪副本（102 KB vs 原件 464 KB，删 `sampling` 与
 * `isochrones[].geojson`）。裁剪会不会把语义裁掉，不由这份文件的作者说：一次性台架
 * `tmp_pruneSelfproof`（跑完即删，依赖 `/tmp/coframe_full.json`）拿**未裁剪原件**与**裁剪件**
 * 各喂一遍 `framePlanOf` / `compareCaliberNotices` / `lcCoLocated`，10 条逐字相同才落的盘。
 * 下面"前提"那组再把三件的身份钉死 —— 前提一旦被改，必有一条先红，不会静默换成自证。
 *
 * ## 这一态仍然没有实物（明写，别当已覆盖）
 * "同尺同格 + 同一格结论相反"造不出来：同中心重跑 ⇒ 格心/`n`/`step` 全同、七张位阵逐字节全等，
 * 要打架得有"格心不变而三个判盲词（菜市场/药店/小学）的 1km 命中发生变化"。
 * 该态继续只有合成件（`lcLayerRoster.test.tsx` 的 `SHIFTED_RING`）。
 */
import { describe, expect, it } from 'vitest'
import trio from './helpers/realCoFrameTrio.json'
import { framePlanOf } from '../components/lifecircle/lcLayers'
import { compareCaliberNotices, lcCoLocated } from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

const R = { a: trio.a, b: trio.b, c: trio.c } as unknown as Record<'a' | 'b' | 'c', LivingCircleReport>
const SW = { showJudgeScale: false, showIsoCompare: true, shapeOn: true, showCellsGrid: true, selectedCell: null }
const plan = (x: 'a' | 'b', y: 'a' | 'b' | 'c') => framePlanOf(R[x], R[y], SW, false)
const inst = (x: 'a' | 'b', y: 'a' | 'b' | 'c') => plan(x, y).instances.map((i) => `${i.layer}:${i.sides.join('+')}`)
const ledger = (k: 'a' | 'b' | 'c') => R[k].caliber!.cells_ledger as unknown as Record<string, string[]>
const masks = (k: 'a' | 'b' | 'c') => Object.keys(ledger(k)).filter(
  (key) => Array.isArray(ledger(k)[key]) && (ledger(k)[key] as string[]).every((row) => /^[01]+$/.test(row)))
/** 位阵里"1"的个数＝台账那页的格数（**逐字符数**，不是"含 1 的行数"——后者最多只有 n 行，会把 72 读成 15）。 */
const ones = (rows: string[]) => rows.reduce((s, r) => s + [...r].filter((c) => c === '1').length, 0)

describe('真件三件 · 前提（裁剪件必须还是那三件真跑件，否则下面的判据全在自证）', () => {
  it('a 是代次前那份：三根戳一律没发、对照环没发，但**台账有**（"没发这一层"不等于"这一侧没有"）', () => {
    for (const k of ['coverage_caliber_version', 'reach_caliber_version', 'shape_caliber_version'] as const)
      expect(R.a.caliber?.[k] ?? null, `a 的 caliber.${k} 不再是"根本没发这个键"`).toBe(null)
    expect(R.a.iso_compare, 'a 现在带着对照环 ⇒ 已不是 09-30 那件').toBeFalsy()
    expect(masks('a'), 'a 的台账位阵张数变了 ⇒ 本文件锚要重取').toHaveLength(7)
  })
  it('b 与 a **逐字同中心**（同框那一支的真实件入口），且三层全发', () => {
    expect(R.b.scene.center).toEqual(R.a.scene.center)
    expect(lcCoLocated(R.a.scene.center, R.b.scene.center), '同中心却判不同框 ⇒ 取景闸本身变了').toBe(true)
    expect(R.b.iso_compare?.area_km2).toBe(0.255)
    expect([R.b.caliber?.reach_caliber_version, R.b.caliber?.coverage_caliber_version, R.b.caliber?.shape_caliber_version])
      .toEqual(['rc-1', 'cov-1', 'sh-2'])
  })
  it('c 是东移件：中心不同、**格阵不同几何**（step 175.5 ≠ 195.3、圈内格 44 ≠ 72）', () => {
    expect(R.c.scene.center).not.toEqual(R.b.scene.center)
    expect(lcCoLocated(R.b.scene.center, R.c.scene.center), '东移件已超出 4 km ⇒ "同框"这一态的入口没了').toBe(true)
    expect([ledger('b').n, ledger('b').step_m, ones(ledger('b').inside)]).toEqual([15, 195.3, 72])
    expect([ledger('c').n, ledger('c').step_m]).toEqual([15, 175.5])
    expect(ones(ledger('c').inside)).toBe(44)
  })
  it('a × b 的七张位阵**逐字节全等**（这才是"合枚"的依据，不是猜的）', () => {
    for (const k of masks('a')) expect(ledger('a')[k], `位阵 ${k} 两份不再相同`).toEqual(ledger('b')[k])
  })
})

describe('真件三件 · 三对各占一态（逐字抄自真浏览器那一遍，见 `L0-同框/`）', () => {
  it('甲 b × c：两侧都发三层且格阵不同几何 ⇒ 每层各一枚、没有缺席、也没人归两侧', () => {
    expect(inst('b', 'c')).toEqual([
      'iso-compare:a', 'iso-compare:b', 'shape-sectors:a', 'shape-sectors:b', 'cells-grid:a', 'cells-grid:b',
    ])
    expect(plan('b', 'c').absent).toEqual([])
    expect(plan('b', 'c').declared).toEqual({ a: ['iso-compare', 'shape-sectors', 'cells-grid'], b: ['iso-compare', 'shape-sectors', 'cells-grid'] })
  })
  it('乙 a × b：格阵七张位阵全等 ⇒ 合一枚且归两侧；对照环与形状 a 侧没发 ⇒ 各只有 b 一枚并点名缺席', () => {
    expect(inst('a', 'b')).toEqual(['iso-compare:b', 'shape-sectors:b', 'cells-grid:a+b'])
    expect(plan('a', 'b').absent).toEqual([{ layer: 'iso-compare', side: 'a' }, { layer: 'shape-sectors', side: 'a' }])
    expect(plan('a', 'b').declared).toEqual({ a: ['cells-grid'], b: ['iso-compare', 'shape-sectors', 'cells-grid'] })
  })
  it('丙 a × c：合枚与缺席同屏 —— 格阵各一枚（不同几何），环与形状只有 b', () => {
    expect(inst('a', 'c')).toEqual(['iso-compare:b', 'shape-sectors:b', 'cells-grid:a', 'cells-grid:b'])
  })
  it('横幅句数与"哪几根轴不同"一致：b×c 同代次 ⇒ 0 句；含 a 的两对 ⇒ 评分/可达/形状三句（判盲同值不报）', () => {
    expect(compareCaliberNotices(R.b, R.c)).toEqual([])
    for (const other of ['b', 'c'] as const) {
      const got = compareCaliberNotices(R.a, R[other])
      expect(got.map((s) => s.slice(0, 8))).toEqual(['两侧评分口径不同', '两侧可达口径不同', '两侧形状口径不同'])
      expect(got.join('')).not.toContain('判盲')
    }
  })
})

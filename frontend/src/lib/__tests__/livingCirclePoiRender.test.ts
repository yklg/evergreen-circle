// 阶段 2 · 渲染层去截断 + POI 渲染点集单一入口（R4 补测）
//
// 本文件钉住四件事，每件都对应一处**已修掉的真实缺陷**：
//  ① 渲染层不得再有静态数量上限（旧 `lcSnapshotPoiLayer` 默认 cap=120、
//     LcMap 降级画布 60、live `POI_MARKER_CAP=120`）—— 它们是「报告说有 98 处、
//     图上只画 N 个」的第二权威；
//  ② `poiRenderSet()` 是**三处渲染入口的唯一取数口**，且必须是**纯函数**
//     （否则 live/降级画布/报告页快照会各画一份不同的点集）；
//  ③ 聚合（阶段 2.4）**只收拢显示、不丢点**：Σ簇计数 === 下发点数；
//  ④ `poiMetricLabel()` 三段式口径与**后端逐字一致**（靠同一份 fixture 的同一期望串对齐）。
import { describe, it, expect } from 'vitest'
import type { LngLat, PoiPoint } from '../../types'
import {
  LC_CANVAS,
  lcSnapshotPoiLayer,
  POI_THIN_CELL_M,
  POI_THIN_THRESHOLD,
  poiMetricLabel,
  poiRenderSet,
  poiThinNote,
} from '../livingCircle'
import kaili from '../../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../../mocks/fixtures/livingCircle/beijing-jinsong.json'

const CENTER = kaili.scene.center as LngLat
const KAILI_POINTS = kaili.poi.points as PoiPoint[]

/** 在中心点附近造 n 个点：`stepDeg` 控制密集程度（越小越挤）。 */
function makePoints(n: number, stepDeg = 0.00012): PoiPoint[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `p-${i}`,
    name: `测点${i}`,
    category: i % 2 === 0 ? 'market' : 'medical',
    lnglat: [CENTER[0] + stepDeg * (i % 10), CENTER[1] + stepDeg * Math.floor(i / 10)],
    minutes: i % 3 === 0 ? null : 3 + i * 0.1,
    in_circle: i % 5 !== 0,
  }))
}

describe('阶段 2.3 · lcSnapshotPoiLayer 默认不再截断', () => {
  it('150 个点时全部投影（旧默认 cap=120 会砍掉 30 个）', () => {
    const pts = makePoints(150)
    const dots = lcSnapshotPoiLayer(CENTER, pts)
    expect(dots).toHaveLength(150)
    // 显式声明 cap 时仍按调用方意图截断（能力保留，只是不再有**默认**截断）
    expect(lcSnapshotPoiLayer(CENTER, pts, 120)).toHaveLength(120)
  })

  it('夹具全量投影（kaili 98 / jinsong 104），且 cluster 缺省为 1', () => {
    expect(lcSnapshotPoiLayer(CENTER, KAILI_POINTS)).toHaveLength(98)
    expect(lcSnapshotPoiLayer(CENTER, KAILI_POINTS).every((d) => d.cluster === 1)).toBe(true)
  })

  it('传入聚合计数时，圆点带出自己的簇大小（hover 文案据此披露）', () => {
    const pts = makePoints(10)
    const counts = new Map([['p-3', 7]])
    const dots = lcSnapshotPoiLayer(CENTER, pts, Number.POSITIVE_INFINITY, counts)
    expect(dots.find((d) => d.key.startsWith('p-3-'))!.cluster).toBe(7)
    expect(dots.find((d) => d.key.startsWith('p-4-'))!.cluster).toBe(1)
  })
})

describe('阶段 2.4 · poiRenderSet 渲染点集（唯一入口）', () => {
  it('常规量级（≤ 阈值）原样全画：reps === points，thinned=false', () => {
    const set = poiRenderSet(KAILI_POINTS)
    expect(set.handed).toBe(98)
    expect(set.shown).toBe(98)
    expect(set.reps).toHaveLength(98)
    expect(set.thinned).toBe(false)
    expect([...set.counts.values()].every((n) => n === 1)).toBe(true)
    expect(poiThinNote(set)).toBeNull()
  })

  it('空 / undefined → 空点集，不抛、不误报聚合', () => {
    for (const v of [[], undefined, null]) {
      const set = poiRenderSet(v as PoiPoint[] | undefined)
      expect(set.shown).toBe(0)
      expect(set.handed).toBe(0)
      expect(set.thinned).toBe(false)
      expect(poiThinNote(set)).toBeNull()
    }
  })

  it('超阈值时按地理网格聚合，**只收拢、不丢点**（Σ簇计数 === 下发点数）', () => {
    const pts = makePoints(POI_THIN_THRESHOLD + 100, 0.00002) // 2m 级间距 ⇒ 同格大量重叠
    const set = poiRenderSet(pts)
    expect(set.handed).toBe(POI_THIN_THRESHOLD + 100)
    expect(set.thinned).toBe(true)
    expect(set.shown).toBeLessThan(set.handed)
    // 不变量：一个点都没丢，只是收进了代表点的簇计数
    expect([...set.counts.values()].reduce((s, n) => s + n, 0)).toBe(set.handed)
    expect([...set.counts.keys()].length).toBe(set.shown)
    // 聚合必须被披露（静默聚合 = 静默截断换了个名字）
    expect(poiThinNote(set)).toContain(`${set.handed} 处`)
    expect(poiThinNote(set)).toContain(`${POI_THIN_CELL_M}m`)
  })

  it('聚合是**纯函数且确定性**：同一输入永远同一 reps / 同一顺序', () => {
    const pts = makePoints(POI_THIN_THRESHOLD + 50, 0.00002)
    const a = poiRenderSet(pts)
    const b = poiRenderSet([...pts])
    expect(a.reps.map((p) => p.id)).toEqual(b.reps.map((p) => p.id))
    // 顺序必须跟随原序（三个渲染入口绘制顺序一致，避免同图不同叠放）
    const order = new Map(pts.map((p, i) => [p.id, i]))
    const idx = a.reps.map((p) => order.get(p.id)!)
    expect(idx).toEqual([...idx].sort((x, y) => x - y))
  })

  it('代表点优先选「圈内 + 耗时更短」的点（聚拢不改变读者第一印象）', () => {
    // 在一处**远离其余点**的格子里放：一个圈外 40min 点 + 一个圈内 5min 点
    // ⇒ 代表点必须是后者（簇计数 2），前者不单独占一个标记。
    const anchor: [number, number] = [CENTER[0] + 0.02, CENTER[1] + 0.02]
    const far: PoiPoint = { id: 'far', name: '远', category: 'market', lnglat: anchor, minutes: 40, in_circle: false }
    const near: PoiPoint = { id: 'near', name: '近', category: 'market', lnglat: [anchor[0] + 0.00001, anchor[1]], minutes: 5, in_circle: true }
    const filler = makePoints(POI_THIN_THRESHOLD + 1, 0.00002)
    const set = poiRenderSet([far, ...filler, near])
    expect(set.counts.get('near')).toBe(2)
    expect(set.counts.has('far')).toBe(false)
  })

  it('阈值是「永不触发的安全阀」而非新口径：当前两份夹具都远低于它', () => {
    expect(POI_THIN_THRESHOLD).toBeGreaterThan(300)
    expect(KAILI_POINTS.length).toBeLessThan(POI_THIN_THRESHOLD)
    expect((jinsong.poi.points as PoiPoint[]).length).toBeLessThan(POI_THIN_THRESHOLD)
  })
})

describe('阶段 2.5 · poiMetricLabel 三段式口径', () => {
  it('与后端逐字同口径：kaili 采集 217 · 圈内 98 · 已展示 98', () => {
    expect(poiMetricLabel(kaili as never)).toBe('采集 217 · 圈内 98 · 已展示 98')
  })

  it('jinsong 采集 175 · 圈内 104 · 已展示 104（同一实现，两城市一致）', () => {
    expect(poiMetricLabel(jinsong as never)).toBe('采集 175 · 圈内 104 · 已展示 104')
  })

  it('三个数各有来源，不是同一个数抄三遍', () => {
    const label = poiMetricLabel(kaili as never)
    const [, total, declared, actual] = label.match(/采集 (\d+) · 圈内 (\d+) · 已展示 (\d+)/)!.map(Number)
    expect(total).toBe((kaili.poi as { total: number }).total)
    expect(declared).toBe(
      (kaili.poi.categories as { in_circle: number }[]).reduce((s, c) => s + c.in_circle, 0),
    )
    expect(actual).toBe(KAILI_POINTS.length)
  })

  it('仅当装配层真的截断过，才出现第四段（且带类别明细与上限）', () => {
    const truncated = {
      poi: {
        categories: [{ category: 'shopping', in_circle: 25 }],
        total: 500,
        in_circle: 25,
        points: KAILI_POINTS.slice(0, 25),
        truncated: {
          cap_per_cat: 200,
          dropped: 6,
          categories: [{ category: 'shopping', kept: 25, dropped: 6 }],
        },
      },
    }
    const label = poiMetricLabel(truncated as never)
    expect(label).toContain('采集 500 · 圈内 25 · 已展示 25')
    expect(label).toContain('另有 6 处未展示')
    expect(label).toContain('shopping 6')
    expect(label).toContain('每类上限 200')
    // 未截断（dropped=0）时不得出现第四段
    expect(poiMetricLabel(kaili as never)).not.toContain('另有')
  })

  it('不读 poi.in_circle 自我声明，而是重算 categories（阶段 1 教训）', () => {
    const lying = {
      poi: {
        categories: [{ category: 'shopping', in_circle: 25 }],
        total: 500,
        in_circle: 999, // 冗余字段谎报 —— 文案必须无视它
        points: KAILI_POINTS.slice(0, 25),
        truncated: { cap_per_cat: 200, dropped: 0, categories: [] },
      },
    }
    expect(poiMetricLabel(lying as never)).toBe('采集 500 · 圈内 25 · 已展示 25')
  })
})

describe('阶段 2 · 画布无关性（三个渲染入口能对上的前提）', () => {
  it('投影点落在画布范围内的比例 = 100%（点数不被画布裁剪）', () => {
    const dots = lcSnapshotPoiLayer(CENTER, KAILI_POINTS)
    const inside = dots.filter(
      (d) => d.cx >= 0 && d.cx <= LC_CANVAS.W && d.cy >= 0 && d.cy <= LC_CANVAS.H,
    )
    expect(inside).toHaveLength(dots.length)
  })
})

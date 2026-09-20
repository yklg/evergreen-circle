// F · 生活圈「共享 POI 投影层」单元测试（覆盖方案 TC-01..06）
// ⚠️ TDD 红线：本文件按**目标 API** 断言 `lcSnapshotPoiLayer`，该导出在
//    lib/livingCircle.ts 尚未实现（C2 改动未落地）。当前运行会因
//    「does not provide an export named 'lcSnapshotPoiLayer'」直接红，
//    这是有意为之的红线——实施 C2 共享层后本文件自动转绿。
//
// 守护契约：
//  - INV-投影：输出与 `lcToPx` 完全同口径（报告快照 / LcMap 降级画布同源）
//  - EQ-空集合：空数组 / undefined → []  不抛
//  - BD-cap：只取前 N 点，不越界
//  - EX-坐标守卫：lnglat 缺失 / 非数组 / NaN 的脏点被过滤，绝不外溢画布
//  - INV-key：key 唯一（同 id 不同坐标也不撞）+ 未知类别兜底色
import { describe, it, expect } from 'vitest'
import type { LngLat, PoiPoint } from '../../types'
import { LC_CANVAS, lcToPx, lcSnapshotPoiLayer } from '../livingCircle'
import kaili from '../../mocks/fixtures/livingCircle/kaili.json'

const CENTER = kaili.scene.center as LngLat
const POINTS = kaili.poi.points as PoiPoint[]

/** 构造一个合法 POI 点（缺省值保证字段类型正确）。 */
function poi(over: Partial<PoiPoint> & { id: string; lnglat: [number, number] }): PoiPoint {
  return {
    name: over.name ?? '测点',
    category: over.category ?? 'market',
    minutes: over.minutes ?? 10,
    in_circle: over.in_circle ?? true,
    ...over,
  } as PoiPoint
}

describe('lcSnapshotPoiLayer · 共享 POI 投影层', () => {
  it('TC-01 输出与 lcToPx 完全同口径（同一中心，逐点相等）', () => {
    const dots = lcSnapshotPoiLayer(CENTER, POINTS)
    for (let i = 0; i < dots.length; i++) {
      const [ex, ey] = lcToPx(CENTER, POINTS[i].lnglat[0], POINTS[i].lnglat[1])
      expect(dots[i].cx).toBeCloseTo(ex, 6)
      expect(dots[i].cy).toBeCloseTo(ey, 6)
    }
    expect(dots.length).toBe(POINTS.length)
  })

  it('TC-02 空数组与 undefined 均返回 [] 且不抛', () => {
    expect(lcSnapshotPoiLayer(CENTER, [])).toEqual([])
    expect(lcSnapshotPoiLayer(CENTER, undefined as unknown as PoiPoint[])).toEqual([])
  })

  it('TC-03 cap 截断只取前 N 点，不越界', () => {
    const seed: PoiPoint[] = Array.from({ length: 30 }, (_, i) =>
      poi({ id: `p-${i}`, lnglat: [CENTER[0] + 0.0001 * i, CENTER[1] + 0.0001 * i] }),
    )
    expect(lcSnapshotPoiLayer(CENTER, seed, 20)).toHaveLength(20)
    // 截断保持原序（前 20 个 id 不变）
    expect(lcSnapshotPoiLayer(CENTER, seed, 20)[0].key).toContain('p-0')
    // cap 大于点数时不扩列
    expect(lcSnapshotPoiLayer(CENTER, seed, 500)).toHaveLength(30)
  })

  it('TC-04 坐标守卫：lnglat 缺失 / 长度≠2 / NaN 的脏点被过滤，不抛', () => {
    const dirty = [
      poi({ id: 'ok-1', lnglat: [CENTER[0] + 0.001, CENTER[1]] }),
      poi({ id: 'ok-2', lnglat: [CENTER[0], CENTER[1] + 0.001] }),
    ]
    const bad: PoiPoint[] = [
      poi({ id: 'bad-missing', lnglat: undefined as unknown as [number, number] }),
      poi({ id: 'bad-short', lnglat: [CENTER[0]] as unknown as [number, number] }),
      poi({ id: 'bad-nan', lnglat: [NaN, CENTER[1]] }),
      poi({ id: 'bad-inf', lnglat: [Infinity, CENTER[1]] }),
    ]
    const dots = lcSnapshotPoiLayer(CENTER, [...bad, ...dirty])
    expect(dots).toHaveLength(2)
    // 仅保留合法点，且 key 前缀即 id（保持原序）
    expect(dots.map((d) => d.key)).toEqual([
      expect.stringContaining('ok-1'),
      expect.stringContaining('ok-2'),
    ])
  })

  it('TC-05 key 唯一（同 id 不同坐标也不撞）+ 未知类别兜底色', () => {
    const two = [
      poi({ id: 'same', lnglat: [CENTER[0] - 0.001, CENTER[1]] }),
      poi({ id: 'same', lnglat: [CENTER[0] + 0.001, CENTER[1]] }),
    ]
    const [a, b] = lcSnapshotPoiLayer(CENTER, two)
    expect(a.key).not.toBe(b.key) // key 含坐标 ⇒ 同 id 不同位不冲突，可安全作 React key
    // 已知类别着对应色
    expect(lcSnapshotPoiLayer(CENTER, [poi({ id: 'm', lnglat: [CENTER[0], CENTER[1]], category: 'medical' })])[0].fill).toBe('#E0483F')
    // 未知类别兜底色（service 灰 #7c6670）
    expect(lcSnapshotPoiLayer(CENTER, [poi({ id: 'z', lnglat: [CENTER[0], CENTER[1]], category: '未知类' })])[0].fill).toBe('#7c6670')
    // title 带真实名称（报告快照 hover 需要）
    expect(lcSnapshotPoiLayer(CENTER, [poi({ id: 't', name: '测试点B', lnglat: [CENTER[0], CENTER[1]] })])[0].title).toBe('测试点B')
  })

  it('TC-06 全量 kaili 点投影均有限且落在画布 [0..W]×[0..H] 内（不外溢/不裁剪）', () => {
    const dots = lcSnapshotPoiLayer(CENTER, POINTS)
    expect(dots.length).toBe(POINTS.length)
    for (const d of dots) {
      expect(Number.isFinite(d.cx)).toBe(true)
      expect(Number.isFinite(d.cy)).toBe(true)
      expect(d.cx).toBeGreaterThanOrEqual(0)
      expect(d.cx).toBeLessThanOrEqual(LC_CANVAS.W)
      expect(d.cy).toBeGreaterThanOrEqual(0)
      expect(d.cy).toBeLessThanOrEqual(LC_CANVAS.H)
    }
  })
})
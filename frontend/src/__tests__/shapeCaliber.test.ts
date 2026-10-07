/**
 * 形状口径（第五把尺）的前端判据集。
 *
 * 重点是第 ② 组「跨端镜像」：后端键里声明的是球面 `bearing()` 分箱，而渲染层只有等距
 * 平面可用。今天两者逐箱相同（实测单点方位差 ≤0.0024°、无顶点压在箱界），但那是巧合
 * 而不是保证 —— 这条判据的作用就是哪天出现临界顶点时，红的是测试，不是屏上的方向。
 */
import { describe, expect, it } from 'vitest'

import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import {
  SHAPE_SUSPECT_CIRCULARITY,
  shapeBinOf,
  shapeCaveatNote,
  shapeOfZone,
  shapeSentence,
  shapeSuspectNote,
  shapeWeakStrong,
} from '../lib/livingCircle'
import { lcMeters } from '../lib/livingCircle'
import type { LivingCircleReport, ShapeCaliber } from '../types'

const REPORTS: [string, LivingCircleReport][] = [
  ['kaili-ev2', kailiEv2 as unknown as LivingCircleReport],
  ['kaili', kaili as unknown as LivingCircleReport],
  ['beijing-jinsong', jinsong as unknown as LivingCircleReport],
]

/* ── ① 在场与缺席 ─────────────────────────────────────────── */

describe('形状口径 · 在场判据', () => {
  it.each(REPORTS)('%s：15/20 两档都读得出形状', (_n, lc) => {
    for (const m of [15, 20]) expect(shapeOfZone(lc, m)).not.toBeNull()
  })

  it.each(REPORTS)('%s：5/10 内圈不发键 ⇒ 出口返回 null（不是 0，也不是"很圆"）', (_n, lc) => {
    for (const m of [5, 10]) expect(shapeOfZone(lc, m)).toBeNull()
  })

  it('载荷整个没有 shape 键（存量件形态）⇒ 所有出口都静默', () => {
    const bare = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    bare.isochrones.forEach((z) => {
      delete (z as { shape?: ShapeCaliber }).shape
    })
    expect(shapeOfZone(bare, 15)).toBeNull()
    expect(shapeSentence(bare, 15)).toBeNull()
    expect(shapeSuspectNote(bare, 15)).toBeNull()
    expect(shapeCaveatNote(bare, 15)).toBeNull()
  })
})

/* ── ② 跨端镜像：前端分箱必须复现后端键 ─────────────────── */

describe('形状口径 · 跨端分箱镜像', () => {
  /**
   * 前端只有等距平面（`lcMeters`），后端键里的半径出自球面 `haversine_m` —— 两者在
   * 1km 尺度上差约 1m，这是**度量差**不是**分箱差**。所以这条判据钉的是真正要紧的
   * 三件事：每个方位的最大值来自同一个顶点（方向一致）、米级容差、最弱/最强方位同格。
   * 哪天有顶点压上箱界，红的是"方向不一致"这一条，而不是无意义的逐米相等。
   */
  it.each(REPORTS)('%s：逐箱 argmax 顶点与后端一致，半径差 ≤2m', (_n, lc) => {
    const zone = lc.isochrones.find((z) => z.minutes === 15)
    const sh = zone?.shape
    expect(sh).toBeTruthy()
    const center = lc.scene.center
    const manual = [0, 0, 0, 0, 0, 0, 0, 0]
    const argmax: (number[] | null)[] = Array(8).fill(null)
    zone!.geojson.coordinates[0].forEach(([lng, lat], vi) => {
      const [mx, my] = lcMeters(center, lng, lat)
      const r = Math.sqrt(mx * mx + my * my)
      const k = shapeBinOf(center, lng, lat)
      if (r > manual[k]) {
        manual[k] = r
        argmax[k] = [lng, lat, vi]
      }
    })
    manual.forEach((v, k) => {
      expect(Math.abs(v - sh!.bins_m[k])).toBeLessThanOrEqual(2)
      const [lng, lat] = sh!.bins_m.length === 8 ? (argmax[k] as [number, number, number]) : [0, 0, 0]
      // 该顶点确实落在前端算出的那个箱里（方向自证）
      expect(shapeBinOf(center, lng, lat)).toBe(k)
    })
    const mine = { weak: manual.indexOf(Math.min(...manual)), strong: manual.indexOf(Math.max(...manual)) }
    const theirs = shapeWeakStrong(sh!)
    expect(mine.weak).toBe(theirs.weak)
    expect(mine.strong).toBe(theirs.strong)
    expect(Math.abs(manual[mine.weak] / manual[mine.strong] - sh!.weak_ratio)).toBeLessThan(0.005)
  })

  it('方位词只有一份出处：句子用的词必须来自键，不是前端另抄的表', () => {
    const lc = REPORTS[0][1]
    const sh = shapeOfZone(lc, 15)!
    const { weak } = shapeWeakStrong(sh)
    expect(shapeSentence(lc, 15)).toContain(sh.bins_word[weak])
    expect(sh.bins_word).toHaveLength(8)
    expect(sh.bins_word[0]).toBe('正北')
  })
})

/* ── ③ 读侧再判一次：口径漂移一律不画 ─────────────────── */

describe('形状口径 · 篡改即失效', () => {
  const tamper = (patch: (sh: ShapeCaliber) => void) => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === 15)!
    patch(zone.shape as ShapeCaliber)
    return lc
  }

  it('分相被改成 floor（会把缺口并进相邻方向）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.bin_phase = 'floor' }), 15)).toBeNull()
  })
  it('原点被换成质心（球面实算圆度会动 0.029、劲松最弱方位直接改口）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.origin = 'centroid' }), 15)).toBeNull()
  })
  it('方位角实现漂移成平面 atan2 ⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.azimuth_fn = 'atan2' }), 15)).toBeNull()
  })
  it('分箱宽度漂移 ⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.bin_deg = 30 }), 15)).toBeNull()
  })
  it('标量与 bins 对不上（第二生产者留下的旧值）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.weak_ratio = 0.99 }), 15)).toBeNull()
    expect(shapeOfZone(tamper((sh) => { sh.circularity = 0.95 }), 15)).toBeNull()
  })
  it('箱值非法（含 0 ⇒ 等于宣称某个方位一步都出不去）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.bins_m = [0, ...sh.bins_m.slice(1)] }), 15)).toBeNull()
  })
  it('词表里有重复（换序/填错的典型形态）⇒ 不画', () => {
    // 读侧**不许自备一份正确词表**（I-07 词表只有一份，随键下发），所以这里只能判结构：
    // 八个位置出现重复 ⇒ 一定不是同一张表。"整体转一格"那种无重复的错序只有签发闸能判，
    // 由后端 B17 的 bins_word 序核对守着（tests/test_shape_caliber.py::test_b17_catches_word_table_rotated_out_of_order）。
    expect(shapeOfZone(tamper((sh) => { sh.bins_word = [sh.bins_word[0], sh.bins_word[0], ...sh.bins_word.slice(2)] }), 15)).toBeNull()
    // 正对照：真词表八个词互不相同，剥掉这条判据就会把正常载荷也打死
    expect(new Set((kailiEv2 as unknown as LivingCircleReport).isochrones.find((z) => z.minutes === 15)!.shape!.bins_word).size).toBe(8)
  })
  it('声明字段集合与读侧校验清单逐位对齐（谁加字段忘了配对，这里先红）', () => {
    // S28 的前端这条腿：生产端发出的键集合 == 后端判据消费的集合 == 前端真在核对的清单。
    // 少一边就是"发了没人消费"的幽灵字段——本轮三条审查打穿的四条缺口全是这个形状。
    const CONSUMED_BY_READER = [
      'bins_m', 'bins_word', 'bin_deg', 'bin_phase', 'origin', 'azimuth_fn', 'circularity', 'weak_ratio',
    ]
    for (const [name, lc] of REPORTS) {
      const sh = (lc.isochrones.find((z) => z.minutes === 15)?.shape ?? {}) as Record<string, unknown>
      expect(Object.keys(sh).sort(), name).toEqual([...CONSUMED_BY_READER].sort())
    }
  })
})

/* ── ④ 文案：只说方向，不说好坏 ─────────────────────────── */

describe('形状口径 · 措辞边界', () => {
  it.each(REPORTS)('%s：句子只指方向，不出现质量词', (_n, lc) => {
    const text = shapeSentence(lc, 15) ?? ''
    expect(text).toMatch(/^最弱方向：/)
    expect(text).toContain('m')
    for (const banned of ['优', '良', '差', '更好', '越圆', '评分', '分]']) {
      expect(text).not.toContain(banned)
    }
  })

  it('常驻声明里写明不参与评分，并带四件口径', () => {
    const note = shapeCaveatNote(REPORTS[0][1], 15) ?? ''
    expect(note).toContain('不参与综合评分')
    expect(note).toContain('scene.center')
    expect(note).toContain('center')
  })
})

/* ── ⑤ 告警阈值两侧对照（正对照，防阈值判据空转）───────── */

describe('形状口径 · 退化告警两侧对照', () => {
  const withCircularity = (v: number): LivingCircleReport => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === 15)!
    const sh = zone.shape as ShapeCaliber
    // 圆度 = 等面积半径 ÷ 最远半径。面积不动时，只有把**整圈**按同比例缩放才能把最远
    // 半径压到目标值上（只改一格是改不动最大值的 —— 上一版就犯了这个错，构造出的
    // 载荷圆度没变，于是"高于阈值必现"这条正对照其实在测 null）。
    const eqR = Math.sqrt((zone.area_km2 * 1e6) / Math.PI)
    const target = eqR / v
    const f = target / Math.max(...sh.bins_m)
    sh.bins_m = sh.bins_m.map((b) => Math.round(b * f * 10) / 10)
    sh.circularity = Math.round((eqR / Math.max(...sh.bins_m)) * 1000) / 1000
    sh.weak_ratio = Math.round((Math.min(...sh.bins_m) / Math.max(...sh.bins_m)) * 1000) / 1000
    return lc
  }

  it('高于阈值 ⇒ 告警必现', () => {
    const lc = withCircularity(SHAPE_SUSPECT_CIRCULARITY + 0.01)
    expect(shapeSuspectNote(lc, 15)).toContain('疑为模型造形')
  })
  it('低于阈值 ⇒ 整句不出现（返回 null，不是空串）', () => {
    const lc = withCircularity(SHAPE_SUSPECT_CIRCULARITY - 0.05)
    expect(shapeSuspectNote(lc, 15)).toBeNull()
  })
  it('真件都不该命中告警（凯里 0.713 / 劲松 0.794 量级）', () => {
    for (const [, lc] of REPORTS) {
      expect(shapeSuspectNote(lc, 15)).toBeNull()
      expect(shapeSuspectNote(lc, 20)).toBeNull()
    }
  })
})

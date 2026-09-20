/**
 * 盲区适配/缺省层 + C1-C4 渲染校验。
 *
 * 守护规则（契约文档 §5 / 实施计划六）：
 *   1. 旧 schema（仅 id/center/radius_m/missing_facilities/nearest/polygon，fixture 演示态）
 *      缺省时不崩、不误判：severity 回退 light、gap_score 回退 null、fixes 回退 []、affected 回退 null。
 *   2. 新 schema 值原样保留且 gap_score 被 clamp 到 [0,1]。
 *   3. 连续热力填充盲HeatFill：null→灰；0→浅黄、0.5→橙、1→红；alpha 随 gap 单调升。
 *   4. blindTitle 三档可达 & isochrone_based 语义 & 受影响 & 补点策略描述。
 */
import { describe, it, expect } from 'vitest'
import type { BlindSpot, LngLat, GeojsonPolygon } from '../types'
import {
  severityOf,
  gapScoreOf,
  fixesOf,
  affectedOf,
  blindHeatFill,
  blindSevSpec,
  LC_BLIND_SEV,
  LC_FIX_DOT,
} from '../lib/livingCircle'

const CENTER: LngLat = [106.7, 26.6]
const RING: LngLat[] = [
  [106.69, 26.6],
  [106.71, 26.6],
  [106.71, 26.61],
  [106.69, 26.61],
  [106.69, 26.6],
]
const POLY: GeojsonPolygon = { type: 'Polygon', coordinates: [RING] }

/** 旧 schema 盲区（fixture 演示态：beijing-jinsong.json 实测仅 5 个旧字段）。 */
const OLD: BlindSpot = {
  id: 'bs-老数据-1',
  center: CENTER,
  radius_m: 1000,
  missing_facilities: ['菜市场'],
  nearest: [{ facility: 'market', name: '某菜市', distance_m: 1500, direction: '西北' }],
  polygon: POLY,
}

/** 新 schema 盲区（含全部新增字段）。 */
const NEW: BlindSpot = {
  ...OLD,
  severity: 'heavy',
  gap_score: 0.82,
  reach: { real_walk_min: 21.4, isochrone_based: true },
  fixes: [
    { facility: '菜市场', strategy: 'build', priority: 1, point: CENTER, served: 6 },
    { facility: '药店', strategy: 'mobile_service', priority: 2, point: CENTER, served: 4 },
  ],
  affected: { sampling_sites: 3, estimated_households: 1200, estimated_residents: 3120, provenance: 'proxy', note: '按规划基准估算' },
}

describe('盲区适配层（旧 schema 兜底）', () => {
  it('OLD：severity 回退 light（最保守，不夸大整改级别）', () => {
    expect(severityOf(OLD)).toBe('light')
    expect(severityOf({})).toBe('light')
    expect(severityOf(undefined as unknown as BlindSpot)).toBe('light')
  })

  it('OLD：gap_score 回退 null / 越界被 clamp 到 [0,1]', () => {
    expect(gapScoreOf(OLD)).toBeNull()
    expect(gapScoreOf({ gap_score: undefined })).toBeNull()
    expect(gapScoreOf({ gap_score: 1.5 })).toBe(1)
    expect(gapScoreOf({ gap_score: -0.3 })).toBe(0)
    expect(gapScoreOf({ gap_score: NaN })).toBeNull()
    expect(gapScoreOf({ gap_score: 'x' })).toBeNull()
  })

  it('OLD：fixes 回退 []、affected 回退 null', () => {
    expect(fixesOf(OLD)).toEqual([])
    expect(fixesOf({ fixes: undefined })).toEqual([])
    expect(fixesOf({ fixes: 'bad' })).toEqual([])
    expect(affectedOf(OLD)).toBeNull()
    // 缺 provenance 的伪 affected 也必须回退 null（诚实口径）
    expect(affectedOf({ affected: { sampling_sites: 9 } })).toBeNull()
    expect(affectedOf({ affected: null })).toBeNull()
  })

  it('NEW：真实值原样保留', () => {
    expect(severityOf(NEW)).toBe('heavy')
    expect(gapScoreOf(NEW)).toBe(0.82)
    expect(fixesOf(NEW).length).toBe(2)
    expect(affectedOf(NEW)).toEqual(NEW.affected)
  })
})

describe('盲区渲染：连续热力 + 严重度色带', () => {
  it('blindHeatFill：null→灰，0→浅黄，0.5→橙，1→红，alpha 单调升', () => {
    expect(blindHeatFill(null)).toBe('rgba(120,120,120,0.16)')
    const c0 = blindHeatFill(0)
    const c5 = blindHeatFill(0.5)
    const c1 = blindHeatFill(1)
    const rgba = (s: string) => s.match(/rgba?\(([^)]+)\)/)![1].split(',').map((x) => Number(x.trim()))
    const [r0, g0] = rgba(c0)
    const [r1] = rgba(c1)
    const [gmid] = [rgba(c5)[1]]
    // 低端偏黄 (R 高 G 高)，高端偏红 (R 高 G 低)
    expect(r0).toBeGreaterThan(g0)
    expect(r1).toBeGreaterThan(gmid)
  })

  it('blindHeatFill 越界 clamp 到 [0,1]', () => {
    expect(blindHeatFill(2)).toBe(blindHeatFill(1))
    expect(blindHeatFill(-1)).toBe(blindHeatFill(0))
  })

  it('severity 色带三档语义一致（heavy 红 / medium 橙 / light 黄）', () => {
    expect(LC_BLIND_SEV.heavy.stroke).toMatch(/d64545/i)
    expect(LC_BLIND_SEV.medium.stroke).toMatch(/e89a3c/i)
    expect(LC_BLIND_SEV.light.stroke).toMatch(/d9bd3a/i)
    expect(blindSevSpec('heavy').label).toBe('重度')
    expect(blindSevSpec(undefined).stroke).toBe('#8a8a8a') // 未知 → 灰
  })

  it('补点处方符号色（C3 绿核）', () => {
    expect(LC_FIX_DOT).toBe('#1f9e63')
  })
})
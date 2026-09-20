/**
 * F2 · mock 数据源规则：已知 id / 未知 id / 最近中心点匹配。
 */
import { describe, it, expect } from 'vitest'
import { SAMPLE_COMMUNITIES, getLifeCircleMock, matchNearestMock } from '../mocks/livingCircleMock'

describe('livingCircleMock 数据源', () => {
  it('SAMPLE_COMMUNITIES 提供两套样例且 id 唯一', () => {
    expect(SAMPLE_COMMUNITIES).toHaveLength(2)
    expect(new Set(SAMPLE_COMMUNITIES.map((c) => c.id)).size).toBe(2)
    for (const c of SAMPLE_COMMUNITIES) {
      expect(c.report.scene.name).toBeTruthy()
      // M5：内置快照为真实百度实跑数据
      expect(c.report.data_origin).toBe('live')
      expect(c.report.sampling.interpolation).toBe('idw')
    }
  })

  it('getLifeCircleMock：已知 id 返回对应报告', () => {
    const r = getLifeCircleMock('kaili')
    expect(r?.scene.name).toBe('凯里老街')
  })

  it('getLifeCircleMock：未知 id 回退首个样例（不抛错）', () => {
    const r = getLifeCircleMock('not-exist')
    expect(r?.scene.name).toBe(SAMPLE_COMMUNITIES[0].report.scene.name)
  })

  it('getLifeCircleMock：null 也回退首个样例', () => {
    const r = getLifeCircleMock(null)
    expect(r?.scene.name).toBe(SAMPLE_COMMUNITIES[0].report.scene.name)
  })

  it('matchNearestMock：按中心点距离选取最近样例', () => {
    const jinsongCenter = SAMPLE_COMMUNITIES[1].report.scene.center
    const kailiCenter = SAMPLE_COMMUNITIES[0].report.scene.center
    // 靠劲松坐标 → 应选中劲松
    const nearJinsong = matchNearestMock([jinsongCenter[0] + 0.001, jinsongCenter[1] + 0.001])
    expect(nearJinsong.scene.name).toBe('北京劲松')
    // 靠凯里坐标 → 应选中凯里
    const nearKaili = matchNearestMock([kailiCenter[0] + 0.001, kailiCenter[1] + 0.001])
    expect(nearKaili.scene.name).toBe('凯里老街')
  })
})
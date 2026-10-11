/**
 * F2 · mock 数据源规则：已知 id / 未知 id / 最近中心点匹配。
 */
import { describe, it, expect } from 'vitest'
import { SAMPLE_COMMUNITIES, getLifeCircleMock, matchNearestMock } from '../mocks/livingCircleMock'

describe('livingCircleMock 数据源', () => {
  it('SAMPLE_COMMUNITIES 五套样例、id 唯一、每套都是真跑快照', () => {
    // 2026-10-11：三份 → 五份（真跑新增上海五角场 / 凯里下司）。数量下钉在这里而不是"≥3"，
    // 是为了让"删样区"和"加样区"都逼人改一处显式声明 —— 与后端 `bake.DEMO_STEMS`、镜像闸那对
    // 路径、`getLifeCircleRecords` 的 id 数组是同一次增删要同步改的四张清单。
    expect(SAMPLE_COMMUNITIES).toHaveLength(5)
    expect(new Set(SAMPLE_COMMUNITIES.map((c) => c.id)).size).toBe(5)
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
    // 按 id 取，不按位置：名册里现在有两份同中心的凯里（旧冻结件 + ev-2 那份），
    // 用下标会让"劲松"读到旧凯里 ⇒ 这条会测成反向。
    const byId = (id: string) => SAMPLE_COMMUNITIES.find((c) => c.id === id)!.report
    const jinsongCenter = byId('beijing-jinsong').scene.center
    const kailiCenter = byId('kaili').scene.center
    // 靠劲松坐标 → 应选中劲松
    const nearJinsong = matchNearestMock([jinsongCenter[0] + 0.001, jinsongCenter[1] + 0.001])
    expect(nearJinsong.scene.name).toBe('北京劲松')
    // 靠凯里坐标 → 应选中凯里
    const nearKaili = matchNearestMock([kailiCenter[0] + 0.001, kailiCenter[1] + 0.001])
    expect(nearKaili.scene.name).toBe('凯里老街')
  })
})
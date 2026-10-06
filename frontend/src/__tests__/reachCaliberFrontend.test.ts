/**
 * 笔 3-B 前端半：第三根口径轴 `rc-*` 的登记、措辞组合与残差句的 presence 判据。
 *
 * 为什么单独一份（不塞进 `compareDiffContract.test.ts`）：那份比的是**差异表两端逐字对齐**，
 * 这一份比的是"这根轴在前端被消费的两处到底有没有被消费"。加一根轴最容易出的不是拼错句，
 * 而是**登记了却没人读**（本仓把它叫"零消费者字段"）——所以每条判据都直接调用真实出口。
 *
 * 四条硬判据：
 *  ① 版本常量与契约夹具同源（换版本只改后端 + 夹具，两侧同时报警）；
 *  ② 措辞按轴子句组合：`rc` 子句能单独成句、也能与另两根拼成三段子句；
 *  ③ `rc` **不拦差异表任何一行**（空集），且**不进**单份报告那句「建议重新体检」——
 *     rc-1 没改任何读数，挂 CTA 就是空承诺；
 *  ④ 残差句只在 payload 真带 `sampling.detour` 时出现；缺键/无样本 ⇒ null（不印 0）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  CALIBER_AXES,
  REACH_CALIBER_VERSION,
  REACH_GAP_ROW_KEYS,
  gapDescFor,
  reachCaliberGap,
  residualCaliberNote,
  staleCaliberNotices,
} from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

const CONTRACT = JSON.parse(
  readFileSync(join(process.cwd(), 'src/__tests__/fixtures/compareDiffContract.json'), 'utf-8'),
) as { caliber_incomparable: Record<string, unknown> }
const GAP = CONTRACT.caliber_incomparable

/** 只喂 `residualCaliberNote` 需要的最小切片，避免测试跟着无关字段漂。 */
const withDetour = (detour: unknown): LivingCircleReport =>
  ({ sampling: { detour } }) as unknown as LivingCircleReport

const FULL = {
  declared_detour_k: 1.3,
  detour_factor_measured: 1.62,
  implied_detour_p10: 1.332,
  implied_detour_p90: 2.267,
  points_used: 1048,
  excluded: { near_center: 1, untimed: 0, non_positive: 0 },
  residual_min: { p50: -0.0, p90: 12.4, p95: 20.1, max: 34.1, min: -11.7 },
}

describe('第三根口径轴 rc 的登记与措辞', () => {
  it('版本常量与契约夹具同源（三方里的两方）', () => {
    expect(REACH_CALIBER_VERSION).toBe(GAP.reach_version_current)
  })

  it('轴清单与顺序逐字等于夹具（词序是用户可见的）', () => {
    expect(CALIBER_AXES.map((s) => s.axis)).toEqual(GAP.axes)
  })

  it('rc 子句单独成句、并与另两根拼成三段子句', () => {
    expect(gapDescFor(['rc'])).toBe(GAP.reach_desc)
    expect(gapDescFor(['ev', 'cov', 'rc'])).toBe(GAP.all_desc)
    // 传反序也得同一句：顺序由表归一，否则差异表与横幅会拼出两种词序
    expect(gapDescFor(['rc', 'cov', 'ev'])).toBe(GAP.all_desc)
    expect(gapDescFor([])).toBeNull()
    const clause = CALIBER_AXES.find((s) => s.axis === 'rc')?.clause ?? ''
    expect(clause).toBeTruthy()
    expect((GAP.all_desc as string).split('、')).toHaveLength(3)
  })

  it('rc 不拦差异表里的任何一行（这条空集本身就是判据）', () => {
    expect(REACH_GAP_ROW_KEYS).toEqual([])
    expect(GAP.reach_applies_to).toEqual([])
  })

  it('rc **不进**单份报告的「建议重新体检」清单，也不留零消费者的那句文案', () => {
    // 夹具里刻意没有 reach_stale_notice：留着没人读＝本仓最恨的那种登记
    expect(GAP).not.toHaveProperty('reach_stale_notice')
    const lc = { caliber: {} } as LivingCircleReport
    const notes = staleCaliberNotices(lc)
    expect(notes.some((n) => n.includes('可达口径'))).toBe(false)
    // 而判盲/评分那两句照旧在（撤掉 rc 那句不能顺手把它们也撤了）
    expect(notes.some((n) => n.includes('判盲口径'))).toBe(true)
    expect(notes.some((n) => n.includes('评分口径'))).toBe(true)
  })

  it('reachCaliberGap 四形状：双缺＝可比、单缺＝不同、同值＝可比、异值＝不同', () => {
    const A = (v?: string) => ({ caliber: v ? { reach_caliber_version: v } : {} } as LivingCircleReport)
    expect(reachCaliberGap(A(), A())).toBe(false)
    expect(reachCaliberGap(A('rc-1'), A('rc-1'))).toBe(false)
    expect(reachCaliberGap(A('rc-1'), A())).toBe(true)
    expect(reachCaliberGap(A('rc-1'), A('rc-2'))).toBe(true)
  })
})

describe('残差耗时那句（rc-1 的唯一上屏出口）', () => {
  it('payload 带着标定 ⇒ 说得出系数、分位数、入样与三类剔除', () => {
    const s = residualCaliberNote(withDetour(FULL))!
    expect(s).toBeTruthy()
    expect(s).toContain('1.62×')
    expect(s).toContain('1.3×')       // 声明值并列报出，差多少是明账
    expect(s).toContain('12.4min')
    expect(s).toContain('34.1min')
    expect(s).toContain('1048')
    expect(s).toContain('中心 1')
    expect(s).toContain('未测时 0')
    expect(s).toContain('零耗时 0')
    expect(s).toContain('代理')
  })

  it('只按分钟说话：这句话里不许出现百分比', () => {
    const s = residualCaliberNote(withDetour(FULL))!
    expect(s).not.toContain('%')
    expect(s).not.toMatch(/残差[^。]*\d+(\.\d+)?%/)
  })

  it('缺 detour 键 / 无可用样本 ⇒ 整块不出现（不印 0、不猜）', () => {
    expect(residualCaliberNote({ sampling: {} } as LivingCircleReport)).toBeNull()
    expect(residualCaliberNote(withDetour(null))).toBeNull()
    expect(residualCaliberNote(withDetour({ ...FULL, detour_factor_measured: null }))).toBeNull()
    expect(residualCaliberNote(withDetour({ ...FULL, residual_min: null }))).toBeNull()
    // 没标定出系数时，屏幕上连"0min"这样的字样都不该出现
    expect(residualCaliberNote(withDetour({ ...FULL, detour_factor_measured: null }))).toBeNull()
  })

  it('三件必须同时说清的事各有一处落点（代理、非因果、不是声明值）', () => {
    const src = readFileSync(join(process.cwd(), 'src/lib/livingCircle.ts'), 'utf-8')
    const fn = src.slice(src.indexOf('export function residualCaliberNote'))
    expect(fn).toContain('受阻代理')
    expect(fn).toContain('不指认具体障碍')
    expect(fn).toContain('declared_detour_k')
  })

  it('这句话真被两处渲染面消费（"登记了却没人读"的反面）', () => {
    // 本仓为这个形状吃过至少两次亏：新字段发进 payload、渲染器也写好了，但没有任何一处调用它
    // ⇒ 全量测试全绿、屏幕上什么都没有。所以这里按**调用点**扫，而不是扫注释或导出。
    const sites = ['src/pages/LifeCirclePage.tsx', 'src/components/lifecircle/LifeCircleReportView.tsx']
    for (const rel of sites) {
      const src = readFileSync(join(process.cwd(), rel), 'utf-8')
      expect(src, `${rel} 没有调用 residualCaliberNote ⇒ 这句上不了屏`).toContain('residualCaliberNote(')
    }
  })
})

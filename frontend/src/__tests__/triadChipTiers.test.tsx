// @vitest-environment jsdom
/**
 * 三要素 chip 的五态在**真渲染面**上落成什么（计划「验证 · P1 反例真跑」的前端半）。
 *
 * 为什么不并进 `triadProseMirror.test.ts`：那份比的是**源码字面量**（措辞出口对不对），
 * 这一份要的是**渲染结果** —— 同一个 payload 进组件，屏幕上说哪句话、点哪一档色。只测纯
 * 函数会放过真事故的那一类：渲染器改对了，组件里却还留着 `t.covered ? …` 的老写法。
 *
 * 四条判据都在说同一件事——**不许塌档**：
 *  ① `blocked`（直线 950m、绕行到不了）印「1km 内有（950m）· 步行到不了」，而不是旧那句
 *    「1km 内缺失」。这是本域犯过三次的假话，也正是赛题要的「道路并非直线」的现成证据。
 *  ② `unknown`（旧快照没有 `within_blind_radius` 这个键）走**中性档**：既不是警告色也不是
 *    可达色。借警告色＝替它下"没有"的结论。
 *  ③ `absent`（1km 尺真的量过、确实没有）才许说「中心 1km 内没有」，且必须与 `unknown` 分档
 *    —— 两档同色就是"没查过"和"查过没有"在屏幕上合并，与逐格台账 `present` 用 int8 三态
 *    （`-1/0/1`）不是 bool 同一条纪律。
 *  ④ 三档两两互不相同。写成同一档＝只有一档在守。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { Report } from '../types'

vi.mock('../lib/bmap', () => ({
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => {
    throw new Error('测试内不应注入 BMapGL')
  },
  geolocateMe: async () => null,
}))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => vi.fn() }
})
vi.mock('../components/VChart', () => ({
  VChart: () => <div data-testid="mock-chart" />,
}))

/* 三档配色，**字面量故意在这里重复一份、不 import `TRIAD_CHIP_CLASS`**：判据必须独立于被测值，
   import 过来的话"有人把两档改成同一种颜色"永远不会让这条红（手法同 `lcReportLocalMap.test.tsx`
   里那份 SPLIT）。 */
const TIER_OK = 'bg-ok/10'
const TIER_GAP = 'bg-warn/10'
const TIER_UNKNOWN = 'bg-line/60'

const REACHABLE = {
  facility: '菜市场', covered: true, in_reach: true, within_blind_radius: true,
  nearest_m: 300, nearest_name: '私宴', nearest_minutes: 7.4,
}
const BLOCKED = {
  facility: '药店', covered: false, in_reach: false, within_blind_radius: true,
  nearest_m: 950, nearest_name: '益民大药房', nearest_minutes: null,
}
const ABSENT = {
  facility: '小学', covered: false, in_reach: false, within_blind_radius: false,
  nearest_m: 2200, nearest_name: '凯里市第十三小学', nearest_minutes: null,
}
/** 刻意**不写** `within_blind_radius` 这个键 —— 旧快照的形状就是这样，缺席不等于 `false`。 */
const UNKNOWN = {
  facility: '小学', covered: false, nearest_name: null, nearest_minutes: null,
}

async function renderTriads(triads: unknown[]): Promise<void> {
  const base = JSON.parse(
    JSON.stringify(getLivingCircleReportMock('lc-kaili-ev2')),
  ) as { living_circle: { scores: { triads: unknown } } }
  base.living_circle.scores.triads = triads
  cleanup()
  render(
    <MemoryRouter initialEntries={['/report/lc-1']}>
      <LifeCircleReportView report={base as unknown as Report} />
    </MemoryRouter>,
  )
  // 体检单那一排 chip 在首屏，等一轮 microtask 让地图降级分支落定
  await new Promise((r) => setTimeout(r, 0))
}

/** 取某一枚 chip（按它在屏幕上的完整文字，不按下标 —— 顺序变了也该照样认得出）。 */
function chip(text: string): HTMLElement {
  const el = screen.queryByText(text, { exact: false })
  expect(el, `屏幕上没有这句话：${text}`).toBeTruthy()
  return el!.closest('.rounded-chip') as HTMLElement
}

afterEach(cleanup)

describe('三要素 chip 的五态渲染档（报告体检单）', () => {
  it('可达档照旧说分钟，且是三档里唯一用可达色的', async () => {
    await renderTriads([REACHABLE])
    const c = chip('菜市场 · 最近 7.4min')
    expect(c.className).toContain(TIER_OK)
    expect(c.className).not.toContain(TIER_GAP)
    expect(c.className).not.toContain(TIER_UNKNOWN)
  })

  it('「1km 内有、步行到不了」不再被说成「1km 内缺失」', async () => {
    await renderTriads([BLOCKED])
    const c = chip('药店 · 1km 内有（950m）· 步行到不了')
    expect(document.body.textContent).not.toContain('1km 内缺失')
    expect(c.className).toContain(TIER_GAP)
    expect(c.className).not.toContain(TIER_OK)
  })

  it('旧快照那种「没查过」走中性档，既不借警告色也不借可达色', async () => {
    await renderTriads([UNKNOWN])
    const c = chip('小学 · 1km 内有没有未查全')
    expect(c.className).toContain(TIER_UNKNOWN)
    expect(c.className).not.toContain(TIER_GAP)
    expect(c.className).not.toContain(TIER_OK)
    // 「没查过」不许被塌成「查过且没有」
    expect(document.body.textContent).not.toContain('中心 1km 内没有')
  })

  it('真量过的「中心 1km 内没有」才用缺席措辞，并与未查全分档', async () => {
    await renderTriads([ABSENT])
    const c = chip('小学 · 中心 1km 内没有')
    expect(c.className).toContain(TIER_GAP)
    expect(c.className).not.toContain(TIER_UNKNOWN)

    // 同一格换个写法（把键去掉）就该换一档：两档同色＝屏幕上把两件事说成一件事
    await renderTriads([UNKNOWN])
    const u = chip('小学 · 1km 内有没有未查全')
    expect(u.className, 'absent 与 unknown 同色 ⇒ 塌档').not.toEqual(c.className)
  })

  it('三档两两互不相同（写成同一档＝只有一档在守）', async () => {
    await renderTriads([REACHABLE])
    const ok = chip('菜市场 · 最近 7.4min').className
    await renderTriads([BLOCKED])
    const gap = chip('药店 · 1km 内有（950m）· 步行到不了').className
    await renderTriads([UNKNOWN])
    const unk = chip('小学 · 1km 内有没有未查全').className
    expect(new Set([ok, gap, unk]).size, '三档里有两档同色').toBe(3)
  })
})

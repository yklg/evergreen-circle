// @vitest-environment jsdom
/**
 * 报告体检单 · 盲区局部图的挂载契约（计划笔 8，P0-7）。
 *
 * 局部图与主图是**同一页上的两个 LcMap 实例** ⇒ 两件事必须钉住：
 *  ① 第二张要**进视口才挂**：P0-7 的原始顾虑是两个 BMapGL 实例同页初始化（抢 SDK、
 *     首屏白付一次瓦片钱）。但"没有 IntersectionObserver"绝不能变成**不挂** ——
 *     jsdom 与老浏览器里它会退化成一副永远的空骨架，那比多一个实例更糟。
 *     本仓 jsdom 恰好不带 IO，所以"无 IO ⇒ 直接挂载"这一支在本文件里是**实跑到的**。
 *  ② 没有盲区 ⇒ 整块不出现：无焦点可聚时摆一张跟主图一样的图是凑数，还白多一个实例。
 *     这条要用"台账在、盲区空"的样区测才有效：直接拿 0 盲区 0 台账的 `lc-kaili`，
 *     外层条件先挡掉，内层判据根本没跑到（第一轮就是这样，变异全绿 = 空用例）。
 *
 * 数实例的抓手 = 降级画布角标「地图降级 · 静态画布」。为此把 `lib/bmap` 换成空 AK
 * （同 `lcMapDesensitize.test.tsx`）⇒ 两个实例都确定性地落 fallback，角标数即已挂载数。
 * 不这么做的化：jsdom 里真 fetch 不返回，实例会卡在 loading 态，数出来的永远是 0。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { LivingCircleReport, Report } from '../types'

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

const CHIP = '地图降级 · 静态画布（无 AK / 离线）'
const CAPTION = '局部视图：盲区图层只留'

function lcOf(reportId: string): LivingCircleReport {
  const r = getLivingCircleReportMock(reportId) as unknown as { living_circle: LivingCircleReport }
  return r.living_circle
}

async function renderReport(report: Report) {
  cleanup()
  const view = render(
    <MemoryRouter initialEntries={['/report/lc-1']}>
      <LifeCircleReportView report={report} />
    </MemoryRouter>,
  )
  // 让 getMapConfig 的 microtask 与 setMode('fallback') 引发的重渲染落地
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
  return view
}

function mockReport(reportId: string): Report {
  return getLivingCircleReportMock(reportId) as unknown as Report
}
/** ev2 原样、只把盲区清零：保留台账 ⇒ 外层块仍在，此时**只有内层判据**拦得住第二张图。 */
function ev2WithoutBlindspots(): Report {
  const r = JSON.parse(JSON.stringify(mockReport('lc-kaili-ev2'))) as {
    living_circle: { blindspots: unknown[] }
  }
  r.living_circle.blindspots = []
  return r as unknown as Report
}

/** 当前已挂载并落地的地图实例数。 */
function mapsMounted(): number {
  return screen.queryAllByText(CHIP).length
}

beforeEach(() => {
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('生活圈报告 · 盲区局部图挂载（笔 8 / P0-7）', () => {
  it('前置自证：ev2 有盲区可聚、kaili 没有，且 jsdom 确实不带 IntersectionObserver', () => {
    expect(lcOf('lc-kaili-ev2').blindspots.length).toBeGreaterThan(0)
    expect(lcOf('lc-kaili').blindspots.length).toBe(0)
    expect(typeof IntersectionObserver, '本用例第 3 条依赖 jsdom 无 IO 这一事实').toBe('undefined')
  })

  it('无 IO 环境 ⇒ 局部图直接挂载（退化成永久空骨架不可接受）', async () => {
    await renderReport(mockReport('lc-kaili-ev2'))
    expect(mapsMounted()).toBe(2)
    expect(document.body.textContent).toContain(CAPTION)
  })

  it('有 IO 时第二张进视口才挂：未进视口只有主图 + 占位，进视口后两张都在场', async () => {
    let fire: (() => void) | null = null
    class FakeIO {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        fire = () => cb([{ isIntersecting: true }])
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeIO)
    await renderReport(mockReport('lc-kaili-ev2'))
    expect(mapsMounted(), '未进视口就挂第二张 ⇒ P0-7 回到原点').toBe(1)
    expect(document.body.textContent).toContain('滚动到此处加载局部图…')

    act(() => fire!())
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
    expect(mapsMounted()).toBe(2)
    expect(document.body.textContent).not.toContain('滚动到此处加载局部图…')
  })

  it('有台账但盲区清零 ⇒ 台账卡照旧在场，第二张图与图注都不出现', async () => {
    // 用 ev2 而不是 kaili：kaili 既无台账又无盲区，外层 `(ledger || blindspots.length>0)`
    // 就先挡掉了，内层判据**根本没被执行**（第一轮拿 kaili 试 `length >= 0` 变异，全绿——
    // 那是一条抓不住任何东西的用例）。盲区清零、台账留着，才有"外层放行、内层该拦"的现场。
    await renderReport(ev2WithoutBlindspots())
    expect(document.querySelectorAll('rect[data-cell]').length, '台账卡整块没了 = 改错了外层').toBeGreaterThan(0)
    expect(mapsMounted()).toBe(1)
    expect(document.body.textContent).not.toContain(CAPTION)
    expect(document.body.textContent).not.toContain('滚动到此处加载局部图…')
  })
})

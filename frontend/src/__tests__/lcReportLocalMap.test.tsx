// @vitest-environment jsdom
/**
 * 报告体检单 · 盲区局部图的挂载契约（计划笔 8，P0-7）。
 *
 * 局部图与主图是**同一页上的两个 LcMap 实例** ⇒ 两件事必须钉住：
 *  ① 第二张要**进视口才挂**：P0-7 的原始顾虑是两个 BMapGL 实例同页初始化（抢 SDK、
 *     首屏白付一次瓦片钱）。但"没有 IntersectionObserver"绝不能变成**不挂** ——
 *     jsdom 与老浏览器里它会退化成一副永远的空骨架，那比多一个实例更糟。
 *     本仓 jsdom 恰好不带 IO，所以"无 IO ⇒ 直接挂载"这一支在本文件里是**实跑到的**。
 *  ② 栏数跟着**实际在场的卡**走：地图恒为一员，所以两栏 ⟺ 台账也在。
 *     上一版无条件 `lg:grid-cols-2`，上海那份盲区 0 处 ⇒ 只有一张卡在场，右半栏成了幽灵栏，
 *     台账卡被挤成半宽、整列空着（2026-10-05 用户截图指出）。当时那条用例只断"卡在不在"，
 *     没断"占几栏"——**存在性判据抓不住布局回归**，这一课记进 `project-verify-claims-empirically`。
 *     盲区 0 处仍挂这张图是 2026-10-05 拍板的：台账卡上那句「开着判定尺时也可以直接在地图上
 *     点一块」只有这张配对图做得到（主图没接 selectedCell）。
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
/** 报告页两行共用的分栏模板。**字面量故意在这里重复一份、不 import 契约**：判据必须独立于
 *  被测值，`import { LC_REPORT_SPLIT }` 的话"有人改了契约"永远不会让这条红（手法同
 *  `lcLayoutContract.test.tsx` 里那六组 utility）。 */
const SPLIT = 'lg:grid-cols-[1.6fr_1fr]'

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
/** ev2 原样、只把盲区清零：保留台账 ⇒ 两栏都在场，但地图不该再聚焦到某一处。 */
function ev2WithoutBlindspots(): Report {
  const r = JSON.parse(JSON.stringify(mockReport('lc-kaili-ev2'))) as {
    living_circle: { blindspots: unknown[] }
  }
  r.living_circle.blindspots = []
  return r as unknown as Report
}
/** ev2 去掉台账、留着盲区 ⇒ 块里只剩地图一张卡，此时不许再摆两栏（幽灵栏就是这条的回归）。 */
function ev2WithoutLedger(): Report {
  const r = JSON.parse(JSON.stringify(mockReport('lc-kaili-ev2'))) as {
    living_circle: { caliber?: { cells_ledger?: unknown } }
  }
  delete r.living_circle.caliber?.cells_ledger
  return r as unknown as Report
}
/** 局部图卡所在的那一行 grid（图注 → 卡 → 行）。 */
function gridEl(): HTMLElement {
  const cap = screen.getByText(/局部视图：/)
  const card = cap.parentElement
  expect(card, '图注不在卡片里 ⇒ 结构变了，本用例失去基线').toBeTruthy()
  return card!.parentElement as HTMLElement
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

  it('盲区清零但有台账 ⇒ 配对图照挂（不聚焦）、图注换口径、两栏照旧', async () => {
    await renderReport(ev2WithoutBlindspots())
    expect(mapsMounted(), '0 盲区就不挂配对图 ⇒ 台账卡那句"直接在地图上点一块"再次落空').toBe(2)
    expect(document.body.textContent).toContain('本区未检出服务盲区')
    expect(document.body.textContent).not.toContain('盲区图层只留')
    expect(document.body.textContent).not.toContain('点绿核补点')
    expect(document.querySelectorAll('rect[data-cell]').length, '台账卡整块没了 = 改错了外层').toBeGreaterThan(0)
    // 这里断 class 只是断"栏数由 `ledgerCards.length` 派生"这条式子还在场；
    // **空栏与列宽本身归 e2e 量**（`幽灵栏` 那条），jsdom 没有排版引擎、量不到几何。
    expect(gridEl().className).toContain(SPLIT)
  })

  it('有盲区但没台账 ⇒ 只剩地图一张卡，栏数必须收回单栏（防幽灵栏）', async () => {
    await renderReport(ev2WithoutLedger())
    expect(document.querySelectorAll('rect[data-cell]').length).toBe(0)
    expect(mapsMounted()).toBe(2)
    expect(gridEl().className, '只有一张卡还摆两栏 ⇒ 右半栏空着（图二那个缺陷）').not.toContain(SPLIT)
    // 没有台账就没有"右侧卡"可互指，图注也不许再这么写
    expect(document.body.textContent).not.toContain('选中格与右侧台账卡互指')
  })

  it('顺序：地图在左、台账在右（与上面体检单行同一侧）', async () => {
    // 「把地图放在左边，与上面统一」是可测的：行的**第一个**子元素必须是那张带图注的地图卡。
    // 两行分栏缝是否真对齐（670 === 670）由 e2e 量，这里只钉顺序不被改回去。
    await renderReport(mockReport('lc-kaili-ev2'))
    const kids = Array.from(gridEl().children)
    expect(kids.length).toBe(2)
    expect(kids[0].textContent, '地图卡不在最左 ⇒ 与上面那行的左右又反了').toContain('局部视图：')
    expect(kids[1].textContent).toContain('逐格台账')
    expect(document.body.textContent).toContain('选中格与右侧台账卡互指')
  })
})

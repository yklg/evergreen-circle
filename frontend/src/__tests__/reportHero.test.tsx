// @vitest-environment jsdom
/**
 * ReportPage 英雄区（渐变底 + 自然流）渲染与接线测试（test-coverage-expander 方案 §3）。
 *
 * 依赖的生产实现：pages/ReportPage.tsx 英雄区、index.css @media print 的 .report-hero。
 *
 * 守护的根因契约（历史 bug：封面图内烘录文字 → 与 DOM 标题前后重叠）：
 *  - H1  英雄区不得再渲染封面图（封面 SVG 烘有标题/品牌行/标语，必与 DOM 文字相撞）
 *  - H2  标题必须**全字长**渲染（历史被截断成 20 字）
 *  - H5  英雄区恰好一个 h1（防双标题回归）
 *  - H15 index.css 必须保留打印留底守卫，否则 window.print() 导出的 PDF 里标题消失
 *
 * 被测范围说明（决定用例档位）：
 *  本套件直接渲染 **整个 ReportPage**，复用 reportRefine.test.tsx:37-66（reportStore 整体 mock）
 *  与 :79-87（MemoryRouter/Routes）的既有脚手架。
 *  ⚠️ **不测布局**：「文字重叠 / 长标题裁剪」属 jsdom 能力外（无布局引擎），
 *  本层只能守住上述代理断言；真正的视觉回归由浏览器级人工验收承担（见方案 G1 缺口）。
 *  ⚠️ 因此**禁止**用 className 断言冒充布局验证 —— 样式改动后仍全绿、真出 bug 却无反应。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ReportPage from '../pages/ReportPage'

const { navigateFn, holder } = vi.hoisted(() => ({
  navigateFn: vi.fn(),
  // 可变容器：factory 在每次 store 调用时才求值，故用例可在 render 前替换 mock 报告
  holder: { report: {} as Record<string, unknown> },
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateFn }
})

// reportStore 整体 mock（与 reportRefine.test.tsx:37-66 同款，隔离 ReportPage 的数据依赖）
vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({
    current: holder.report,
    loading: false,
    error: null,
    load: vi.fn(),
  }),
}))

vi.mock('../lib/api', () => ({
  refineSection: vi.fn(),
  submitFeedback: vi.fn(),
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
}))

const LONG_TITLE =
  "佳沃食品（Joyvio 佳沃蓝莓）、鑫荣懋（Joy Wing Mau）、怡颗莓（Driscoll's 中国）、光筑农业（诺普信旗下蓝莓）、百果园、叮咚买菜 竞争格局深度分析报告"

function makeReport(overrides: Record<string, unknown> = {}) {
  return {
    id: 'r1',
    title: '测试报告',
    subtitle: '测试副标题',
    created_at: '2026-09-16T22:27:49',
    experts: ['e1', 'e2'],
    cover_image: '/assets/brand/report-cover.png',
    toc: [],
    sections: [],
    claims: [],
    evidence: [],
    figures: [],
    sentiment: undefined,
    trace: [],
    glossary: [],
    metrics: undefined,
    audit_review: undefined,
    quality_before: undefined,
    quality_after: undefined,
    ...overrides,
  }
}

function renderReportPage(report: Record<string, unknown> = makeReport()) {
  holder.report = report
  return render(
    <MemoryRouter initialEntries={['/report/r1']}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  navigateFn.mockClear()
  holder.report = makeReport()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ReportPage 英雄区 · 根因契约', () => {
  it('H1 — 英雄区不再渲染封面图（封面 SVG 烘有文字，是本 bug 的根因）', () => {
    const { container } = renderReportPage()
    // 锚点用 img[alt="cover"]：语义明确，不受页面其它合法 img 干扰
    expect(container.querySelector('img[alt="cover"]')).toBeNull()
  })

  it('H2 — 标题全字长渲染，不截断（历史被截成 20 字）', () => {
    renderReportPage(makeReport({ title: LONG_TITLE }))
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1.textContent).toBe(LONG_TITLE)
    // 与原串等长 = 没有被 slice/… 截断
    expect(h1.textContent?.length).toBe(LONG_TITLE.length)
  })

  it('H3 — 副标题渲染', () => {
    renderReportPage(makeReport({ subtitle: '基于 90 条联网证据 · 6 位专家协作生成' }))
    expect(screen.getByText(/基于 90 条联网证据/)).toBeTruthy()
  })

  it('H4 — 统计行渲染且与数据一致', () => {
    renderReportPage(
      makeReport({
        claims: [{ claim_id: 'c1' }, { claim_id: 'c2' }],
        evidence: [{ evidence_id: 'e1' }],
      }),
    )
    expect(screen.getByText(/2 位专家/)).toBeTruthy()
    expect(screen.getByText(/2 条结论/)).toBeTruthy()
    expect(screen.getByText(/1 条证据/)).toBeTruthy()
  })

  it('H5 — 英雄区恰好一个 h1（防双标题回归）', () => {
    const { container } = renderReportPage()
    expect(container.querySelectorAll('h1').length).toBe(1)
  })

  it('H6 — 标题按纯文本渲染，不解析 HTML（防注入）', () => {
    const evil = '<img src=x onerror=alert(1)>'
    const { container } = renderReportPage(makeReport({ title: evil }))
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1.textContent).toBe(evil)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img[alt="cover"]')).toBeNull()
  })

  it('H17 — 负向哨兵：英雄区不渲染 brands 文本（防再把杂乱加回来）', () => {
    renderReportPage(makeReport({ brands: ['ZZBRANDMARK_ONE', 'ZZBRANDMARK_TWO'] }))
    expect(screen.queryByText(/ZZBRANDMARK_ONE/)).toBeNull()
    expect(screen.queryByText(/ZZBRANDMARK_TWO/)).toBeNull()
  })

  it('H16 — 边界：统计全为 0 值仍能渲染且不崩', () => {
    renderReportPage(makeReport({ experts: [], claims: [], evidence: [] }))
    expect(screen.getByText(/0 位专家/)).toBeTruthy()
    expect(screen.getByText(/0 条结论/)).toBeTruthy()
  })
})

describe('ReportPage 英雄区 · 操作行接线', () => {
  it('H7 — 点「知识库」→ /knowledge', () => {
    renderReportPage()
    fireEvent.click(screen.getByRole('button', { name: /知识库/ }))
    expect(navigateFn).toHaveBeenCalledWith('/knowledge')
  })

  it('H8 — 点「演示」→ /report/{id}/slides', () => {
    renderReportPage()
    fireEvent.click(screen.getByRole('button', { name: /演示/ }))
    expect(navigateFn).toHaveBeenCalledWith('/report/r1/slides')
  })

  it('H9 — trace 非空：渲染「决策链路」且点后跳 /trace/{id}', () => {
    renderReportPage(makeReport({ trace: [{ span_id: 's1' }] }))
    fireEvent.click(screen.getByRole('button', { name: /决策链路/ }))
    expect(navigateFn).toHaveBeenCalledWith('/trace/r1')
  })

  it('H10 — trace 为空数组：不渲染「决策链路」', () => {
    renderReportPage(makeReport({ trace: [] }))
    expect(screen.queryByRole('button', { name: /决策链路/ })).toBeNull()
  })

  it('H11 — trace 字段缺失：不渲染且渲染不抛错', () => {
    const r = makeReport()
    delete (r as Record<string, unknown>).trace
    expect(() => renderReportPage(r)).not.toThrow()
    expect(screen.queryByRole('button', { name: /决策链路/ })).toBeNull()
  })

  it('H12 — 点「编辑」→ 文案切「阅读」，再点切回', async () => {
    renderReportPage()
    fireEvent.click(screen.getByRole('button', { name: /编辑/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /阅读/ })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /阅读/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /编辑/ })).toBeTruthy())
  })

  it('H13 — 点「导出」→ window.print() 被调用一次', () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    renderReportPage()
    fireEvent.click(screen.getByRole('button', { name: /导出/ }))
    expect(printSpy).toHaveBeenCalledTimes(1)
  })

  it('H12b — 点「简报」不抛错且按钮仍在（详细切换逻辑由 reportBriefView.test.tsx:277+ 守护）', () => {
    renderReportPage()
    expect(() => fireEvent.click(screen.getByRole('button', { name: /简报/ }))).not.toThrow()
    expect(screen.getByRole('button', { name: /简报/ })).toBeTruthy()
  })

  it('H14 — 长标题渲染 smoke（不因内容长度而崩）', () => {
    expect(() =>
      renderReportPage(makeReport({ title: LONG_TITLE, subtitle: 'x'.repeat(200) })),
    ).not.toThrow()
  })
})

describe('英雄区打印留底契约（H15）', () => {
  it('H15 — index.css 的 @media print 必须保留 .report-hero 的双写打印属性', () => {
    // vitest/Vite 下 import.meta.url 不是 file: scheme（转换产物），故按 cwd 解析
    const cssPath = resolve(process.cwd(), 'src/index.css')
    const css = readFileSync(cssPath, 'utf8')
    const printStart = css.indexOf('@media print')
    expect(printStart).toBeGreaterThan(-1)
    const printBlock = css.slice(printStart)
    expect(printBlock).toMatch(/\.report-hero/)
    // Safari 依赖 -webkit- 前缀，两个必须双写
    expect(printBlock).toMatch(/print-color-adjust:\s*exact/)
    expect(printBlock).toMatch(/-webkit-print-color-adjust:\s*exact/)
  })
})

// @vitest-environment jsdom
/**
 * F3 · 渲染适配器测试（A1）：ReportPage 对 living_circle 报告分发到双层视图
 * （顶层体检单 + 下层完整章节报告），research 报告路径不受影响。
 *
 * 守护契约：
 *  - R1 有 living_circle / report_type=living_circle → 渲染体检单（评分/三要素/盲区）+ 章节报告
 *  - R2 无 living_circle → 保持原报告链路（「报告目录」边栏），不出现体检单
 *  - R3 新增报告类型 = 加分支不改既有结构（R2 兜底，防 if(living_circle) 分叉蔓延）
 *  - R4 双层视图的跳转（双样例对比 / 返回地图）接线正确
 *
 * ⚠️ VChart 以桩替身（echarts 依赖 ResizeObserver，jsdom 不可用），图表结构契约
 *    已由 livingCircleContract.test.ts（ChartSpec.option 存在）守护。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ReportPage from '../pages/ReportPage'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'

const { navigateFn, holder } = vi.hoisted(() => ({
  navigateFn: vi.fn(),
  holder: { report: {} as Record<string, unknown> },
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateFn }
})

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

// echarts 桩替身（见文件头注释）
vi.mock('../components/VChart', () => ({
  VChart: ({ spec }: { spec: { title?: string } }) => <div data-testid="mock-chart">{spec?.title ?? 'chart'}</div>,
}))

function makeResearch(overrides: Record<string, unknown> = {}) {
  return {
    id: 'r1',
    title: '竞争调研报告',
    subtitle: '副标题',
    created_at: '2026-09-16T22:27:49',
    experts: ['e1'],
    toc: [{ id: 'sec-1', title: '章节一', level: 1 }],
    sections: [{ id: 'sec-1', title: '章节一', level: 1, paragraphs: ['正文'] }],
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

function renderPage(report: Record<string, unknown>) {
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
  holder.report = makeResearch()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ReportPage · 渲染适配器（A1）', () => {
  it('R2 — research 报告：保持原链路（报告目录边栏出现），不渲染体检单', () => {
    const { container } = renderPage(makeResearch())
    expect(screen.getByText('报告目录')).toBeTruthy()
    expect(screen.queryByText('完整章节报告')).toBeNull()
    expect(container.querySelector('.report-hero')).toBeTruthy() // 原英雄区仍在
  })

  it('R1 — living_circle 报告：渲染体检单（评分/三要素/盲区）', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    renderPage(report as unknown as Record<string, unknown>)
    expect(screen.getAllByText('体检单').length).toBeGreaterThan(0)
    expect(screen.getByText('65')).toBeTruthy() // 凯里综合评分
    for (const t of ['菜市场', '药店', '小学']) {
      expect(screen.getAllByText(new RegExp(t)).length).toBeGreaterThan(0)
    }
    expect(screen.getByText(/服务盲区清单/)).toBeTruthy()
    expect(screen.getByText(/盲区 4 处/)).toBeTruthy()
    // 演示数据横幅
    expect(screen.getByText(/演示数据模式/)).toBeTruthy()
  })

  it('R1 — 下层完整章节报告：概览 + 各章标题渲染，原页边栏不出现', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    renderPage(report as unknown as Record<string, unknown>)
    expect(screen.getByText('完整章节报告')).toBeTruthy()
    // 章节标题同时出现在 sticky 锚点条与正文标题，故用 >=1 断言
    for (const title of ['体检概览', '医疗配置', '教育设施', '菜市与购物', '养老配置', '可达性与等时圈', '服务盲区诊断', '体检结论与整改建议']) {
      expect(screen.getAllByText(title).length).toBeGreaterThan(0)
    }
    expect(screen.queryByText('报告目录')).toBeNull()
    // 术语表 + 方法论披露
    expect(screen.getByText('术语表')).toBeTruthy()
  })

  it('R4 — 双层视图接线：点「双样例对比」→ /compare；点返回 → /life-circle/kaili', async () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    renderPage(report as unknown as Record<string, unknown>)
    fireEvent.click(screen.getByRole('button', { name: /双样例对比/ }))
    expect(navigateFn).toHaveBeenCalledWith('/compare')
    navigateFn.mockClear()
    fireEvent.click(screen.getByTitle('返回体检地图'))
    await waitFor(() => expect(navigateFn).toHaveBeenCalledWith('/life-circle/kaili'))
  })

  it('R3 — 章节锚点：sticky 摘要条渲染全部章节入口（scroll-mt 保证锚定可读）', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    const { container } = renderPage(report as unknown as Record<string, unknown>)
    const nav = container.querySelector('header nav')
    expect(nav).toBeTruthy()
    expect(nav!.querySelectorAll('button').length).toBe(report.sections.length)
  })
})
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
import kaili from '../mocks/fixtures/livingCircle/kaili.json'

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
    title: '目的地调研报告',
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
    // 断言值从快照派生：重算快照后无需手改测试，但视图读错快照会立刻转红
    expect(screen.getByText(String(kaili.scores.total))).toBeTruthy()
    for (const t of ['菜市场', '药店', '小学']) {
      expect(screen.getAllByText(new RegExp(t)).length).toBeGreaterThan(0)
    }
    expect(screen.getByText(/服务盲区清单/)).toBeTruthy()
    expect(screen.getByText(new RegExp(`盲区 ${kaili.blindspots.length} 处`))).toBeTruthy()
    // 真实数据标注（M5 内置快照）
    expect(screen.getByText(/真实百度路网测时数据/)).toBeTruthy()
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

  it('R3-C1 — 章节导航迁至左侧竖排目录：入口在左栏 aside nav 且数量=章节数，header 不再承载', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    const { container } = renderPage(report as unknown as Record<string, unknown>)
    const nav = container.querySelector('aside nav')
    expect(nav).toBeTruthy()
    expect(nav!.querySelectorAll('button').length).toBe(report.sections.length)
    // 字号层级：目录用导航字号 text-aux（与 research「报告目录」同源），非 label/tag 小字号
    const firstBtn = nav!.querySelectorAll('button')[0]
    expect(firstBtn.getAttribute('class')).toContain('text-aux')
    expect(firstBtn.getAttribute('class')).not.toContain('text-tag')
    // C1：导航从顶部 header 迁出（旧顶部 sticky 锚点条不再出现）
    expect(container.querySelector('header nav')).toBeNull()
    // 顶部条仅保留入口/操作（双样例对比仍在顶条，见 R4）
    expect(container.querySelector('header')).toBeTruthy()
  })

  it('R3-C1 — research 报告不受影响：仍保留「报告目录」左栏（见 R2），living_circle 左栏为 aside nav', () => {
    // R2 已断言 research 走「报告目录」边栏；此处补齐 live 报告左栏与 research 不对撞
    const report = getLivingCircleReportMock('lc-kaili')!
    const { container } = renderPage(report as unknown as Record<string, unknown>)
    expect(container.querySelector('aside nav')).toBeTruthy()
    expect(report.report_type).toBe('living_circle')
  })

  it('R1-offline — 离线估算报告：评分/雷达/盲区占位 + 离线徽标，不出现误导性真实文案', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    const lc = report.living_circle!
    // 镜像 OfflineDataSource 契约（POI/盲区空 + total=0 + 圆形近似 + 骨架章节）
    const offline = {
      ...report,
      subtitle: '上海市 · 离线估算（区县中心近似）｜离线估算 · 评分待实时体检· 未联网采集 POI',
      sections: [
        { id: 'overview', title: '体检概览（离线估算）', level: 2, key_takeaway: '当前为离线估算模式', paragraphs: ['数据口径：data_origin=offline'], charts: [] },
        { id: 'isochrone', title: '可达性与等时圈', level: 2, key_takeaway: '圆形近似', paragraphs: ['离线模式未调用百度路网测时'], charts: [] },
        { id: 'conclusion', title: '体检结论（待实时体检）', level: 2, key_takeaway: '请发起实时体检', paragraphs: ['离线估算模式：不产出可比评分/盲区'], charts: [] },
      ],
      toc: [
        { id: 'overview', title: '体检概览（离线估算）', level: 2 },
        { id: 'isochrone', title: '可达性与等时圈', level: 2 },
        { id: 'conclusion', title: '体检结论（待实时体检）', level: 2 },
      ],
      living_circle: {
        ...lc,
        data_origin: 'offline' as const,
        sampling: { ...lc.sampling, interpolation: 'circular_approx' },
        poi: { categories: [], total: 0, in_circle: 0, points: [] },
        blindspots: [],
        scores: { ...lc.scores, total: 0, radar: [], bars: [], triads: [], note: '离线估算：未联网采集 POI——综合评分与服务盲区需实时体检后给出，且离线分不可与实时分比较' },
      },
    }
    renderPage(offline as unknown as Record<string, unknown>)
    // 徽标 + 横幅（离线估算，非真实测时）
    expect(screen.getAllByText('离线估算').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/未联网采集 POI/).length).toBeGreaterThan(0)
    // 评分占位（不渲染 0 分数字）
    expect(screen.getByText('评分待实时体检')).toBeTruthy()
    expect(screen.getByText(/分类雷达需实时体检数据/)).toBeTruthy()
    expect(screen.getByText(/盲区识别需实时体检后给出/)).toBeTruthy()
    // 不出现误导性真实/演示文案
    expect(screen.queryByText(/真实百度路网测时数据/)).toBeNull()
    expect(screen.queryByText(/演示数据模式/)).toBeNull()
  })
})
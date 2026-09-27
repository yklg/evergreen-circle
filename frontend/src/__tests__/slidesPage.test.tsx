// @vitest-environment jsdom
/**
 * 幻灯片页（SlidesPage，/report/:reportId/slides）测试（test-coverage-expander 方案）。
 *
 * 依赖的生产实现（TDD 红→绿，落地后转绿）：
 * - pages/SlidesPage.tsx：路由页自行 fetchReport(id)，渲染 16:9 幻灯片；
 *   键盘（←/→/空格/PgUp/PgDn/Home/End）+ 按钮翻页，底部页码，右上角「打印为 PDF」「返回报告」。
 * - 8 页精选模板：封面→执行摘要(summary)→数据速览→竞争格局(overview/feature)→护城河与反共识(moat/contrarian)
 *   →结论(conclusion)→风险(risk)→证据与信源；缺内容自动跳过且页码连续（无空白页）。
 *
 * 覆盖：加载渲染第一页；前后翻页（按钮+键盘）；页码正确；缺失章节时跳过且页码连续；打印按钮存在。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import SlidesPage from '../pages/SlidesPage'
import { pickSlideChart } from '../lib/slideChart'
import * as api from '../lib/api'
import type { Report } from '../types'

// 仅 mock api（纯对象 factory，规避 vi.mock(rrd, importOriginal) 的 hoist 竞态）；
// 路由用真实 MemoryRouter 渲染，「返回报告」用落地路由 stub 做行为断言。
vi.mock('../lib/api', () => ({
  fetchReport: vi.fn(),
}))

const mockedFetchReport = api.fetchReport as unknown as ReturnType<typeof vi.fn>

function makeReport(overrides: Partial<Report> = {}): Report {
  const id = overrides.id ?? 'r1'
  return {
    id,
    title: '测试报告',
    subtitle: '副标题',
    created_at: '2026-09-06T10:00:00',
    experts: [],
    cover_image: '',
    toc: [],
    claims: [],
    evidence: [
      { evidence_id: 'e1', source_url: 'https://a.com', source_type: 'official', title: 'E1', excerpt: '', credibility: 92, collected_by: '', destination: '', captured_at: '' },
      { evidence_id: 'e2', source_url: 'https://b.com', source_type: 'news', title: 'E2', excerpt: '', credibility: 80, collected_by: '', destination: '', captured_at: '' },
    ],
    figures: [],
    charts: [],
    glossary: [],
    sentiment: undefined,
    trace: [],
    metrics: {},
    audit_review: undefined,
    quality_before: undefined,
    quality_after: undefined,
    sections: [
      {
        id: 'summary',
        title: '执行摘要',
        level: 0,
        key_takeaway: '摘要核心判断',
        highlights: ['摘要亮点'],
        paragraphs: [],
        claims: [],
        charts: [],
      },
      {
        id: 'conclusion',
        title: '结论与行动建议',
        level: 1,
        key_takeaway: '结论判断',
        highlights: ['行动建议1'],
        paragraphs: [],
        claims: [],
        charts: [],
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  mockedFetchReport.mockReset()
})

afterEach(() => {
  cleanup()
})

function renderSlides(rid = 'r1', withReportLanding = false) {
  return render(
    <MemoryRouter initialEntries={[`/report/${rid}/slides`]}>
      <Routes>
        <Route path="/report/:reportId/slides" element={<SlidesPage />} />
        {withReportLanding && (
          <Route path="/report/:reportId" element={<div data-testid="report-landing">报告落地页</div>} />
        )}
      </Routes>
    </MemoryRouter>,
  )
}

describe('SlidesPage', () => {
  it('加载后第一页为封面（标题 + 页码 1 / N + 打印为 PDF 按钮）', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1')
    await waitFor(() => expect(mockedFetchReport).toHaveBeenCalledWith('r1'))
    expect(screen.getByText('测试报告')).toBeTruthy() // 封面标题
    expect(screen.getByText(/1 \/ \d+/)).toBeTruthy() // 页码
    expect(screen.getByRole('button', { name: /打印为 PDF/ })).toBeTruthy()
  })

  it('按钮翻页：下一张 → 执行摘要页；上一张 → 回封面', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1')
    await screen.findByText('测试报告')
    fireEvent.click(screen.getByRole('button', { name: /下一张|下一页|Next/ }))
    expect(await screen.findByText(/执行摘要/)).toBeTruthy()
    expect(screen.getByText(/2 \/ \d+/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /上一张|上一页|Prev/ }))
    expect(await screen.findByText(/1 \/ \d+/)).toBeTruthy()
  })

  it('键盘翻页：ArrowRight 前进、ArrowLeft 后退', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1')
    await screen.findByText('测试报告')
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(await screen.findByText(/执行摘要/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(await screen.findByText(/1 \/ \d+/)).toBeTruthy()
  })

  it('缺失章节自动跳过且页码连续（无空白页）', async () => {
    // 报告缺少 summary 节：数据速览(恒在)后直接是「结论与行动建议」，不再有执行摘要页，页码连续
    const noSummary = makeReport({ sections: [makeReport().sections[1]].filter(Boolean) })
    mockedFetchReport.mockResolvedValue(noSummary)
    renderSlides('r1')
    await screen.findByText('测试报告')
    // 第 2 页 = 数据速览（跳过 summary 后依旧连续）
    fireEvent.click(screen.getByRole('button', { name: /下一张|下一页|Next/ }))
    expect(await screen.findByText(/2 \/ \d+/)).toBeTruthy()
    expect(screen.queryByText(/执行摘要/)).toBeNull()
    // 第 3 页 = 结论与行动建议
    fireEvent.click(screen.getByRole('button', { name: /下一张|下一页|Next/ }))
    expect(await screen.findByText(/结论与行动建议/)).toBeTruthy()
    expect(screen.getByText(/3 \/ \d+/)).toBeTruthy()
  })

  it('「返回报告」→ 导航到报告页（落地路由出现）', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1', true)
    await screen.findByText('测试报告')
    fireEvent.click(screen.getByRole('button', { name: /返回报告/ }))
    await screen.findByTestId('report-landing')
    expect(screen.getByTestId('report-landing')).toBeTruthy()
  })

  it('键盘边界键：Home→首页、End→末页、PageDown/PageUp/空格', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1')
    await screen.findByText('测试报告')
    // makeReport 默认产出 5 页：封面/summary/速览/结论/证据
    fireEvent.keyDown(window, { key: 'PageDown' })
    expect(await screen.findByText(/2 \/ 5/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'PageUp' })
    expect(await screen.findByText(/1 \/ 5/)).toBeTruthy()
    fireEvent.keyDown(window, { key: ' ' }) // 空格 = 下一张
    expect(await screen.findByText(/2 \/ 5/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'End' })
    expect(await screen.findByText(/5 \/ 5/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'Home' })
    expect(await screen.findByText(/1 \/ 5/)).toBeTruthy()
  })

  it('越界保护：末页再按 End/下一张 页码不涨', async () => {
    mockedFetchReport.mockResolvedValue(makeReport())
    renderSlides('r1')
    await screen.findByText('测试报告')
    fireEvent.keyDown(window, { key: 'End' })
    expect(await screen.findByText(/5 \/ 5/)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'End' })
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(await screen.findByText(/5 \/ 5/)).toBeTruthy()
    const nextBtn = screen.getByRole('button', { name: /下一张/ })
    expect((nextBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('加载失败：显示错误与「返回报告」（不空白崩溃）', async () => {
    mockedFetchReport.mockRejectedValue(new Error('network'))
    renderSlides('r1', true)
    expect(await screen.findByText('报告加载失败')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /返回报告/ }))
    await screen.findByTestId('report-landing')
  })

  it('XSS 防护：标题/亮点含注入串时按纯文本渲染（不产生 img/script 标签）', async () => {
    const evilTitle = '<img src=x onerror=alert(1)>标题<script>alert(2)</script>'
    const evilHigh = '<img src=y onerror=alert(3)>亮点'
    const injected = makeReport({
      title: evilTitle,
      sections: [
        { ...makeReport().sections[0], key_takeaway: evilTitle, highlights: [evilHigh] },
        ...makeReport().sections.slice(1),
      ],
    })
    mockedFetchReport.mockResolvedValue(injected)
    const { container } = renderSlides('r1')
    // 注入标题以纯文本渲染（React 转义），不解析成 img/script
    await screen.findByText(/alert\(1\)/)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('alert(1)')
    fireEvent.click(screen.getByRole('button', { name: /下一张|下一页|Next/ }))
    // 摘要页：key_takeaway=evilTitle、highlights[0]=evilHigh 均以纯文本呈现
    expect((await screen.findByText(/alert\(1\)/)).textContent).toContain('alert(1)')
    expect(screen.getByText(/alert\(3\)/)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
  })
})

/* ── TC-22：幻灯片取图按类型择优，不按下标（词云口碑化修复 步骤 10）── */

const DONUT = { chart_id: 'c_donut', type: 'sentiment_donut', title: '情感分布', option: {} }
const CLOUD = { chart_id: 'c_cloud', type: 'wordcloud', title: '口碑词云', words: [] }
const BAR = { chart_id: 'c_bar', type: 'cost_bar', title: '花费结构', option: {} }

function reportWith(sentimentCharts: unknown[]) {
  return {
    sections: [
      { id: 'sentiment', title: '全网舆情', level: 1, key_takeaway: '', highlights: [], paragraphs: [], claims: [], charts: sentimentCharts },
      { id: 'cost', title: '花费', level: 1, key_takeaway: '', highlights: [], paragraphs: [], claims: [], charts: [BAR] },
    ],
  } as unknown as Report
}

describe('pickSlideChart · 低样本不换图', () => {
  it('情感环图在场时选环图', () => {
    expect(pickSlideChart(reportWith([DONUT, CLOUD]))?.chart_id).toBe('c_donut')
  })

  it('低样本 ⇒ 环图缺位时改选别处的结构化图，而不是舆情章的词云', () => {
    // 旧写法取「第一个含图章的 charts[0]」：这一栏会从 donut 静默变成 wordcloud，
    // 幻灯片内容随样本量改变；且分层词云在 200px 高的幻灯片里常整体放不下。
    expect(pickSlideChart(reportWith([CLOUD]))?.chart_id).toBe('c_bar')
  })

  it('全报告只有词云时退回词云；一张图都没有时返回 null（边界如实，不静默造图）', () => {
    const onlyCloud = { sections: [{ id: 'sentiment', charts: [CLOUD] }] } as unknown as Report
    expect(pickSlideChart(onlyCloud)?.chart_id).toBe('c_cloud')
    expect(pickSlideChart(makeReport())).toBeNull()
  })
})
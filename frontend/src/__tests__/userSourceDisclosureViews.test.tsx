// @vitest-environment jsdom
/**
 * 报告页与情报中心的「用户指定信源」呈现（计划 v3 §二 B5/B6/F1 · §八 TC-33/TC-37/TC-38）。
 *
 * 三组判据分别守三个真实缺陷形状：
 * 1. 报告页举证块：读数必须**来自服务端**（`report["user_sources"]`），前端一行都不自己算 ——
 *    否则这里就成了第三个口径，和覆盖率/证据链两处各自漂移；
 * 2. 旧报告（没有这个块）不得报错，也不得凭空显示"共 0 条"；
 * 3. 情报中心的口径说明行**只在含用户指定信源时出现**（degradeDisclosure 同源纪律：
 *    一句永远在的话等于没有话）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import type { DestinationGraphNode, IntelOverview } from '../types'
import ReportPage from '../pages/ReportPage'

const mocks = vi.hoisted(() => ({
  fetchIntel: vi.fn(),
  fetchEvidences: vi.fn(),
  fetchSubscriptions: vi.fn(),
  fetchWorkload: vi.fn(),
  fetchDashboard: vi.fn(),
  fetchLifeCircleReports: vi.fn(),
  createSubscription: vi.fn(),
  deleteReport: vi.fn(),
  deleteLifeCircleReport: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  fetchIntel: mocks.fetchIntel,
  fetchEvidences: mocks.fetchEvidences,
  fetchSubscriptions: mocks.fetchSubscriptions,
  fetchWorkload: mocks.fetchWorkload,
  fetchDashboard: mocks.fetchDashboard,
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
  createSubscription: mocks.createSubscription,
  deleteReport: mocks.deleteReport,
  deleteLifeCircleReport: mocks.deleteLifeCircleReport,
  refineSection: vi.fn(),
  submitFeedback: vi.fn(),
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
}))

vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({ current: holder.report, loading: false, error: null, load: vi.fn() }),
}))

const holder = { report: {} as Record<string, unknown> }

function makeReport(overrides: Record<string, unknown> = {}) {
  return {
    id: 'r1', title: '测试报告', subtitle: '', created_at: '2026-09-28T10:00:00',
    experts: [], cover_image: '', toc: [], sections: [], claims: [], evidence: [],
    figures: [], trace: [], glossary: [], ...overrides,
  }
}

function renderReport(report: Record<string, unknown>) {
  holder.report = report
  return render(
    <MemoryRouter initialEntries={['/report/r1']}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const BLOCK = {
  label: '用户指定',
  summary: {
    total: 4, cited: 2, uncited: 1, unread: 1, blocked: 0,
    gated_off_query: 0, merged: 1, pending: 0, denominator: 3, rate: 0.667,
  },
  items: [
    { uid: 'u1', url: 'https://gov.cn/a', url_canonical: 'https://gov.cn/a', state: 'fetched',
      coverage: 'cited', reason: '', evidence_id: 'e1', group_id: '', bytes: 2048, ms: 700,
      cited_by: ['c1'] },
    { uid: 'u2', url: 'https://x.cn/b', url_canonical: 'https://x.cn/b', state: 'unread',
      coverage: 'unread', reason: 'HTTP 404', evidence_id: '', group_id: '', bytes: 0, ms: 300,
      cited_by: [] },
    { uid: 'u3', url: 'https://y.cn/c', url_canonical: 'https://y.cn/c', state: 'merged',
      coverage: 'cited', reason: '', evidence_id: '', group_id: 'g1', bytes: 0, ms: 500,
      cited_by: ['c2'] },
    { uid: 'u4', url: 'https://z.cn/d', url_canonical: 'https://z.cn/d', state: 'fetched',
      coverage: 'uncited', reason: '', evidence_id: 'e4', group_id: '', bytes: 900, ms: 400,
      cited_by: [] },
  ],
  note: '本报告含用户指定信源 4 条（已引用 2 · 未引用 1 · 未读取 1 · 闸门拒绝 0 · 跑题诊断 0 · 归并 1），已计入信源分布与多源互证口径。',
}

beforeEach(() => {
  vi.clearAllMocks()
  holder.report = makeReport()
})

afterEach(() => {
  cleanup()
  holder.report = {}
})

describe('报告页举证块', () => {
  it('逐桶数字原样来自服务端 summary（前端不重算）', () => {
    renderReport(makeReport({ user_sources: BLOCK }))
    expect(screen.getByText(/共 4 条/)).toBeTruthy()
    // 用**整串精确匹配**：note 里也含同样的字样，正则会把两块都捞到（判据要指到具体那一行）
    expect(
      screen.getByText('已引用 2 · 未引用 1 · 未读取 1 · 闸门拒绝 0 · 跑题诊断 0 · 归并 1'),
    ).toBeTruthy()
    expect(screen.getByText(BLOCK.note)).toBeTruthy()
  })

  it('四条各自说清"用没用上 + 读没读到"，被拒原因可见', () => {
    renderReport(makeReport({ user_sources: BLOCK }))
    expect(screen.getByText('https://x.cn/b')).toBeTruthy()
    expect(screen.getByText('HTTP 404')).toBeTruthy()
    // 归并条目按组核算为已引用（A-3），显示的是覆盖率桶而不是读取态
    expect(screen.getAllByText('已引用').length).toBe(2)
    expect(screen.getByText('未引用')).toBeTruthy()
    expect(screen.getByText('与既有信源同质 · 已归并')).toBeTruthy()
  })

  it('旧报告没有这个块 ⇒ 整块不出现，也不报"共 0 条"', () => {
    renderReport(makeReport())
    expect(screen.queryByText(/共 0 条/)).toBeNull()
    expect(screen.queryByText(/用户指定信源/)).toBeNull()
  })

  it('举证块里每一条都能在证据链上找到对应标签的条目（口径一致性人工核对的自动化版）', () => {
    const evidence = [
      { evidence_id: 'e1', source_url: 'https://gov.cn/a', source_type: 'user_supplied',
        domain: 'gov.cn', title: '公报A', excerpt: 'x', credibility: 60,
        collected_by: 'user_supplied', captured_at: '2026-09-28T10:00:00' },
      { evidence_id: 'e4', source_url: 'https://z.cn/d', source_type: 'user_supplied',
        domain: 'z.cn', title: '公报D', excerpt: 'y', credibility: 60,
        collected_by: 'user_supplied', captured_at: '2026-09-28T10:00:00' },
    ]
    renderReport(makeReport({ user_sources: BLOCK, evidence }))
    // 举证块 total=4，其中 2 条 merged/unread 不独立成行 ⇒ 证据链上带「用户指定」标签的恰是 2 行
    expect(screen.getAllByText('用户指定').length).toBe(2)
  })
})

function intelPayload(over: Partial<IntelOverview> = {}): IntelOverview {
  return {
    report_total: 2, evidence_total: 100, claim_total: 8, high_conf_total: 4,
    avg_evidence_per_report: 50, fact_accuracy: 60,
    platform_distribution: { official: 60, news: 30, user_supplied: 10 },
    user_source_evidence: 10,
    distribution_note: '信源分布含用户指定信源 10 条（由调研时手填的网址直接抓取入库，计入占比与可信度口径）。',
    destination_graph: { nodes: [], unattributed: 0, scanned: 100 },
    minutes_saved: 60, avg_efficiency: 6, avg_coverage: 3, total_tokens: 5000,
    cards: [], cards_truncated: false,
    ...over,
  } as IntelOverview
}

describe('情报中心口径说明行与第四类', () => {
  async function renderIntel(payload: IntelOverview) {
    mocks.fetchIntel.mockResolvedValue(payload)
    mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { by_destination: {}, by_type: {} }, total: 0 })
    mocks.fetchSubscriptions.mockResolvedValue([])
    mocks.fetchWorkload.mockResolvedValue([])
    const { default: ResearchIntelView } = await import('../pages/reports/ResearchIntelView')
    render(
      <MemoryRouter>
        <ResearchIntelView onDelete={vi.fn()} refreshToken={0} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('信源结构与研判')).toBeTruthy())
  }

  it('含用户指定信源 ⇒ 说明行在位，且分布条多出一类「用户指定」', async () => {
    await renderIntel(intelPayload())
    expect(screen.getByText(/信源分布含用户指定信源 10 条/)).toBeTruthy()
    expect(screen.getByText('用户指定 10%')).toBeTruthy()
  })

  it('不含用户指定信源 ⇒ 说明行与这一类都不出现（永远在的话等于没有话）', async () => {
    await renderIntel(intelPayload({
      platform_distribution: { official: 60, news: 40 },
      user_source_evidence: 0,
      distribution_note: '',
    }))
    expect(screen.queryByText(/信源分布含用户指定信源/)).toBeNull()
    expect(screen.queryByText(/^用户指定/)).toBeNull()
  })

  it('未进三类映射的类别按注册表标签点名（不是裸 key 上屏）', async () => {
    // `unknown` 在注册表里登记为「未归类」，但不在展示层的四类映射中 ⇒ 应显示中文标签。
    // 判据刻意用完整串：若哪天有人把 kindLabel 换回裸 key，这里会出现 `未归类信源：unknown`。
    await renderIntel(intelPayload({
      platform_distribution: { official: 60, unknown: 40 },
      user_source_evidence: 0,
      distribution_note: '',
    }))
    expect(screen.getByText(/^未归类信源：未归类（计入/)).toBeTruthy()
  })
})

describe('全局证据溯源库 · 类别标签取注册表（G0 展示面）', () => {
  async function renderLibrary() {
    const { default: EvidenceAndTracking } = await import('../pages/reports/EvidenceAndTracking')
    mocks.fetchEvidences.mockResolvedValue({
      items: [
        { evidence_id: 'e_u1', report_id: 'r1', source_url: 'https://www.gov.cn/gongbao',
          source_type: 'user_supplied', domain: 'gov.cn', title: '全省文旅公报',
          excerpt: '正文……', credibility: 62, collected_by: 'user_supplied',
          destination: '', captured_at: '2026-09-28T10:00:00' },
      ],
      facets: {
        total: 6,
        by_type: { user_supplied: 1, official: 5 },
        by_destination: { 大理: 5 },
      },
    })
    mocks.fetchSubscriptions.mockResolvedValue([])
    const nodes: DestinationGraphNode[] = [
      { destination: '大理', domain: 'travel', source: 'bocha', count: 5,
        source_types: ['official'], avg_credibility: 58, last_at: null },
    ]
    const view = render(
      <MemoryRouter>
        <EvidenceAndTracking enabled refreshToken={0} nodes={nodes} evidenceTotal={6} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('全省文旅公报')).toBeTruthy())
    return view
  }

  it('筛选 chip 与行内标签都是中文名，整屏不出现裸 key', async () => {
    const { container } = await renderLibrary()
    // 两处独立判据：chip 的标签带计数（"用户指定 1"），行内标签是裸类别名。
    // 改前这两处都渲染 `user_supplied` ⇒ 下面三行都会红。
    expect(screen.getByRole('button', { name: '用户指定 1' })).toBeTruthy()
    expect(screen.getAllByText('用户指定').length).toBe(1)
    expect(container.textContent ?? '').not.toContain('user_supplied')
    // destination-less（§一 A-2）必须显式说清"无目的地归属"，不是留一个空位
    expect(screen.getByText('无目的地归属')).toBeTruthy()
  })

  it('点选类别 chip：回显用中文，但**查询值**仍是后端 key', async () => {
    await renderLibrary()
    fireEvent.click(screen.getByRole('button', { name: '用户指定 1' }))
    await waitFor(() => expect(mocks.fetchEvidences.mock.calls.length).toBeGreaterThan(1))
    const last = mocks.fetchEvidences.mock.calls[mocks.fetchEvidences.mock.calls.length - 1]?.[0] as
      | { source_type?: string }
      | undefined
    expect(last?.source_type).toBe('user_supplied')
    expect(screen.getByText(/信源 用户指定/)).toBeTruthy()
  })
})

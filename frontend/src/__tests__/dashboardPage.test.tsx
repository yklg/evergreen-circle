// @vitest-environment jsdom
/**
 * F4 目的地情报中心（F4-1 ~ F4-3）
 *
 * 覆盖缺口（计划 §5.3 D5 / §5.4 F4）：DashboardPage 的 destination 语义改名与
 * 客户端筛选此前无测试。
 * 守护契约：
 *   F4-1  「目的地情报中心」标题 + 覆盖目的地指标 + 图谱按目的地聚合（静态文本口径）
 *   F4-2  destinationFilter 切换（facet chip / 图谱行 / 「全部」重置）
 *   F4-3  空数据：reports=0 空态；有报告但无带目的地证据 → 空提示，且全程无 NaN
 *
 * 事实订正（避免断言与实际行为脱节）：本页筛选是**客户端过滤**（`filteredEv`），
 * 不发 `?destination=` 请求 —— `GET /api/evidences?destination=` 由后端与 api 层提供，
 * 本页未接线。故这里断言列表收缩与「当前 N 条」，不断言不存在的请求参数。
 *
 * 数值断言取静态文本（如「2 条 · 2 类信源 · 可信 85%」）；大数字走 VCountUp 动画
 * （framer 0→value，jsdom 下异步），故不断言动画中的数字。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DashboardPage from '../pages/DashboardPage'
import * as api from '../lib/api'

vi.mock('../lib/api', () => ({
  fetchDashboard: vi.fn(),
  fetchEvidences: vi.fn(),
  fetchSubscriptions: vi.fn(),
  createSubscription: vi.fn(),
  deleteSubscription: vi.fn(),
  fetchWorkload: vi.fn(),
}))

const m = {
  dashboard: api.fetchDashboard as unknown as ReturnType<typeof vi.fn>,
  evidences: api.fetchEvidences as unknown as ReturnType<typeof vi.fn>,
  subs: api.fetchSubscriptions as unknown as ReturnType<typeof vi.fn>,
  workload: api.fetchWorkload as unknown as ReturnType<typeof vi.fn>,
}

const ev = (id: string, destination: string, source_type: string, credibility: number, title: string) => ({
  evidence_id: id,
  report_id: 'r1',
  source_url: `https://example.com/${id}`,
  source_type,
  domain: 'example.com',
  title,
  excerpt: `${title} 摘要`,
  credibility,
  collected_by: 'L1-001',
  destination,
  captured_at: '2026-09-10T10:00:00',
})

const ITEMS = [
  ev('e1', '大理', 'official', 0.9, '大理E1'),
  ev('e2', '大理', 'xiaohongshu', 0.8, '大理E2'),
  ev('e3', '成都', 'news', 0.7, '成都E3'),
]

const STATS = {
  reports: 2,
  evidence_total: 3,
  claim_total: 5,
  high_conf_total: 2,
  avg_evidence_per_report: 1.5,
  fact_accuracy: 66,
  platform_distribution: {},
  destination_distribution: { 大理: 2, 成都: 1 },
  minutes_saved: 120,
  avg_efficiency: 3.2,
  avg_coverage: 1.4,
  total_tokens: 12345,
  research_cards: [],
}

beforeEach(() => {
  m.dashboard.mockReset().mockResolvedValue(STATS)
  m.evidences.mockReset().mockResolvedValue({
    items: ITEMS,
    facets: { total: 3, by_type: { official: 1, xiaohongshu: 1, news: 1 }, by_destination: { 大理: 2, 成都: 1 } },
  })
  m.subs.mockReset().mockResolvedValue([])
  m.workload.mockReset().mockResolvedValue([])
})

afterEach(() => cleanup())

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

/* 图谱行按钮由「目的地 span + 统计 span」拼成（JSX 换行被剥离 → 无空白分隔），
   其 accessible name 会把两段粘在一起，故用目的地文本定位到按钮本体。 */
function graphRow(destination: string): HTMLButtonElement {
  const el = screen.getByText(destination).closest('button')
  expect(el, `未找到图谱行：${destination}`).not.toBeNull()
  return el as HTMLButtonElement
}

describe('F4 目的地情报中心', () => {
  it('F4-1 标题与覆盖目的地指标；图谱按目的地聚合（条数/信源类数/可信度）', async () => {
    const { container } = renderDashboard()
    await waitFor(() => expect(screen.getByText('目的地情报中心')).toBeTruthy())

    expect(screen.getByText('覆盖目的地')).toBeTruthy()
    expect(screen.getByText(/目的地情报图谱/)).toBeTruthy()
    expect(screen.getByText(/目的地持续追踪/)).toBeTruthy()

    // 大理：2 条证据 / 2 类信源 / 平均可信度 85%；成都：1 条 / 1 类 / 70%
    expect(screen.getByText(/2 条 · 2 类信源 · 可信 85%/)).toBeTruthy()
    expect(screen.getByText(/1 条 · 1 类信源 · 可信 70%/)).toBeTruthy()
    expect(container.textContent).not.toContain('NaN')
    // 历史竞品口径残留守卫
    expect(container.textContent).not.toContain('竞争情报中心')
    expect(container.textContent).not.toContain('覆盖品牌')
  })

  it('F4-2 destinationFilter 切换：facet chip 过滤 → 图谱行切换 → 「全部」重置', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('大理E1')).toBeTruthy())
    expect(screen.getByText('成都E3')).toBeTruthy()
    expect(screen.getByText(/共 3 条 · 当前 3 条/)).toBeTruthy()

    // facet chip「大理 2」→ 仅剩大理证据
    fireEvent.click(screen.getByRole('button', { name: '大理 2' }))
    expect(screen.getByText('大理E1')).toBeTruthy()
    expect(screen.queryByText('成都E3')).toBeNull()
    expect(screen.getByText(/共 3 条 · 当前 2 条/)).toBeTruthy()

    // 图谱行「成都」→ 切到成都（单选，非叠加）
    fireEvent.click(graphRow('成都'))
    expect(screen.getByText('成都E3')).toBeTruthy()
    expect(screen.queryByText('大理E1')).toBeNull()

    // 「全部」→ 复位
    fireEvent.click(screen.getByRole('button', { name: '全部' }))
    expect(screen.getByText('大理E1')).toBeTruthy()
    expect(screen.getByText('成都E3')).toBeTruthy()
  })

  it('F4-3 空数据：reports=0 空态 CTA；无带目的地证据时给空提示且无 NaN', async () => {
    m.dashboard.mockResolvedValue({ ...STATS, reports: 0, evidence_total: 0, claim_total: 0 })
    const empty = renderDashboard()
    await waitFor(() => expect(screen.getByText('情报库还是空的')).toBeTruthy())
    expect(screen.getByRole('button', { name: '发起新调研' })).toBeTruthy()
    empty.unmount()

    // 有报告但证据列表为空 / facets 为空 → 图谱与证据库各自空态，不崩
    m.dashboard.mockResolvedValue(STATS)
    m.evidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
    const { container } = renderDashboard()
    await waitFor(() => expect(screen.getByText('尚无带目的地标注的证据')).toBeTruthy())
    expect(screen.getByText('暂无匹配证据')).toBeTruthy()
    expect(screen.getByText('还没有追踪订阅')).toBeTruthy()
    expect(container.textContent).not.toContain('NaN')
    expect(container.textContent).not.toContain('undefined')
  })
})

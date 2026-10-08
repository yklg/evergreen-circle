// @vitest-environment jsdom
/**
 * F3 幻灯片按调研类型映射内页（F3-1 ~ F3-3）
 *
 * 覆盖缺口（计划 §5.3 D7 / §5.4 F3）：`SLIDE_TYPES` 类型化映射与页眉文案此前无测试。
 * 守护契约：
 *   F3-1  guide 取 route→transport；assessment 取 accessibility→amenities（含首个命中的顺序契约）
 *   F3-2  焦点/洞察章节缺失 → 该页整页跳过，页码仍连续（不出现空白页）
 *   F3-3  页眉 kind 与封面「调研范围」按类型/目的地切换
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import SlidesPage from '../pages/SlidesPage'
import * as api from '../lib/api'
import type { Report, ReportSection } from '../types'

vi.mock('../lib/api', () => ({ fetchReport: vi.fn() }))

const mockedFetchReport = api.fetchReport as unknown as ReturnType<typeof vi.fn>

beforeEach(() => mockedFetchReport.mockReset())
afterEach(() => cleanup())

const sec = (id: string, title: string, extra: Partial<ReportSection> = {}): ReportSection => ({
  id,
  title,
  level: 1,
  key_takeaway: `${title}·核心判断`,
  highlights: [`${title}·亮点`],
  paragraphs: [],
  claims: [],
  charts: [],
  ...extra,
})

function makeReport(rtype: string, sections: ReportSection[]): Report {
  return {
    id: 'r1',
    title: '测试报告',
    subtitle: '副标题',
    research_type: rtype,
    created_at: '2026-09-06T10:00:00',
    destinations: ['大理', '丽江'],
    experts: [],
    cover_image: '',
    toc: [],
    claims: [],
    evidence: [
      { evidence_id: 'e1', source_url: 'https://a.com', source_type: 'official', title: 'E1', excerpt: '', credibility: 92, collected_by: '', destination: '大理', captured_at: '' },
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
    sections,
  }
}

function renderSlides() {
  return render(
    <MemoryRouter initialEntries={['/report/r1/slides']}>
      <Routes>
        <Route path="/report/:reportId/slides" element={<SlidesPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const nextPage = () => fireEvent.keyDown(window, { key: 'ArrowRight' })

/** 从页码条「N / M」里读出总页数 —— 不硬编码：跳过页的规则一改，M 就跟着变。 */
async function slideTotal(): Promise<number> {
  const el = await screen.findByText(/\d+\s*\/\s*\d+/)
  const m = el.textContent?.match(/\/\s*(\d+)/)
  expect(m, '页码条没读到总页数').toBeTruthy()
  return Number(m![1])
}

/**
 * 翻一页，并**等页码真的走到第 n 页**再往下走。
 *
 * 原来这里是一次性连按三次、然后才 `findByText` 等最终内容。页码条是每页必更新的同步点，
 * 拿它当栅栏之后「等到页码」就等于「等到渲染」。改动前那种写法在真 CI 上抽中过：
 * 2026-10-08 `e821d47` 首次 run 红在 `findByText(「行程与路线」)`（testing-library 默认 1000ms），
 * 重跑同一条 commit 即全绿 ⇒ 计时抖动而非内容回归（本地默认／2 并发／全串行三档调度
 * 各 1236 passed 也抽不中）。**断言一条没动**，只是把等待补到每一步。
 * ⚠️ 正则前后各带一个数字边界：`2 / 5` 是 `12 / 5` 的子串，不加会串页。
 */
async function goToPage(n: number, total: number): Promise<void> {
  nextPage()
  await screen.findByText(new RegExp(`(?<!\\d)${n}\\s*/\\s*${total}(?!\\d)`))
}

describe('F3 幻灯片类型映射', () => {
  it('F3-1 guide 焦点页取 route（route 缺则回落 transport）；assessment 取 accessibility', async () => {
    // guide：route 与 transport 同时存在 → 取 route（焦点页 h1 = 「行程与路线」+ route 内容）
    mockedFetchReport.mockResolvedValue(
      makeReport('guide', [
        sec('summary', '执行摘要'),
        sec('transport', '交通与抵达'),
        sec('route', '逐日路线'),
        sec('conclusion', '结论与行动建议'),
      ]),
    )
    const g = renderSlides()
    await screen.findByText('测试报告')
    const total = await slideTotal()
    await goToPage(2, total) // 执行摘要
    await goToPage(3, total) // 关键数据速览
    await goToPage(4, total) // 焦点页
    expect(screen.getByText('行程与路线')).toBeTruthy()
    expect(screen.getByText('逐日路线·核心判断')).toBeTruthy()
    expect(screen.queryByText('交通与抵达·核心判断')).toBeNull()
    g.unmount()

    // guide：无 route → 回落 transport
    mockedFetchReport.mockResolvedValue(
      makeReport('guide', [sec('summary', '执行摘要'), sec('transport', '交通与抵达')]),
    )
    const g2 = renderSlides()
    await screen.findByText('测试报告')
    const total2 = await slideTotal()
    await goToPage(2, total2)
    await goToPage(3, total2)
    await goToPage(4, total2)
    expect(screen.getByText('交通与抵达·核心判断')).toBeTruthy()
    g2.unmount()

    // assessment：焦点页取 accessibility，且绝不出现 guide 的「行程与路线」
    mockedFetchReport.mockResolvedValue(
      makeReport('assessment', [
        sec('summary', '执行摘要'),
        sec('accessibility', '可达性'),
        sec('amenities', '配套完善度'),
        sec('verdict', '综合研判'),
      ]),
    )
    renderSlides()
    await screen.findByText('测试报告')
    const total3 = await slideTotal()
    await goToPage(2, total3)
    await goToPage(3, total3)
    await goToPage(4, total3)
    expect(screen.getByText('可达性与配套')).toBeTruthy()
    expect(screen.getByText('可达性·核心判断')).toBeTruthy()
    await goToPage(5, total3) // 洞察页
    expect(screen.getByText('研判与反共识')).toBeTruthy()
    expect(screen.getByText('综合研判')).toBeTruthy()
    expect(screen.queryByText('行程与路线')).toBeNull()
  })

  it('F3-2 焦点/洞察章节缺失 → 整页跳过且页码连续（无空白页）', async () => {
    // guide 报告既无 route 也无 transport，且无 tips/season/contrarian → 焦点页与洞察页都跳过
    mockedFetchReport.mockResolvedValue(
      makeReport('guide', [sec('summary', '执行摘要'), sec('conclusion', '结论与行动建议')]),
    )
    renderSlides()
    await screen.findByText('测试报告')
    // 页数 = 封面 + 摘要 + 速览 + 结论 + 证据 = 5（跳过的两页不计入）
    expect(screen.getByText(/1 \/ 5/)).toBeTruthy()
    nextPage()
    expect(await screen.findByText(/2 \/ 5/)).toBeTruthy()
    nextPage()
    expect(await screen.findByText(/3 \/ 5/)).toBeTruthy()
    expect(screen.getByText('关键数据速览')).toBeTruthy()
    nextPage()
    expect(await screen.findByText(/4 \/ 5/)).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1, name: '结论与行动建议' })).toBeTruthy()
    // 焦点页标题从未出现（整页被跳过，而非渲染成空页）
    expect(screen.queryByText('行程与路线')).toBeNull()
    expect(screen.queryByText('避坑与反共识')).toBeNull()
  })

  it('F3-3 页眉 kind 与封面「调研范围」按类型/目的地切换', async () => {
    mockedFetchReport.mockResolvedValue(
      makeReport('assessment', [sec('summary', '执行摘要'), sec('conclusion', '结论')]),
    )
    const a = renderSlides()
    await screen.findByText('测试报告')
    expect(document.body.textContent).toContain('调研评估汇报')
    expect(screen.getByText(/调研范围：大理 · 丽江/)).toBeTruthy()
    a.unmount()

    mockedFetchReport.mockResolvedValue(
      makeReport('guide', [sec('summary', '执行摘要'), sec('conclusion', '结论')]),
    )
    renderSlides()
    await screen.findByText('测试报告')
    expect(document.body.textContent).toContain('旅游攻略汇报')
    expect(document.body.textContent).not.toContain('调研评估汇报')
  })
})

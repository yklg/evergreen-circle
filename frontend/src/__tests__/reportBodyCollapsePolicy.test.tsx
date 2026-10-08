// @vitest-environment jsdom
/**
 * 两个报告页的正文折叠门槛 —— 守「**不同是决定，不是漏写**」这句话本身。
 *
 * 背景：用户问「为什么有的章节有『展开完整正文』有的没有」。实测结论是既定的两段式契约：
 *  - 生活圈 `LifeCircleReportView.tsx` 门槛 **2**：≤2 段直出、>2 段才折叠
 *    （改动前落库的报告只有 2 段，一律折叠会让老报告观感凭空变样）；
 *  - 调研 `ReportPage.tsx` 门槛 **0**：只要有一段就收进 `<details>`
 *    （C1「结论先行」刻意把正文全部收起）。
 *
 * 为什么现有判据不够：`reportLayoutC1.test.tsx` 的 C-F2 用**三段**夹具 ⇒ 把调研侧门槛
 * 从 0 改成 2 它照样绿。也就是说"顺手把两边统一一下"这种改法**没有任何东西会红** ——
 * 本文件的调研侧那条就是补这个缺口的唯一闸（1 段仍必须折叠）。
 *
 * 两侧唯一的同源硬约束不在这里测（它由 `reportLayoutC1` C-F2 与 `lcReportBodyBlocks` B3
 * 各自钉住类名 `report-body-collapse` + 打印留底 CSS）：折叠必须用同一个类名，
 * 因为 beforeprint 是按**类名**选节点强制展开的，换名 = 导出 PDF 丢正文。
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const { holder } = vi.hoisted(() => ({ holder: { report: {} as Record<string, unknown> } }))

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
  fetchReport: vi.fn(),
  generateReportBrief: vi.fn(),
}))

vi.mock('../components/VChart', () => ({
  VChart: ({ spec }: { spec: { title?: string } }) => <div data-testid="mock-chart">{spec?.title ?? 'chart'}</div>,
}))

import ReportPage from '../pages/ReportPage'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** 只带正文的调研报告：把图件/结构化块/明细表全部拿掉，折叠与否就只由段数决定。 */
function researchReport(paragraphs: string[]) {
  return {
    id: 'r_policy',
    title: '折叠门槛探针报告',
    subtitle: '',
    created_at: '',
    experts: [],
    cover_image: '',
    toc: [],
    sections: [{
      id: 'overview',
      title: '概览',
      level: 2,
      key_takeaway: '核心判断',
      paragraphs,
      claims: [],
      charts: [],
      source_evidence_ids: [],
    }],
    claims: [],
    evidence: [],
    figures: [],
    trace: [],
    glossary: [],
  }
}

/** 演示态生活圈报告，逐章把正文压成 n 段。 */
function lcReportWithParagraphs(n: number) {
  const base = JSON.parse(JSON.stringify(getLivingCircleReportMock('lc-kaili'))) as {
    sections: Record<string, unknown>[]
  } & Record<string, unknown>
  base.sections = base.sections.map((s) => ({ ...s, paragraphs: Array.from({ length: n }, (_, i) => `第${i + 1}段正文`) }))
  return base as unknown as Record<string, unknown>
}

afterEach(() => {
  cleanup()
  holder.report = {}
})

describe('折叠门槛 · 调研侧 = 0（C1 决定：全部段落收进折叠）', () => {
  it('只有一段也必须折叠 —— 这条是"顺手统一阈值"的唯一闸', () => {
    holder.report = researchReport(['只有这一段'])
    const { container } = renderAt('/report/r_policy')
    const d = container.querySelector('details.report-body-collapse[data-section-body="overview"]')
    expect(d).toBeTruthy()
    expect(d!.textContent).toContain('展开完整正文（共 1 段）')
    // 折叠是呈现态：内容仍在 DOM 里，不许卸载
    expect(d!.textContent).toContain('只有这一段')
  })

  it('正文为空时整块不出现（既没有 details 也没有空壳）', () => {
    holder.report = researchReport([])
    const { container } = renderAt('/report/r_policy')
    expect(container.querySelector('details.report-body-collapse')).toBeNull()
  })
})

describe('折叠门槛 · 生活圈侧 = 2（短章直出，长章才收）', () => {
  it('1 段与 2 段都不折叠：正文直接铺在章里', () => {
    for (const n of [1, 2]) {
      holder.report = lcReportWithParagraphs(n)
      const { container } = renderAt('/report/lc-1')
      expect(container.querySelector('details.report-body-collapse'), `${n} 段章不该出现折叠条`).toBeNull()
      expect(container.textContent).toContain('第1段正文')
      cleanup()
    }
  })

  it('3 段起必须折叠，且折叠条报出真实段数', () => {
    holder.report = lcReportWithParagraphs(3)
    const { container } = renderAt('/report/lc-1')
    const d = container.querySelector('details.report-body-collapse')
    expect(d, '3 段章没折叠 ⇒ 门槛被改大了').toBeTruthy()
    expect(d!.textContent).toContain('展开完整正文（共 3 段）')
  })
})

// @vitest-environment jsdom
/**
 * C1 版式全章化（N1 / rugged-lagoon-merlin C-F1~C-F4）
 *
 * 守护契约（ReportPage 章节重排 + 折叠交互完整性）：
 *   C-F1 同章 DOM 顺序：核心判断 → 图表 → 结构化块 → 数据空间 → 正文（首段评注直出）
 *        （T-12′：批次②后每章可同时有 charts + structured + data_grid，五段全序一次钉死）
 *   C-F2 正文默认折叠（details 无 open、内容不卸载）+ index.css 打印展开留底（仿 H15 手法）
 *   C-F3 编辑模式自动 open（折叠不切断编辑路径）
 *   C-F4 本章高亮命中 → 折叠体自动 open（折叠不切断高亮路径）
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { currentRef } = vi.hoisted(() => ({
  currentRef: { current: undefined as unknown },
}))

vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({
    current: currentRef.current,
    loading: false,
    error: null,
    load: () => {},
  }),
}))

vi.mock('../lib/api', () => ({
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
  fetchReport: vi.fn(),
  generateReportBrief: vi.fn(),
}))

import ReportPage from '../pages/ReportPage'
import { useAnnotationStore } from '../store/annotationStore'

const SECTION = {
  id: 'overview',
  title: '概览',
  key_takeaway: '核心判断',
  paragraphs: ['第一段评注', '第二段正文', '第三段正文'],
  highlights: ['亮点一'],
  claims: [],
  charts: [
    {
      chart_id: 'ch_c1',
      type: 'wordcloud',
      title: '口碑词云',
      words: [{ word: '古城', weight: 5 }],
      evidence_ids: [],
    },
  ],
  structured: {
    type: 'access_matrix',
    data: [
      {
        destination: '成都',
        routes: [{ mode: '高铁', duration: '1.5 小时', cost: '180 元', frequency: '每小时 2 班' }],
      },
    ],
  },
  data_grid: {
    columns: ['数据名', '值', '指标', '来源', '来源网址'],
    rows: [{
      name: '成都 · 高铁', value: '95', metric: '耗时（分钟）',
      source: 'a.example.com', source_url: 'https://a.example.com/x',
    }],
  },
}

const REPORT = {
  id: 'r_c1',
  title: 'C1 版式测试报告',
  subtitle: '',
  created_at: '',
  experts: [],
  cover_image: '',
  toc: [],
  sections: [SECTION],
  claims: [],
  evidence: [],
  figures: [],
  trace: [],
  glossary: [],
}

beforeEach(() => {
  currentRef.current = REPORT
})

afterEach(() => {
  cleanup()
  currentRef.current = undefined
  useAnnotationStore.setState({ annotations: {} })
})

function renderReport() {
  return render(
    <MemoryRouter initialEntries={['/report/r_c1']}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function detailsEl(container: HTMLElement) {
  return container.querySelector('details[data-section-body="overview"]') as HTMLDetailsElement
}

describe('C1 章节版式', () => {
  it('C-F1：同章「核心判断 → 图表 → 结构化块 → 数据空间 → 正文」全序钉', () => {
    renderReport()
    const order = [
      screen.getByText('核心判断'),          // 518 结论先行
      screen.getByTestId('wordcloud-dom'),  // 536 图表
      screen.getByText(/可达性矩阵/),         // 545 结构化块
      screen.getByText(/概览 · 数据空间/),    // 548 数据空间
      screen.getByText('第一段评注'),         // 551 正文（首段评注直出）
    ]
    for (let i = 0; i + 1 < order.length; i++) {
      expect(
        order[i].compareDocumentPosition(order[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
    }
  })

  it('C-F2：正文默认折叠但内容不卸载；index.css 打印留底规则在位（H15 手法）', () => {
    const { container } = renderReport()
    const d = detailsEl(container)
    expect(d).not.toBeNull()
    expect(d.hasAttribute('open')).toBe(false)
    expect(container.textContent).toContain('展开完整正文')
    expect(container.textContent).toContain('第二段正文') // 折叠是呈现态，不卸载 DOM
    expect(container.textContent).toContain('第三段正文')

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')
    const printBlock = css.slice(css.indexOf('@media print'))
    expect(printBlock).toMatch(/details\.report-body-collapse\s*>\s*summary/)
    expect(printBlock).toMatch(/display:\s*none/)
  })

  it('C-F3：编辑模式整体自动展开折叠正文', () => {
    const { container } = renderReport()
    expect(detailsEl(container).hasAttribute('open')).toBe(false)
    fireEvent.click(screen.getByText('编辑'))
    expect(detailsEl(container).hasAttribute('open')).toBe(true)
  })

  it('C-F4：本章高亮命中 → 折叠体自动 open（折叠不切断高亮路径）', () => {
    useAnnotationStore.setState({
      annotations: {
        r_c1: {
          edits: {},
          highlights: [
            { id: 'h1', sectionId: 'overview', text: '第二段正文', color: 'sun', comment: '', createdAt: 1 },
          ],
        },
      },
    })
    const { container } = renderReport()
    expect(detailsEl(container).hasAttribute('open')).toBe(true)
  })
})

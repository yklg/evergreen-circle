// @vitest-environment jsdom
/**
 * 生活圈报告正文块渲染契约（计划笔 1.2 / 1.3 / 1.6）。
 *
 * 守护四件事：
 *  B1 **老 payload 不白屏**：`highlights` 是后端新产出字段，改动前落库的报告没有它
 *     （`db.py:1529-1586` 写时无版本列、`:1559-1586` 读时只修 `severity`）⇒ 渲染层必须
 *     对 undefined 免疫。这条不是假想：报告表里存量行就是 2 段 / 无亮点 / 3 图。
 *  B2 **亮点卡真渲染**：`LifeCircleReportView` 历史上完全不读 `sec.highlights`
 *     （调研侧在 `ReportPage.tsx:569`），后端一旦产出亮点就会被静默丢掉。
 *  B3 **折叠必须用调研侧同名类**：`ReportPage.tsx:153-167` 的 beforeprint 按类名
 *     `details.report-body-collapse` 强制展开，且该 effect 与生活圈早退在同一组件实例注册
 *     ⇒ 同名即自动生效；换名 = 生活圈正文在导出 PDF 里整段消失（评审 P0-3）。
 *  B4 **data_grid 标题不写死「盲区明细」**：该 title 兼作 CSV 文件名（`VDataGrid.tsx:23`），
 *     而 data_grid 不再只属于盲区章。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import path from 'node:path'
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

// echarts 桩替身（jsdom 无 ResizeObserver；图件结构契约由 livingCircleContract 守）
vi.mock('../components/VChart', () => ({
  VChart: ({ spec }: { spec: { title?: string } }) => <div data-testid="mock-chart">{spec?.title ?? 'chart'}</div>,
}))

type Section = Record<string, unknown> & { id: string; paragraphs?: string[] }

/** 取演示态生活圈报告，可选按章改写 sections（深拷贝，避免污染 mock 单例）。 */
function lcReport(mutate?: (secs: Section[]) => Section[]) {
  const base = JSON.parse(JSON.stringify(getLivingCircleReportMock('lc-kaili'))) as {
    sections: Section[]
  } & Record<string, unknown>
  if (mutate) base.sections = mutate(base.sections)
  return base as unknown as Record<string, unknown>
}

function renderReport(report: Record<string, unknown>) {
  holder.report = report
  return render(
    <MemoryRouter initialEntries={['/report/lc-1']}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  navigateFn.mockClear()
})

afterEach(() => {
  cleanup()
})

describe('生活圈报告正文块 · 渲染契约', () => {
  it('B1 — 老 payload（无 highlights、每章 2 段）不白屏，且不折叠', () => {
    const report = lcReport((secs) =>
      secs.map((s) => {
        const { highlights, ...rest } = s
        void highlights
        return { ...rest, paragraphs: (s.paragraphs ?? []).slice(0, 2) }
      }),
    )
    const { container } = renderReport(report)
    expect(container.querySelector('section[id^="lc-sec-"]')).toBeTruthy()
    expect(container.querySelector('details.report-body-collapse')).toBeNull()
  })

  it('B2 — 有 highlights 的章产出亮点卡，条数与数据一致', () => {
    const hls = ['亮点甲', '亮点乙', '亮点丙']
    const report = lcReport((secs) =>
      secs.map((s, i) => (i === 0 ? { ...s, highlights: hls } : { ...s, highlights: [] })),
    )
    renderReport(report)
    for (const h of hls) expect(screen.getAllByText(h).length).toBeGreaterThan(0)
  })

  it('B3 — 段数 > 2 的章必须用调研侧同名类折叠（否则导出 PDF 丢正文）', () => {
    const paras = ['第一段', '第二段', '第三段', '第四段', '第五段']
    const report = lcReport((secs) => secs.map((s, i) => (i === 0 ? { ...s, paragraphs: paras } : s)))
    const { container } = renderReport(report)
    const d = container.querySelector('details.report-body-collapse')
    expect(d).toBeTruthy()
    expect(d!.getAttribute('data-section-body')).toBe('overview')
    expect(d!.querySelector('summary')?.textContent).toContain('共 5 段')
    // 出厂闭合：正文仍在 DOM 里，靠 beforeprint 展开（不卸载内容 = C1 同一契约）
    expect((d as HTMLDetailsElement).open).toBe(false)
  })

  it('B3 — 打印 CSS 仍保留该类的 summary 留底规则', () => {
    const css = readFileSync(path.resolve(__dirname, '../index.css'), 'utf8')
    const printBlock = css.slice(css.indexOf('@media print'))
    expect(printBlock).toMatch(/details\.report-body-collapse\s*>\s*summary/)
  })

  it('B4 — data_grid 标题不再写死「盲区明细」，改由章名派生', () => {
    // 演示 mock 的盲区是 0 处，而 VDataGrid 在 rows 为空时直接 return null
    // （VDataGrid.tsx:8）⇒ 必须注入有行的 data_grid 才测得到标题。
    const report = lcReport((secs) =>
      secs.map((s) =>
        s.id === 'blindspot'
          ? {
              ...s,
              data_grid: {
                columns: ['盲区编号', '缺失设施', '最近设施', '补点建议'],
                rows: [{ name: 'bs-1', value: '药店 812m', metric: '药店', source: 'fixture://bs', source_url: '' }],
              },
            }
          : s,
      ),
    )
    const { container } = renderReport(report)
    expect(container.textContent).not.toContain('盲区明细')
    expect(container.textContent).toContain('服务盲区诊断 · 明细表')
  })

  it('B5 — 带台账的样区（lc-kaili-ev2）能整页渲染，台账卡与折叠同时在场', () => {
    // 现有用例都只渲染 `lc-kaili`（无台账），ev2 那份在浏览器里抛过运行时错误却全绿，
    // 因为没有任何用例走过它。这条就是补那个洞。
    const report = getLivingCircleReportMock('lc-kaili-ev2')
    expect(report).toBeTruthy()
    const { container } = renderReport(report as unknown as Record<string, unknown>)
    expect(container.querySelector('section[id^="lc-sec-"]')).toBeTruthy()
    expect(container.textContent).toContain('逐格台账')
    expect(container.querySelectorAll('rect[data-cell]').length).toBeGreaterThan(0)
    expect(container.querySelector('details.report-body-collapse')).toBeTruthy()
    expect(container.textContent).toContain('判定格阵')
  })

  it('B6 — 演示态必须自己产出亮点句（生产出、演示态不出 = 假绿，台账 R6）', () => {
    const report = getLivingCircleReportMock('lc-kaili-ev2') as unknown as {
      sections: { id: string; highlights?: string[] }[]
    }
    const withHl = report.sections.filter((s) => (s.highlights ?? []).length > 0)
    expect(withHl.length).toBeGreaterThan(0)
    const total = report.sections.reduce((n, s) => n + (s.highlights ?? []).length, 0)
    expect(total).toBeLessThanOrEqual(report.sections.length * 3) // 每章 ≤3 条（与后端同一上限）
  })

  it('B7 — 明细表分享态脱敏：经纬度对与 gap 值被剥掉，方位与距离保留', async () => {
    // 真浏览器差分测出来的泄漏：地图脱敏了、盲区明细表没脱（source 列带精确经纬度与 gap）。
    // `?share=1` 是公开无鉴权链接 ⇒ 表不脱等于没脱。
    // 纯函数放 lib（组件文件多导出一个函数会破 fast-refresh，被 lint 棘轮拦住过）
    const { maskGridForShare } = await import('../lib/livingCircle')
    const grid = {
      columns: ['a', 'b', 'c', 'd'],
      rows: [
        {
          name: 'bs-凯里老街-1 · 轻度',
          value: '最近 汇农生鲜 247m · 小学·移动点/改道补充·P1',
          metric: '小学',
          source: '[107.9758, 26.5734] · 东南 · gap 0.262',
          source_url: '',
        },
      ],
    }
    const masked = maskGridForShare(grid as never) as unknown as {
      rows: { source: string; value: string; name: string }[]
    }
    const s = masked.rows[0].source
    expect(s).not.toContain('107.9758')
    expect(s).not.toContain('26.5734')
    expect(s).not.toContain('0.262')
    expect(s).toContain('概略片区')
    expect(s).toContain('东南') // 方位是粗粒度，与既有 ③-A 立场一致 ⇒ 保留
    expect(masked.rows[0].value).toContain('247m') // 距离不是坐标，不动
    expect(masked.rows[0].name).toContain('轻度')
    // 原对象不得被就地改写（React 侧共享引用）
    expect(grid.rows[0].source).toContain('107.9758')
  })
})

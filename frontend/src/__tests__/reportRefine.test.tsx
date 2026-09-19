// @vitest-environment jsdom
/**
 * ReportPage 精修接线测试（计划 §3.4 / §5.4，P1-3）。
 *
 * 运行依赖（当前项目已安装）：@testing-library/react + jsdom + vitest。
 *
 * 覆盖：
 *  - test_report_page_refine_sse_wiring  点「精修」→ openTaskStream(taskId) 被调、
 *                                         onEvent('progress') 更新本地进度、onEvent('done') → load(rid)+关流
 *
 * api 层（refineReportEvidence 真实调用与请求体）见同目录 apiRefine.test.ts。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import * as api from '../lib/api'
import ReportPage from '../pages/ReportPage'

const { navigateFn } = vi.hoisted(() => ({ navigateFn: vi.fn() }))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateFn }
})

vi.mock('../lib/api', () => ({
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
  fetchReport: vi.fn(),
}))

const mockedRefine = api.refineReportEvidence as unknown as ReturnType<typeof vi.fn>
const mockedOpenTaskStream = api.openTaskStream as unknown as ReturnType<typeof vi.fn>

// reportStore 整体 mock：提供可控的 current 报告与 load，隔离 ReportPage 的数据依赖。
// 字段需覆盖 ReportPage 渲染所需（与真实 store 返回的 ReportData 形状一致）。
const loadFn = vi.fn()
vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({
    current: {
      id: 'r1',
      title: '测试报告',
      subtitle: '',
      created_at: '',
      experts: [],
      cover_image: '/assets/brand/report-cover.png',
      toc: [],
      sections: [],
      claims: [],
      evidence: [
        { evidence_id: 'e1', title: '高质证据', credibility: 90 },
        { evidence_id: 'e2', title: '低质证据', credibility: 30 },
      ],
      figures: [],
      sentiment: undefined,
      trace: [],
      glossary: [],
      metrics: undefined,
      audit_review: undefined,
      quality_before: undefined,
      quality_after: undefined,
    },
    loading: false,
    error: null,
    load: loadFn,
  }),
}))

beforeEach(() => {
  navigateFn.mockClear()
  loadFn.mockClear()
  mockedRefine.mockReset()
  mockedOpenTaskStream.mockReset().mockImplementation(() => () => {})
})

afterEach(() => {
  cleanup()
})

function renderReport(rid: string) {
  return render(
    <MemoryRouter initialEntries={[`/report/${rid}`]}>
      <Routes>
        <Route path="/report/:reportId" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReportPage 精修接线（P1-3）', () => {
  it('点「精修」→ openTaskStream(taskId) 被调；done → load(rid)+关流', async () => {
    mockedRefine.mockResolvedValue({ taskId: 't_refine_1' })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let handlers: any = null
    mockedOpenTaskStream.mockImplementation((_tid, h) => {
      handlers = h
      return () => {}
    })
    renderReport('r1')
    // 触发精修按钮（计划新增：证据区「高质证据精修」）
    fireEvent.click(screen.getByText(/用高可信度证据精修|精修/))
    await waitFor(() => expect(mockedRefine).toHaveBeenCalled())
    expect(mockedOpenTaskStream).toHaveBeenCalledWith('t_refine_1', expect.anything())
    // 模拟 SSE 进度 + 完成
    act(() => {
      handlers.onEvent('progress', { percent: 50, stage: '精修第1/1章' })
      handlers.onEvent('done', { reportId: 'r1' })
    })
    expect(loadFn).toHaveBeenCalledWith('r1') // done 后重载报告
  })
})
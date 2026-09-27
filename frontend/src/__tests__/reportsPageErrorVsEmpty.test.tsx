// @vitest-environment jsdom
/**
 * D4 · 取数失败 ≠ 没有报告（报告中心真实态）
 *
 * 现状（架构评审 v4 事实 7）：`ReportsPage.tsx:32-33` 两条 `.catch(() => {})` 把失败
 * 吞掉，而 `api.ts:195/288` 又对 `/api/life-circle`、`/api/reports` 做了 `safeJson(...,[])`
 * 空数组兜底 ⇒ **后端 500 / 网络断 与 真的一份报告都没有，在 UI 上完全同形**，
 * 都渲染「暂无该类报告」。用户会以为"我还没做过体检"，而不是"取数出了问题"。
 *
 * 判据配对（本项目既有做法：一条 xfail 指向目标行为 + 一条**记录当前行为**，修复时
 * 后者必须重指而非删除，见 `backend/tests/test_task_body_contract.py:10`）：
 * - `it.fails`：失败必须可分辨（有失败披露或重试入口）；
 * - 两条正向：失败态与真空态今天渲染**一模一样** —— 这个"一样"本身就是缺陷的证据。
 *
 * `wip/domainpack` 已把这两处兜底去掉并区分「加载失败·重试 / 暂无报告」三态，
 * 路线乙在本分支落地时，摘掉 `it.fails` 标记即转绿。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentType } from 'react'

const mocks = vi.hoisted(() => ({
  fetchReports: vi.fn(),
  fetchLifeCircleReports: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  fetchReports: mocks.fetchReports,
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
}))

afterEach(cleanup)

beforeEach(() => {
  mocks.fetchReports.mockReset()
  mocks.fetchLifeCircleReports.mockReset()
})

/** 真实态渲染报告中心：注入 store 为 live（否则走内置快照，测不到取数分支）。 */
async function renderLive() {
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={['/reports']}>
      <P />
    </MemoryRouter>,
  )
}

const EMPTY_COPY = '暂无该类报告'
const FAILURE_HINT = /加载失败|读取失败|网络|重试/

describe('报告中心：真实态取数', () => {
  it('失败时今天渲染成「暂无该类报告」——记录当前行为，不是期望它', async () => {
    mocks.fetchReports.mockRejectedValue(new Error('network down'))
    mocks.fetchLifeCircleReports.mockRejectedValue(new Error('network down'))
    await renderLive()

    await waitFor(() => expect(mocks.fetchLifeCircleReports).toHaveBeenCalled())
    expect(screen.getByText(EMPTY_COPY)).toBeTruthy()
    // 缺陷本身：没有任何失败线索、没有重试入口
    expect(screen.queryByText(FAILURE_HINT)).toBeNull()
  })

  it('真空列表时渲染同一句文案（与上一条刻意同形）', async () => {
    mocks.fetchReports.mockResolvedValue([])
    mocks.fetchLifeCircleReports.mockResolvedValue([])
    await renderLive()

    await waitFor(() => expect(mocks.fetchLifeCircleReports).toHaveBeenCalled())
    expect(screen.getByText(EMPTY_COPY)).toBeTruthy()
  })

  it.fails('失败时必须披露失败并提供重试，而不是伪装成空列表', async () => {
    mocks.fetchReports.mockRejectedValue(new Error('network down'))
    mocks.fetchLifeCircleReports.mockRejectedValue(new Error('network down'))
    await renderLive()

    await waitFor(() => expect(mocks.fetchLifeCircleReports).toHaveBeenCalled())
    expect(screen.getByText(FAILURE_HINT)).toBeTruthy()
    expect(screen.queryByText(EMPTY_COPY)).toBeNull()
  })
})

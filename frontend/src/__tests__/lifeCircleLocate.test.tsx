// @vitest-environment jsdom
/**
 * 阶段 2 · P0「名称与坐标同源」的**回归防线**（LiveCirclePage live 态）
 * + v5 A「定位确认弹窗」的确认/取消决策（U21 种子改写锚点）。
 *
 * ## 被守护的事故
 *
 * 旧实现 `onLocate`：
 * ```ts
 * setCtaText(hit.name || '当前位置')      // ① setState 排队，同 tick 内不生效
 * void startRealCheck(hit.lnglat)         // ② 立即执行，闭包里 ctaText 仍是旧值
 * ```
 * ⇒ 请求里 `scene_name` 取**旧输入框文字**、`center` 取**新定位坐标**、
 *   `city` 取**当前展示的报告** —— 三字段三个来源。
 * 实测产出报告 `lc-d3cfa371`：名称「北京劲松」+ 中心「昆明」+ 城市「北京·朝阳」。
 *
 * v5 A：真实模式「定位到我」不再直接发起体检 —— 先弹确认框
 * （定位名称/坐标/坐标系/额度提示），**确认才发起、取消不发起**（U21）。
 *
 * ## 本文件的判据
 *
 * 1. 输入框里故意留一个**与定位结果不同**的旧值（北京劲松）；
 *    定位返回昆明坐标 + 昆明地名 → 确认后请求的 `query` 必须是**定位结果**，不是旧值。
 * 2. 请求**不得携带 city**（城市改由后端按中心点逆地理；前端传 city 必是错的那个）。
 * 3. 坐标系标签必须随坐标同行（降级定位是 WGS-84，需由服务端转换）。
 * 4. 确认框展示定位名称/坐标/坐标系；「取消」不调用创建任务、不消耗额度。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import type { ForwardedRef } from 'react'

/**
 * 桩函数的签名必须**显式写出**，不能靠 `vi.fn(async () => null)` 让 TS 推断。
 * 原因：`vi.mock` 只换运行时实现，**类型仍来自真实模块**（`lib/api`）。若桩写成
 * 「返回 null 的无参函数」，`mockResolvedValue(报告对象)` 就会因「null 类型不能接收
 * Report」而报 TS2322 —— 而 `npm run typecheck` 用的是 `-p tsconfig.app.json`，
 * 它**真的会检查测试文件**（`tsc --noEmit` 走 solution 风格 tsconfig 时不检查任何文件，
 * 是假通过）。两者差别见 restart.sh 内注释。
 */
const { api, nav } = vi.hoisted(() => {
  const createLivingCircleTask = vi.fn(
    async (_input: Record<string, unknown>): Promise<{ taskId: string }> => ({ taskId: 'lc-fake-task' }),
  )
  const fetchLifeCircleReports = vi.fn(async (): Promise<{ id: string }[]> => [])
  const fetchLifeCircleReport = vi.fn(async (_reportId?: string): Promise<unknown> => null)
  const openTaskStream = vi.fn(() => () => {})
  return {
    api: { createLivingCircleTask, fetchLifeCircleReports, fetchLifeCircleReport, openTaskStream },
    nav: { to: '' },
  }
})

vi.mock('../lib/api', () => ({
  createLivingCircleTask: api.createLivingCircleTask,
  fetchLifeCircleReports: api.fetchLifeCircleReports,
  fetchLifeCircleReport: api.fetchLifeCircleReport,
  openTaskStream: api.openTaskStream,
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => (to: string) => {
      nav.to = to
    },
  }
})

/** 地图桩：只暴露 locate()，避免 jsdom 里加载真实 BMapGL/网络 */
const STALE_INPUT = '北京劲松'
const LOCATED_NAME = '云南省昆明市五华区莲华街道'
const LOCATED_COORD: [number, number] = [102.7596, 25.0295]

vi.mock('../components/lifecircle/LcMap', async () => {
  const React = await import('react')
  return {
    default: React.forwardRef(function FakeLcMap(_props: unknown, ref: ForwardedRef<unknown>) {
      React.useImperativeHandle(ref, () => ({
        locate: async () => ({ lnglat: LOCATED_COORD, name: LOCATED_NAME, coordSys: 'wgs84' }),
      }))
      return React.createElement('div', { 'data-testid': 'fake-lc-map' })
    }),
  }
})

const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')
const { useDataModeStore } = await import('../store/dataModeStore')
const { getLivingCircleReportMock } = await import('../mocks/livingCircleReports')

beforeEach(() => {
  useDataModeStore.setState({ mode: 'live' }) // 真实态：定位走确认框 → 确认才 startRealCheck
  // 让 live 分支拿到一份报告（页面才有地图与「定位到我」按钮）
  api.fetchLifeCircleReports.mockResolvedValue([{ id: 'lc-kaili' }])
  api.fetchLifeCircleReport.mockResolvedValue(getLivingCircleReportMock('lc-kaili'))
  api.createLivingCircleTask.mockClear()
  nav.to = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

async function renderAndStaleType() {
  render(
    <MemoryRouter initialEntries={['/life-circle/kaili']}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )
  // 先等真实报告加载完成（否则拿到的是「还没有体检记录」空态的另一个输入框）
  await screen.findByRole('button', { name: /定位到我/ })
  const input = screen.getByPlaceholderText(/输入社区名 \/ 或 经度/) as HTMLInputElement
  // 输入框留一个与定位结果无关的旧值 —— 旧实现会把它当成本次任务的名称
  fireEvent.change(input, { target: { value: STALE_INPUT } })
  await waitFor(() => expect(input.value).toBe(STALE_INPUT), { timeout: 1000 })
  return input
}

/** v5 A：点「定位到我」→ 等确认框出现 → 返回确认框元素 */
async function locateToConfirm() {
  fireEvent.click(screen.getByRole('button', { name: /定位到我/ }))
  const dialog = await screen.findByRole('dialog', { name: '确认发起体检' })
  return dialog
}

describe('LifeCirclePage（live 态）· 定位发起体检的名称/坐标同源（经确认框）', () => {
  it('v5 A：定位后先弹确认框（名称/坐标/WGS-84 提示），确认才发起', async () => {
    await renderAndStaleType()
    await locateToConfirm()

    // 确认框内容：定位名称 / 坐标 / 坐标系（wgs84 → 服务端转 BD-09）
    expect(screen.getByText(LOCATED_NAME)).toBeTruthy()
    expect(screen.getByText(/102\.75960, 25\.02950/)).toBeTruthy()
    expect(screen.getByText(/WGS-84（提交时服务端转 BD-09）/)).toBeTruthy()
    // 额度提示：新中心点消耗配额；同地点/邻近（≤500m）30 天内有结果走缓存
    expect(screen.getByText(/将消耗本次体检所需百度配额/)).toBeTruthy()
    expect(screen.getByText(/邻近（≤500m）/)).toBeTruthy()

    // 尚未确认：不得发起任务（U21：确认框不发起）
    expect(api.createLivingCircleTask).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /确认体检/ }))
    await waitFor(() => expect(api.createLivingCircleTask).toHaveBeenCalledTimes(1))
    const arg = api.createLivingCircleTask.mock.calls[0][0] as Record<string, unknown>

    expect(arg.query).toBe(LOCATED_NAME)
    expect(arg.query).not.toBe(STALE_INPUT)
    expect(arg.center).toEqual(LOCATED_COORD)
    // 坐标系必须与坐标同行：降级定位是 WGS-84，服务端要据此转换，否则中心偏约 600m
    expect(arg.coord_sys).toBe('wgs84')
    // 生活圈任务不再进工作台：回落本页 SSE，页面原地显示「体检进行中」状态横幅
    await waitFor(() => expect(screen.getByRole('status')).toBeTruthy())
    expect(nav.to).toBe('')
  })

  it('请求不得携带 city（城市由后端按中心点逆地理，前端传的必是无关值）', async () => {
    await renderAndStaleType()
    await locateToConfirm()
    fireEvent.click(screen.getByRole('button', { name: /确认体检/ }))

    await waitFor(() => expect(api.createLivingCircleTask).toHaveBeenCalledTimes(1))
    const arg = api.createLivingCircleTask.mock.calls[0][0] as Record<string, unknown>

    expect(arg).not.toHaveProperty('city')
  })

  it('U21：取消不发起体检、不创建任务、不耗额度', async () => {
    await renderAndStaleType()
    await locateToConfirm()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))

    // 取消后确认框关闭，且从未创建任务
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '确认发起体检' })).toBeNull())
    expect(api.createLivingCircleTask).not.toHaveBeenCalled()
    expect(nav.to).toBe('')
  })
})

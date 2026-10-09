// @vitest-environment jsdom
/**
 * 横幅上的「当前席位」行（计划 F2）。
 *
 * 这块横幅有**两个挂载点**（`LifeCirclePage.tsx` 的有记录态与无记录空态各一处），两处共用
 * `RunNotices` 一份实现 —— 这正是"扩 RunNotices 而不是新立组件"的理由：只接一处就会漏一处，
 * 而漏的那一处不会报错，只会让某个状态下屏上少一行。所以两个挂载点各自断言一次，
 * 并且用它们**本来就不同**的头部文案来证明锚到的是哪一处（`体检进行中 ·` vs `生活圈体检进行中 ·`）。
 *
 * 三态渲染是这条判据的另一半：名册未到 ⇒ 整行不出现（缺席即不印）；名册已到但查不到该 id ⇒
 * **印裸 id**（注册表指到不存在的席位是缺陷，不许遮）；查到 ⇒ `名 · 职位中文段`。
 *
 * 两条与"异步"绑在一起的纪律：
 *  - 名册一律经 `api.fetchExperts` 这一条真链路进来（不是在用例里 setState 完事）——
 *    组件里那个 `load('living_circle')` 会**覆盖**手工塞进去的槽位，上一版就是这么自相矛盾的；
 *  - 订阅的是**名册数组**而不是 `resolve` 函数：后者引用恒定，名册到位不会重渲染
 *    （同一个教训由 `lcSignatureDomain.test.tsx` 抓到过）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ForwardedRef } from 'react'

type StreamHandlers = { onEvent: (t: string, d: unknown) => void }

/** 形参走 rest 元组再解构 —— 本仓 eslint 不给 `_前缀` 免死
 *  （`lifeCircleBannerRegistry.test.tsx` 那 6 条账上有名的 error 就是这么来的），
 *  新文件预算 0，不能照抄它的写法。 */
const { api, hands } = vi.hoisted(() => ({
  api: {
    createLivingCircleTask: vi.fn(async () => ({ taskId: 'lc-r1' })),
    fetchLifeCircleReports: vi.fn(async (): Promise<unknown> => []),
    fetchLifeCircleReport: vi.fn(async (): Promise<unknown> => null),
    openTaskStream: vi.fn(),
    fetchExperts: vi.fn(async (domain: string): Promise<unknown[]> =>
      domain === 'living_circle'
        ? [
            { id: 'L1-030', name: '甄实核', nickname: 'V', level: 'L1', group: 'method', role_title: 'POI 核验官 / POI Verifier' },
            { id: 'L2-005', name: '路遥川', nickname: 'M', level: 'L2', group: 'strategy', role_title: '慢行可达性分析师 / Mobility Advisor' },
          ]
        : []),
  },
  hands: { fire: (() => {}) as (t: string, d: unknown) => void },
}))

vi.mock('../lib/api', () => api)

vi.mock('../components/lifecircle/LcMap', async () => {
  const React = await import('react')
  return {
    default: React.forwardRef(function FakeLcMap(_props: unknown, ref: ForwardedRef<unknown>) {
      React.useImperativeHandle(ref, () => ({ locate: async () => null }))
      return React.createElement('div', { 'data-testid': 'fake-lc-map' })
    }),
  }
})

const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')
const { useDataModeStore } = await import('../store/dataModeStore')
const { useExpertStore } = await import('../store/expertStore')
const { useTaskRegistry } = await import('../store/taskRegistry')
const { getLivingCircleReportMock } = await import('../mocks/livingCircleReports')

async function startRun() {
  render(
    <MemoryRouter initialEntries={['/life-circle/kaili']}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByRole('button', { name: /开始体检/ })
  fireEvent.click(screen.getAllByRole('button', { name: /开始体检/ })[0])
  await waitFor(() => expect(screen.getByRole('status')).toBeTruthy())
}

/** 让页面停在有记录态（横幅住在报告分支里）。 */
const withRecord = () => api.fetchLifeCircleReports.mockImplementation(async () => [{ id: 'lc-kaili' }])

/** 名册的默认返回（用例可逐个覆盖）。抽出来是因为 `afterEach` 的 `restoreAllMocks`
 *  会把 `vi.fn(impl)` 打回空函数 —— 只靠构造时给的实现，第二条用例就会拿不到名册。 */
const LIVING_ROSTER = () => [
  { id: 'L1-030', name: '甄实核', nickname: 'V', level: 'L1', group: 'method', role_title: 'POI 核验官 / POI Verifier' },
  { id: 'L2-005', name: '路遥川', nickname: 'M', level: 'L2', group: 'strategy', role_title: '慢行可达性分析师 / Mobility Advisor' },
]

beforeEach(() => {
  useDataModeStore.setState({ mode: 'live' })
  useTaskRegistry.setState({ tasks: {} })
  useExpertStore.setState({ expertsByDomain: {}, loadedDomains: {}, loadingDomains: {} })
  api.createLivingCircleTask.mockImplementation(async () => ({ taskId: 'lc-r1' }))
  api.fetchExperts.mockImplementation(async (domain: string) =>
    (domain === 'living_circle' ? LIVING_ROSTER() : []) as never)
  api.fetchLifeCircleReport.mockImplementation(async () => getLivingCircleReportMock('lc-kaili'))
  api.createLivingCircleTask.mockClear()
  api.fetchExperts.mockClear()
  api.openTaskStream.mockImplementation((...args: [string, StreamHandlers]) => {
    const [, handlers] = args
    hands.fire = (t: string, d: unknown) => handlers.onEvent(t, d)
    return () => {}
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('F2 · 两个挂载点都有席位行（数据源＝progress.expert）', () => {
  it('有记录态横幅：progress 带 expert ⇒ 行出现，印「名 · 职位」＋席位 id 注脚', async () => {
    withRecord()
    await startRun()
    hands.fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    const row = (await screen.findByText('甄实核 · POI 核验官')).closest('div')
    expect(row?.textContent).toContain('当前席位')
    expect(row?.textContent).toContain('L1-030')
    // 挂载点身份：这一支横幅的头部带"生活圈"三个字（另一支不带，见下一条）
    expect(screen.getByText('生活圈体检进行中 · POI 采集')).toBeTruthy()
  })

  it('无记录空态横幅：同一份 RunNotices ⇒ 行也出现（漏接这一处就会在这里红）', async () => {
    api.fetchLifeCircleReports.mockImplementation(async () => [])
    await startRun()
    hands.fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    const row = (await screen.findByText('甄实核 · POI 核验官')).closest('div')
    expect(row?.textContent).toContain('当前席位')
    // 这一支横幅的头部文案没有"生活圈"三个字 ⇒ 证明确实是空态那个挂载点渲的
    expect(screen.getByText('体检进行中 · POI 采集')).toBeTruthy()
  })
})

describe('F2 · 演示态取值（数据源＝message.expert）', () => {
  it('夹具把归属挂在 message 上 ⇒ 行同样出现（只挂 progress 会得到"真跑有、演示空"）', async () => {
    withRecord()
    await startRun()
    hands.fire('progress', { stage: 'measure', percent: 30 })
    expect(screen.queryByText(/当前席位/), 'progress 没带归属就不该印行').toBeNull()
    hands.fire('message', { stage: 'measure', text: '粗扫 400m 网格', expert: 'L2-005' })
    await screen.findByText('路遥川 · 慢行可达性分析师')
  })
})

describe('F2 · 三态渲染', () => {
  it('横幅一挂载就去取名册（体检台原先没人 load，光订阅数组会永远拿到空册）', async () => {
    // 这一条是真浏览器 e2e 抓出来的：`RunNotices` 只订阅了名册数组，而整页没有任何地方触发
    // `load('living_circle')` ⇒ "名册未到 ⇒ 不印行"这条**正确**的语义在体检台上等于"永远不印"。
    withRecord()
    await startRun()
    hands.fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    await screen.findByText('甄实核 · POI 核验官')
    expect(api.fetchExperts.mock.calls.some((c: unknown[]) => c[0] === 'living_circle'), '没按 living_circle 域取册').toBe(true)
  })

  it('名册未到 ⇒ 整行不出现（缺席即不印，不闪一个裸 id 再换）', async () => {
    withRecord()
    // 把取数**挂住**：否则上面那条 load 会在断言之前就把册子填上，这一态根本测不到。
    api.fetchExperts.mockImplementationOnce(() => new Promise(() => {}))
    await startRun()
    hands.fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    await waitFor(() => expect(useTaskRegistry.getState().tasks['lc-r1'].expert).toBe('L1-030'))
    expect(screen.queryByText(/当前席位/)).toBeNull()

    // 名册到位 ⇒ 同一帧不必重发，行就该出现（订阅数组而不是函数的意义所在）
    useExpertStore.setState({
      expertsByDomain: {
        living_circle: [{ id: 'L1-030', name: '甄实核', role_title: 'POI 核验官 / POI Verifier' }] as never,
      },
    })
    await screen.findByText('甄实核 · POI 核验官')
  })

  it('名册已到但查不到该席位 ⇒ 印裸 id（注册表指到不存在的席位必须可见）', async () => {
    withRecord()
    await startRun()
    hands.fire('progress', { stage: 'diagnose', percent: 82, expert: 'L9-999' })
    const line = await screen.findByText(/当前席位/)
    expect(line.textContent).toContain('L9-999')
    expect(line.textContent).not.toContain('甄实核')
  })
})

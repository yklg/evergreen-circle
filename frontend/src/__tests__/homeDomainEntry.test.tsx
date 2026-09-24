// @vitest-environment jsdom
/**
 * 首页三能力入口契约（C1–C6；替代旧 homeLifeCircle 分步弹窗流）。
 *
 * 守护：
 * - R1 三域卡（攻略/评估来自注册表适配层，生活圈固定虚线卡）+ 示例/专家墙随域联动
 * - R2 真实态建任务 body 语义为权威 type（assess 静默变 guide 的回归钉在此）
 * - R3 落地：travel+live→/clarify、travel+fixture→/workspace、living_circle→/life-circle
 * - R5 专家墙按域；R7 失败停首页不跳转；边界：空输入禁用提交、示例卡只填字不发任务
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

afterEach(cleanup)

function PathProbe() {
  const loc = useLocation()
  return (
    <div data-testid="path" data-path={loc.pathname}>
      {JSON.stringify(loc.state ?? {})}
    </div>
  )
}

// ── 全局 mock：api（createTask/fetchExperts）+ 类型卡适配层 ─────────────
const mocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  fetchExperts: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  createTask: mocks.createTask,
  fetchExperts: mocks.fetchExperts,
}))

vi.mock('../lib/researchTypesClient', () => ({
  fetchResearchTypes: vi.fn(async () => [
    { key: 'guide', label: '游玩攻略', subtitle: '交通 · 住宿 · 路线 · 美食 · 预算' },
    { key: 'assessment', label: '调研评估', subtitle: '可达性 · 配套 · 安全 · 性价比' },
  ]),
}))

const TRAVEL_EXPERTS = Array.from({ length: 12 }, (_, i) => ({
  id: `T${i + 1}`,
  name: `旅游专家${i + 1}`,
  nickname: `T${i + 1}`,
  level: i < 1 ? 'L3' : 'L1',
}))
const LIVING_EXPERTS = Array.from({ length: 12 }, (_, i) => ({
  id: `L${i + 1}`,
  name: `生活圈专家${i + 1}`,
  nickname: `L${i + 1}`,
  level: i < 1 ? 'L3' : 'L1',
}))

async function renderHome(mode: 'live' | 'fixture') {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode })
  const { useExpertStore } = await import('../store/expertStore')
  useExpertStore.setState({
    expertsByDomain: {},
    loadedDomains: {},
    loadingDomains: {},
    experts: [],
    loaded: false,
    loading: false,
  })
  mocks.fetchExperts.mockImplementation(async (domain: string) =>
    domain === 'living_circle' ? LIVING_EXPERTS : TRAVEL_EXPERTS,
  )
  const { default: HomePage } = await import('../pages/HomePage')
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/clarify/:taskId" element={<PathProbe />} />
        <Route path="/workspace/:taskId" element={<PathProbe />} />
        <Route path="/workspace" element={<PathProbe />} />
        <Route path="/life-circle/:sceneId" element={<PathProbe />} />
        <Route path="/experts" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function lastPath() {
  const els = screen.queryAllByTestId('path')
  return els.length ? els[els.length - 1] : null
}

/** 等类型卡（fetchResearchTypes 微任务）渲染就绪，再做点击断言。 */
function ready() {
  return waitFor(() => expect(screen.getByText('游玩攻略')).toBeTruthy())
}

const submitBtn = () => screen.getByRole('button', { name: /开始调研|前往生活圈地图/ })
const typeQuery = (text: string) =>
  fireEvent.change(screen.getByRole('textbox'), { target: { value: text } })

beforeEach(() => {
  mocks.createTask.mockReset()
  mocks.fetchExperts.mockReset()
})

describe('FE-20 · 三域卡首屏', () => {
  it('攻略/评估/生活圈三卡渲染，攻略默认选中（aria-pressed）', async () => {
    await renderHome('live')
    await ready()
    await waitFor(() => expect(screen.getByText('游玩攻略')).toBeTruthy())
    expect(screen.getByText('调研评估')).toBeTruthy()
    expect(screen.getByText('15 分钟生活圈体检')).toBeTruthy()
    const cards = screen.getAllByRole('button', { pressed: true })
    expect(cards.some((b) => b.textContent?.includes('游玩攻略'))).toBe(true)
  })
})

describe('FE-21 · 域切换联动', () => {
  it('切评估 → 评估示例集；切生活圈 → 两张样例直达卡 + 中心点提示', async () => {
    await renderHome('live')
    await ready()
    fireEvent.click(screen.getByText('调研评估'))
    expect(screen.getByText('双城宜居对比')).toBeTruthy()
    expect(screen.queryByText('亲子路线规划')).toBeNull()

    fireEvent.click(screen.getByText('15 分钟生活圈体检'))
    expect(screen.getByText('凯里老街')).toBeTruthy()
    expect(screen.getByText('北京劲松')).toBeTruthy()
    expect(screen.getByPlaceholderText(/输入中心点/)).toBeTruthy()
  })
})

describe('FE-22/23/24 · 旅游域提交落地方向', () => {
  it('FE-22 真实态攻略：原话透传 → createTask type=guide → /clarify/:id', async () => {
    await renderHome('live')
    await ready()
    mocks.createTask.mockResolvedValue({ taskId: 't_guide', kind: 'travel_guide', purpose: 'guide' })
    typeQuery('大理 5 天亲子游')
    fireEvent.click(submitBtn())
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalledTimes(1))
    expect(mocks.createTask).toHaveBeenCalledWith('大理 5 天亲子游', 'deep', undefined, 'guide')
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/clarify/t_guide'))
    expect(lastPath()?.textContent).toContain('大理 5 天亲子游')
    // 旧弹窗向导必须彻底消失
    expect(screen.queryByText(/分步问答/)).toBeNull()
  })

  it('FE-23 演示态攻略：零网络意图 → /workspace/demo-*', async () => {
    await renderHome('fixture')
    await ready()
    mocks.createTask.mockResolvedValue({ taskId: 'demo-1', kind: 'travel_guide', purpose: 'guide' })
    typeQuery('大理 3 天')
    fireEvent.click(submitBtn())
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/workspace/demo-1'))
  })

  it('FE-24 真实态评估：createTask 第 4 参为 assessment（回归静默变 guide 的 bug）', async () => {
    await renderHome('live')
    await ready()
    mocks.createTask.mockResolvedValue({ taskId: 't_ass', kind: 'travel_assess', purpose: 'assess' })
    fireEvent.click(screen.getByText('调研评估'))
    typeQuery('评估成都和杭州哪个更宜居')
    fireEvent.click(submitBtn())
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalledTimes(1))
    expect(mocks.createTask.mock.calls[0][3]).toBe('assessment')
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/clarify/t_ass'))
  })
})

describe('FE-25/26 · 生活圈域直达地图', () => {
  it('FE-25 样例卡直达对应 scene，且零 createTask', async () => {
    await renderHome('live')
    await ready()
    fireEvent.click(screen.getByText('15 分钟生活圈体检'))
    fireEvent.click(screen.getByText('凯里老街'))
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/life-circle/kaili'))
    expect(mocks.createTask).not.toHaveBeenCalled()
  })

  it('FE-26 输入文字提交 → /life-circle/custom 且 state.query 带字（不丢字）', async () => {
    await renderHome('live')
    await ready()
    fireEvent.click(screen.getByText('15 分钟生活圈体检'))
    typeQuery('贵阳市观山湖区')
    fireEvent.click(submitBtn())
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/life-circle/custom'))
    expect(lastPath()?.textContent).toContain('贵阳市观山湖区')
    expect(mocks.createTask).not.toHaveBeenCalled()
  })
})

describe('FE-27/28 · 边界与示例卡交互', () => {
  it('FE-27 旅游域空输入：提交钮禁用', async () => {
    await renderHome('live')
    await ready()
    expect((submitBtn() as HTMLButtonElement).disabled).toBe(true)
    typeQuery('x')
    expect((submitBtn() as HTMLButtonElement).disabled).toBe(false)
  })

  it('FE-28 点攻略示例卡：文字进输入框但不发任务（可改后提交）', async () => {
    await renderHome('live')
    await ready()
    fireEvent.click(screen.getByText('亲子路线规划'))
    const ta = screen.getByPlaceholderText(/想去哪里/) as HTMLTextAreaElement
    expect(ta.value).toContain('大理')
    expect(mocks.createTask).not.toHaveBeenCalled()
  })
})

describe('FE-29 · 专家墙按域', () => {
  it('切到生活圈 → 加载生活圈名册（头像按 title 区分人设）；「查看 48 位」跳 /experts', async () => {
    await renderHome('live')
    await ready()
    await waitFor(() => expect(screen.getByTitle('旅游专家1 · T1')).toBeTruthy())
    expect(screen.queryByTitle('生活圈专家1 · L1')).toBeNull()

    fireEvent.click(screen.getByText('15 分钟生活圈体检'))
    await waitFor(() => expect(screen.getByTitle('生活圈专家1 · L1')).toBeTruthy())
    fireEvent.click(screen.getByText(/查看 48 位/))
    await waitFor(() => expect(lastPath()?.getAttribute('data-path')).toBe('/experts'))
  })
})

describe('FE-31 · 建任务失败停首页', () => {
  it('reject → 错误提示可见且不跳转', async () => {
    await renderHome('live')
    await ready()
    mocks.createTask.mockRejectedValue(new Error('网络错误'))
    typeQuery('大理')
    fireEvent.click(submitBtn())
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(lastPath()).toBeNull()
  })
})

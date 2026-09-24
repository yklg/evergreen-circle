// @vitest-environment jsdom
/**
 * 方案 A（Clarify 异步化）前端回归测试：守护 3 个 P0 不退化。
 *
 * 运行依赖（当前项目未安装，需 `npm i -D @testing-library/react @testing-library/jest-dom jsdom`）：
 *   - T-HP1  HomePage 三能力入口：真实态旅游提交先进 clarify（分步弹窗向导已退役）
 *   - T-CP3  空问卷 → 跳 workspace
 *   - T-CP5  loading 不误跳（修 P0#3：原 questions.length===0 硬跳）
 *   - T-CP1  loading → render（SSE 驱动）
 *   - T-CP4  error → 重试提示（P1#5 降级）
 *
 * api 层（createTask / openClarifyStream / submitClarify）统一 mock，避免真实网络与 EventSource。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import HomePage from '../pages/HomePage'
import ClarifyPage from '../pages/ClarifyPage'
import * as api from '../lib/api'

// 在路由层注入可控的 navigate，便于断言跳转目标
const { navigateFn } = vi.hoisted(() => ({ navigateFn: vi.fn() }))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateFn }
})

vi.mock('../lib/api', () => ({
  createLivingCircleTask: vi.fn(),
  createTask: vi.fn(),
  openClarifyStream: vi.fn(() => () => {}),
  submitClarify: vi.fn(),
}))

const mockedCreateLivingCircleTask = api.createLivingCircleTask as unknown as ReturnType<typeof vi.fn>
const mockedCreateTask = api.createTask as unknown as ReturnType<typeof vi.fn>
const mockedOpenClarifyStream = api.openClarifyStream as unknown as ReturnType<typeof vi.fn>
const mockedSubmitClarify = api.submitClarify as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  navigateFn.mockClear()
  mockedCreateLivingCircleTask.mockReset()
  mockedCreateTask.mockReset()
  mockedOpenClarifyStream.mockReset().mockImplementation(() => () => {})
  mockedSubmitClarify.mockReset().mockResolvedValue({ ok: true })
})

// globals:false 下 RTL 不会自动清理，须手动 cleanup，避免前序测试的
// loading/问卷容器残留在 document.body 干扰后续断言（如 T-CP1 误匹配旧 loading）。
afterEach(() => {
  cleanup()
})

function renderClarify(taskId: string) {
  return render(
    <MemoryRouter initialEntries={[`/clarify/${taskId}`]}>
      <Routes>
        <Route path="/clarify/:taskId" element={<ClarifyPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

// ── P0#2（M3 收口）：HomePage 三能力入口 —— 真实态旅游提交统一先进 ClarifyPage ──
// （分步弹窗向导 ResearchWizard 已退役；演示态直进 /workspace 由 homeDomainEntry 钉。）
describe('T-HP1 HomePage 真实态发起目的地调研（域卡 → /clarify/:taskId）', () => {
  it('攻略：createTask(type=guide) → /clarify/:taskId（不再直跳 workspace）', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't_xyz', kind: 'travel_guide', purpose: 'guide' })
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    )
    await screen.findByText('游玩攻略')
    const ta = screen.getByPlaceholderText(/想去哪里/)
    fireEvent.change(ta, { target: { value: '大理 5 天亲子游' } })
    fireEvent.click(screen.getByRole('button', { name: '开始调研' }))

    await waitFor(() => expect(mockedCreateTask).toHaveBeenCalledTimes(1))
    expect(mockedCreateTask).toHaveBeenCalledWith(
      '大理 5 天亲子游',
      'deep',
      undefined,
      'guide',
    )
    await waitFor(() => expect(navigateFn).toHaveBeenCalled())
    expect(navigateFn).toHaveBeenCalledWith(
      '/clarify/t_xyz',
      expect.objectContaining({ state: expect.objectContaining({ query: '大理 5 天亲子游', type: 'guide' }) }),
    )
  })

  it('评估：切「调研评估」卡 → createTask(type=assessment) → /clarify/:taskId', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't_ass', kind: 'travel_assess', purpose: 'assess' })
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    )
    await screen.findByText('游玩攻略')
    fireEvent.click(screen.getByText('调研评估'))
    fireEvent.change(screen.getByPlaceholderText(/评估哪几个城市/), { target: { value: '评估成都和杭州' } })
    fireEvent.click(screen.getByRole('button', { name: '开始调研' }))

    await waitFor(() => expect(mockedCreateTask).toHaveBeenCalledTimes(1))
    expect(mockedCreateTask.mock.calls[0][3]).toBe('assessment')
    await waitFor(() =>
      expect(navigateFn).toHaveBeenCalledWith(
        '/clarify/t_ass',
        expect.objectContaining({ state: expect.objectContaining({ query: '评估成都和杭州', type: 'assessment' }) }),
      ),
    )
  })
})

// ── P0#3：ClarifyPage loading 不误跳 + 空问卷跳 workspace ──
describe('T-CP3 / T-CP5 ClarifyPage 跳转边界', () => {
  it('T-CP5 loading 阶段不跳转，显示进度', () => {
    // openClarifyStream 不推送任何事件 → 保持 loading
    renderClarify('t_load')
    expect(screen.getByText(/正在为你准备调研问卷/)).toBeTruthy()
    expect(navigateFn).not.toHaveBeenCalled()
  })

  it('T-CP3 收到空问卷数组 → 跳 workspace', async () => {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_ready', { questions: [] })
      return () => {}
    })
    renderClarify('t_empty')
    await waitFor(() =>
      expect(navigateFn).toHaveBeenCalledWith(
        '/workspace/t_empty',
        expect.objectContaining({ replace: true }),
      ),
    )
  })
})

// ── P1#5 / SSE 驱动：loading → render / error → 重试 ──────
describe('T-CP1 / T-CP4 ClarifyPage SSE 状态机', () => {
  it('T-CP1 收到 clarify_ready 仅渲染首题 + 下一步，其余题目不在首屏', async () => {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_stage', { stage: 'understanding', message: '理解中' })
      handlers.onEvent('clarify_ready', {
        questions: [
          { id: 'q1', question: '最看重哪些维度？', type: 'multi', options: ['功能', '定价'] },
          { id: 'q2', question: '目标市场是？', type: 'single', options: ['国内', '海外'] },
        ],
      })
      return () => {}
    })
    renderClarify('t_ready')
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(screen.getByText('下一步')).toBeTruthy()
    // 向导分步：一次只显示一题，第二题不在首屏
    expect(screen.queryByText('目标市场是？')).toBeNull()
    expect(screen.queryByText(/正在为你准备调研问卷/)).toBeNull()
  })

  it('T-CP4 收到 error 显示提示 + 重试按钮', async () => {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('error', { message: '问卷生成失败' })
      return () => {}
    })
    renderClarify('t_err')
    expect(await screen.findByText(/问卷生成遇到问题/)).toBeTruthy()
    expect(screen.getByText('重试')).toBeTruthy()
  })
})

// ── 分步向导 + 内联核对屏（重构后交互模型） ──────────────
describe('T-Wizard 分步向导 + 核对屏', () => {
  const twoQs = [
    { id: 'q1', question: '最看重哪些维度？', type: 'multi' as const, options: ['功能', '定价'] },
    { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
  ]

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function mockReady(questions: any[]) {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_ready', { questions })
      return () => {}
    })
  }

  it('TC-W1 点「下一步」推进到第二题，首题移出当前步', async () => {
    mockReady(twoQs)
    renderClarify('t_w1')
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(screen.queryByText('目标市场是？')).toBeNull()
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('目标市场是？')).toBeTruthy()
    expect(screen.queryByText('最看重哪些维度？')).toBeNull()
    expect(screen.getByText(/第 2 \/ 2 题/)).toBeTruthy()
  })

  it('TC-W2 连续推进到末题再「下一步」进入核对屏（含全部题型控件）', async () => {
    mockReady(twoQs)
    renderClarify('t_w2')
    await screen.findByText('最看重哪些维度？')
    fireEvent.click(screen.getByText('下一步'))
    await screen.findByText('目标市场是？')
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
    expect(screen.getByText('最看重哪些维度？')).toBeTruthy()
    expect(screen.getByText('目标市场是？')).toBeTruthy()
    expect(screen.getByText('启动调研')).toBeTruthy()
  })

  it('TC-W3 核对屏内改选项 → answers 更新；点「启动调研」跳转 workspace', async () => {
    mockReady(twoQs)
    renderClarify('t_w3')
    await screen.findByText('最看重哪些维度？')
    fireEvent.click(screen.getByText('下一步'))
    await screen.findByText('目标市场是？')
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
    fireEvent.click(screen.getByText('海外'))
    fireEvent.click(screen.getByText('启动调研'))
    await waitFor(() =>
      expect(navigateFn).toHaveBeenCalledWith(
        '/workspace/t_w3',
        expect.objectContaining({ state: { query: '' } }),
      ),
    )
  })

  it('TC-W4 单题问卷：首题「下一步」直接进核对屏（无第二步）', async () => {
    mockReady([{ id: 'q1', question: '最看重哪些维度？', type: 'multi' as const, options: ['功能'] }])
    renderClarify('t_w4')
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
  })

  it('TC-W5 competitors 自定义输入在核对屏仍可添加', async () => {
    mockReady([
      { id: 'competitors', question: '重点调研哪些对象？', type: 'multi' as const, options: ['对象A'] },
    ])
    renderClarify('t_w5')
    await screen.findByText('重点调研哪些对象？')
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
    const input = screen.getByPlaceholderText(/补充其他想调研的/)
    fireEvent.change(input, { target: { value: '自研新品' } })
    fireEvent.click(screen.getByText('添加'))
    expect(await screen.findByText('自研新品')).toBeTruthy()
  })
})

// ── 自动前进：单选 / 多选选中后免点「下一步」即跳下一题 ──
// 研究结论（Typeform/Medallia/Clarky/Fomr/Paperform/SurveyVista）：
// single（350ms 视觉锁定）与 multi（1.2s 停顿，每次勾选重置）均自动前进；
// multi 另给「完成本题」按钮可立即跳过等待；text/slider 仍需显式确认，不自动跳。
describe('T-AutoAdvance 自动前进（单选 + 多选）', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function mockReady(questions: any[]) {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_ready', { questions })
      return () => {}
    })
  }

  it('TC-AA1 单选选中后延时自动进入下一题（无需点下一步）', async () => {
    mockReady([
      { id: 'q1', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
      { id: 'q2', question: '最看重哪些维度？', type: 'single' as const, options: ['功能', '定价'] },
    ])
    renderClarify('t_aa1')
    expect(await screen.findByText('目标市场是？')).toBeTruthy()
    expect(screen.queryByText('最看重哪些维度？')).toBeNull()
    // 选中单选选项 → 不应立即跳（视觉锁定 350ms）
    fireEvent.click(screen.getByText('国内'))
    expect(screen.queryByText('最看重哪些维度？')).toBeNull()
    // 延时后自动前进到下一题
    await waitFor(() => expect(screen.getByText('最看重哪些维度？')).toBeTruthy(), { timeout: 1500 })
    expect(screen.queryByText('目标市场是？')).toBeNull()
  })

  it('TC-AA2 选中后手动点「下一步」不双跳（仍仅前进 1 步）', async () => {
    mockReady([
      { id: 'q1', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
      { id: 'q2', question: '调研范围是？', type: 'single' as const, options: ['头部', '长尾'] },
      { id: 'q3', question: '预算偏好？', type: 'single' as const, options: ['高', '低'] },
    ])
    renderClarify('t_aa2')
    await screen.findByText('目标市场是？')
    fireEvent.click(screen.getByText('国内')) // 安排自动前进
    fireEvent.click(screen.getByText('下一步')) // 立刻手动前进并取消定时器
    expect(await screen.findByText('调研范围是？')).toBeTruthy()
    // 等待超出自动前进延时：因定时器已取消，且 q2 未选，应仍停在 q2（不双跳）
    await new Promise((r) => setTimeout(r, 600))
    expect(screen.getByText('调研范围是？')).toBeTruthy()
    expect(screen.queryByText('预算偏好？')).toBeNull()
  })

  it('TC-AA3 多选题选中后停顿自动前进（无需点下一步）+ 主按钮变「完成本题」', async () => {
    mockReady([
      { id: 'q1', question: '最看重哪些维度？', type: 'multi' as const, options: ['功能', '定价'] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa3')
    await screen.findByText('最看重哪些维度？')
    fireEvent.click(screen.getByText('功能')) // 多选切换 → 应出现「完成本题」按钮
    expect(await screen.findByText('完成本题')).toBeTruthy()
    // 停顿超过 1.2s 后自动前进到下一题
    await waitFor(() => expect(screen.getByText('目标市场是？')).toBeTruthy(), { timeout: 2500 })
    expect(screen.queryByText('最看重哪些维度？')).toBeNull()
  })

  it('TC-AA5 多选点「完成本题」立即前进，不等待停顿且不双跳', async () => {
    mockReady([
      { id: 'q1', question: '最看重哪些维度？', type: 'multi' as const, options: ['功能', '定价'] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa5')
    await screen.findByText('最看重哪些维度？')
    fireEvent.click(screen.getByText('功能'))
    expect(await screen.findByText('完成本题')).toBeTruthy()
    fireEvent.click(screen.getByText('完成本题')) // 立即前进并取消定时器
    expect(await screen.findByText('目标市场是？')).toBeTruthy()
    // 等待超出停顿窗口：因定时器已取消，应停在 q2（不双跳到核对屏）
    await new Promise((r) => setTimeout(r, 1600))
    expect(screen.getByText('目标市场是？')).toBeTruthy()
    expect(screen.queryByText(/请核对/)).toBeNull()
  })

  it('TC-AA6 多选取消到 0 项不自动前进，按钮回到「下一步」', async () => {
    mockReady([
      { id: 'q1', question: '最看重哪些维度？', type: 'multi' as const, options: ['功能', '定价'] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa6')
    await screen.findByText('最看重哪些维度？')
    fireEvent.click(screen.getByText('功能')) // 选中 → 完成本题
    expect(await screen.findByText('完成本题')).toBeTruthy()
    fireEvent.click(screen.getByText('功能')) // 再点取消 → 回到下一步
    expect(await screen.findByText('下一步')).toBeTruthy()
    await new Promise((r) => setTimeout(r, 1600))
    expect(screen.getByText('最看重哪些维度？')).toBeTruthy() // 未自动前进
    expect(screen.queryByText('目标市场是？')).toBeNull()
  })

  it('TC-AA7 competitors（multi+自定义）选中后同样停顿自动前进', async () => {
    mockReady([
      { id: 'competitors', question: '重点调研哪些对象？', type: 'multi' as const, options: ['对象A'] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa7')
    await screen.findByText('重点调研哪些对象？')
    fireEvent.click(screen.getByText('对象A')) // 多选 chip → 走与 multi 同一路径
    expect(await screen.findByText('完成本题')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('目标市场是？')).toBeTruthy(), { timeout: 2500 })
  })

  it('TC-AA8 competitors 单步自定义补充后同样停顿自动前进（走 maybeAdvance 统一路径）', async () => {
    mockReady([
      { id: 'competitors', question: '重点调研哪些对象？', type: 'multi' as const, options: ['对象A'] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa8')
    await screen.findByText('重点调研哪些对象？')
    const input = screen.getByPlaceholderText(/补充其他想调研的/)
    fireEvent.change(input, { target: { value: '自研新品' } })
    fireEvent.click(screen.getByText('添加')) // 自定义补充 → 经 maybeAdvance 排程（验证 schedule 形参已移除）
    expect(await screen.findByText('完成本题')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('目标市场是？')).toBeTruthy(), { timeout: 2500 })
  })

  it('TC-AA4 文本题输入后不自动前进（需显式确认）', async () => {
    mockReady([
      { id: 'q1', question: '补充背景信息', type: 'text' as const, options: [] },
      { id: 'q2', question: '目标市场是？', type: 'single' as const, options: ['国内', '海外'] },
    ])
    renderClarify('t_aa4')
    await screen.findByText('补充背景信息')
    const ta = screen.getByPlaceholderText(/选填，可补充背景信息/)
    fireEvent.change(ta, { target: { value: 'B 公司在海外占优' } })
    await new Promise((r) => setTimeout(r, 600))
    expect(screen.getByText('补充背景信息')).toBeTruthy()
    expect(screen.queryByText('目标市场是？')).toBeNull()
  })
})

// ── 修复 S1+S2 回归：浏览器原生 onError 通道 ──────────────
// 既有 5 条测试只通过 mock 调用 handlers.onEvent(...)，从不调用 onError，
// 而真实 bug 正好走 onError（有限流关闭 → EventSource.onerror）。以下补齐该通道。
describe('T-Ax ClarifyPage SSE onError 通道（S1+S2 回归）', () => {
  it('TC-A1 clarify_ready 后 onError 不误报 → 渲染问卷', async () => {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_ready', {
        questions: [{ id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能', '定价'] }],
      })
      handlers.onError() // 模拟有限流关闭触发的原生 onerror
      return () => {}
    })
    renderClarify('t_onerr_after_ready')
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(screen.queryByText(/问卷生成遇到问题/)).toBeNull()
  })

  it('TC-A2 未就绪时 onError → 显示错误 + 重试（真实失败出口不被遮盖）', async () => {
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onError() // 真实连接失败，未收到任何 clarify_ready
      return () => {}
    })
    renderClarify('t_onerr_before_ready')
    expect(await screen.findByText(/问卷生成遇到问题/)).toBeTruthy()
    expect(screen.getByText('重试')).toBeTruthy()
  })

  it('TC-A3 clarify_ready 后主动 close()', async () => {
    const closeSpy = vi.fn()
    // 捕获 handlers 但不立即派发；真实 SSE 在 openClarifyStream 返回（close 已赋值）后才异步到达。
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let captured: any = null
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      captured = handlers
      return closeSpy
    })
    renderClarify('t_close_after_ready')
    // 模拟事件在连接建立后到达（此时 closeFn 已指向 closeSpy，S1 的 close() 才会真正生效）
    act(() => {
      captured?.onEvent('clarify_ready', {
        questions: [{ id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] }],
      })
    })
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(closeSpy).toHaveBeenCalled()
  })

  it('TC-A4 clarify_update(competitors_fallback) → 核对屏温和提示（C6，替代旧 degraded 大警告）', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let handlers: any = null
    mockedOpenClarifyStream.mockImplementation((_tid, h) => { handlers = h; return () => {} })
    renderClarify('t_c6')
    // 基础题即时（partial）+ 竞品发现兜底到达（clarify_update, competitors_fallback）
    act(() => {
      handlers?.onEvent('clarify_ready', {
        questions: [{ id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] }],
        partial: true,
      })
      handlers?.onEvent('clarify_update', {
        questions: [
          { id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] },
          { id: 'competitors', question: '重点调研哪些对象？', type: 'multi', options: ['对象A'] },
        ],
        competitors_fallback: true,
        complete: true,
      })
    })
    // 推进到核对屏：第 0 题 focus → 第 1 题 competitors → 第 2 题（review）
    fireEvent.click(screen.getByText('下一步'))
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
    expect(screen.getByText(/以下调研对象为自动识别候选，建议核对或手动补充/)).toBeTruthy()
    // 旧的大警告文案必须消失（C6：不再弹「AI 不可用」）
    expect(screen.queryByText(/已使用默认问卷/)).toBeNull()
  })

  it('TC-A8 clarify_update 增量追加竞品题到末尾（C4），且保留当前步不漂移', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let handlers: any = null
    mockedOpenClarifyStream.mockImplementation((_tid, h) => { handlers = h; return () => {} })
    renderClarify('t_c4')
    // 基础题即时（partial）：只有 focus + perspective，scope/competitors 尚未出现
    act(() => {
      handlers?.onEvent('clarify_ready', {
        questions: [
          { id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] },
          { id: 'perspective', question: '视角？', type: 'single', options: ['PM'] },
        ],
        partial: true,
      })
    })
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(screen.queryByText(/请确认我们理解的调研对象/)).toBeNull()
    expect(screen.queryByText(/自动发现了以下候选对象/)).toBeNull()
    // 调研对象发现完成 → 增量追加到末尾（scope + competitors），当前步不变
    act(() => {
      handlers?.onEvent('clarify_update', {
        questions: [
          { id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] },
          { id: 'perspective', question: '视角？', type: 'single', options: ['PM'] },
          { id: 'scope', question: '请确认我们理解的调研对象是否准确？', type: 'single', options: ['准确，继续', '不准确'] },
          { id: 'competitors', question: '自动发现了以下候选对象，请勾选', type: 'multi', options: ['对象A'] },
        ],
        competitors_fallback: false,
        complete: true,
      })
    })
    // 当前仍停在 focus（步未漂移），但新题已在末尾、推进后可达
    expect(screen.getByText('最看重哪些维度？')).toBeTruthy()
    // focus → perspective
    fireEvent.click(screen.getByText('下一步'))
    // perspective → scope（调研对象发现追加的 scope 题）
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText(/请确认我们理解的调研对象是否准确/)).toBeTruthy()
    // scope → competitors（调研对象发现追加的 competitors 题）
    fireEvent.click(screen.getByText('下一步'))
    expect(await screen.findByText(/自动发现了以下候选对象/)).toBeTruthy()
  })

  it('TC-A5 点击重试重新拉起 SSE', async () => {
    // 第一次：未就绪即 onError → 错误态
    mockedOpenClarifyStream.mockImplementationOnce((_tid, handlers) => {
      handlers.onError()
      return () => {}
    })
    // 后续（retry 重臂）：正常送达
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      handlers.onEvent('clarify_ready', {
        questions: [{ id: 'focus', question: '最看重哪些维度？', type: 'multi', options: ['功能'] }],
      })
      return () => {}
    })
    renderClarify('t_retry')
    expect(await screen.findByText(/问卷生成遇到问题/)).toBeTruthy()
    fireEvent.click(screen.getByText('重试'))
    expect(await screen.findByText('最看重哪些维度？')).toBeTruthy()
    expect(mockedOpenClarifyStream).toHaveBeenCalledTimes(2)
  })
})

// ── SSE 生命周期：清理 / 卸载守卫 ────────────────────────
describe('T-Ax ClarifyPage SSE 生命周期', () => {
  it('TC-A6 卸载时 close() 被调用（无泄漏）', () => {
    const closeSpy = vi.fn()
    mockedOpenClarifyStream.mockImplementation(() => closeSpy)
    const { unmount } = renderClarify('t_unmount')
    unmount()
    expect(closeSpy).toHaveBeenCalled()
  })

  it('TC-A7 卸载后延迟事件被忽略（不抛错）', () => {
    let captured: ((type: string, data?: unknown) => void) | null = null
    mockedOpenClarifyStream.mockImplementation((_tid, handlers) => {
      captured = handlers.onEvent
      return () => {}
    })
    const { unmount } = renderClarify('t_late')
    unmount()
    // 卸载后模拟延迟事件到达：closed 守卫应使其提前返回，不抛错
    expect(() =>
      captured?.('clarify_ready', {
        questions: [{ id: 'x', question: 'q', type: 'multi', options: [] }],
      }),
    ).not.toThrow()
  })
})

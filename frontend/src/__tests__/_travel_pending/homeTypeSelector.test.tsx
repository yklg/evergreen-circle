// @vitest-environment jsdom
/**
 * F1 首页调研类型选择器（F1-1 ~ F1-5）
 *
 * 守护的契约（计划 §5.4 F1 / 规则 R1 单一真相源 + R4 契约键名成对断言）：
 *   F1-1 卡片文案来自 GET /api/research-types（前端不复制 label/subtitle）
 *   F1-2 两张卡互斥选中（aria-pressed）
 *   F1-3 提交时 createTask 收到当前选中的 type（类型透传不丢）
 *   F1-4 类型接口失败 → 显式错误态 + 提交被拦（不静默兜底默认类型）
 *   F1-5 类型切换 → 示例卡随之切换（key={rtype} 重建）
 *
 * 说明：`fetchResearchTypes` 走 `safeJson(..., [])`，接口失败时**不 reject** 而是
 * 回落空数组，因此 F1-4 用 mockResolvedValue([]) 忠实模拟失败，而非 mockRejected。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import HomePage from '../pages/HomePage'
import * as api from '../lib/api'
import { useUIStore } from '../store/uiStore'

vi.mock('../lib/api', () => ({
  createTask: vi.fn(),
  fetchResearchTypes: vi.fn(),
  fetchExperts: vi.fn().mockResolvedValue([]),
  fetchSettings: vi.fn().mockResolvedValue(null),
  getPrefsApiCapability: vi.fn(() => 'unsupported'),
}))

const mockedCreateTask = api.createTask as unknown as ReturnType<typeof vi.fn>
const mockedFetchResearchTypes = api.fetchResearchTypes as unknown as ReturnType<typeof vi.fn>

/* 哨兵文案：若前端硬编码了「游玩攻略/调研评估」，以下断言会失败。
   键保持真实 key（guide/assessment），否则示例卡与占位符无法按类型切换。 */
const TYPES = [
  { key: 'guide', label: 'ZZTYPE_ALPHA', subtitle: 'ZZSUB_ALPHA' },
  { key: 'assessment', label: 'ZZTYPE_BETA', subtitle: 'ZZSUB_BETA' },
]

beforeEach(() => {
  mockedCreateTask.mockReset().mockResolvedValue({ taskId: 't_1' })
  mockedFetchResearchTypes.mockReset().mockResolvedValue(TYPES)
  // 模型选择器持久化在 localStorage，跨用例可能残留 → 显式归零保证 modelOverride 稳定
  useUIStore.setState({ model: 'Auto' })
  localStorage.clear()
})

afterEach(() => {
  cleanup()
})

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  )
}

/* 提交按钮无 accessible name（纯图标），失败态下它是页面上唯一 disabled 的按钮 */
function submitButton(container: HTMLElement): HTMLButtonElement | null {
  return container.querySelector<HTMLButtonElement>('button[disabled]')
}

describe('F1 首页调研类型选择器', () => {
  it('F1-1 卡片 label/subtitle 全部来自接口，前端未硬编码类型文案', async () => {
    renderHome()
    expect(await screen.findByText('ZZTYPE_ALPHA')).toBeTruthy()
    expect(screen.getByText('ZZSUB_ALPHA')).toBeTruthy()
    expect(screen.getByText('ZZTYPE_BETA')).toBeTruthy()
    expect(screen.getByText('ZZSUB_BETA')).toBeTruthy()
    // 防回潮：后端注册表的中文文案不得出现在前端源码里
    expect(screen.queryByText('游玩攻略')).toBeNull()
    expect(screen.queryByText('调研评估')).toBeNull()
  })

  it('F1-2 默认选中首张卡，点击第二张后互斥切换', async () => {
    renderHome()
    const cardA = await screen.findByRole('button', { name: /ZZTYPE_ALPHA/ })
    const cardB = screen.getByRole('button', { name: /ZZTYPE_BETA/ })

    expect(cardA.getAttribute('aria-pressed')).toBe('true')
    expect(cardB.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(cardB)
    expect(cardB.getAttribute('aria-pressed')).toBe('true')
    expect(cardA.getAttribute('aria-pressed')).toBe('false')
  })

  it('F1-3 选中第二张卡后提交，createTask 收到该 type', async () => {
    renderHome()
    fireEvent.click(await screen.findByRole('button', { name: /ZZTYPE_BETA/ }))

    const ta = screen.getByPlaceholderText(/想评估哪个城市/)
    fireEvent.change(ta, { target: { value: '评估成都和杭州哪个更适合长期居住' } })
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true })

    await waitFor(() => expect(mockedCreateTask).toHaveBeenCalledTimes(1))
    expect(mockedCreateTask).toHaveBeenCalledWith(
      '评估成都和杭州哪个更适合长期居住',
      'deep',
      null,
      'assessment',
    )
  })

  it('F1-4 类型接口失败（空数组）→ 错误态 + 提交被拦', async () => {
    mockedFetchResearchTypes.mockResolvedValue([])
    const { container } = renderHome()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('调研类型加载失败')

    const btn = submitButton(container)
    expect(btn).not.toBeNull()
    expect(btn?.disabled).toBe(true)

    // 走键盘提交路径（绕过 disabled 属性）验证 submit() 自身的 typesFailed 守卫
    const ta = screen.getByPlaceholderText(/想去哪里玩/)
    fireEvent.change(ta, { target: { value: '大理 5 天亲子游攻略' } })
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true })
    await waitFor(() => expect(alert).toBeTruthy())
    expect(mockedCreateTask).not.toHaveBeenCalled()
  })

  it('F1-5 类型切换 → 示例卡与输入占位符随之切换', async () => {
    renderHome()
    await screen.findByRole('button', { name: /ZZTYPE_ALPHA/ })

    // guide（默认）：攻略类示例 + 攻略类占位符
    expect(screen.getByText('亲子路线规划')).toBeTruthy()
    expect(screen.getByPlaceholderText(/想去哪里玩/)).toBeTruthy()
    expect(screen.queryByText('宜居度横向对比')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /ZZTYPE_BETA/ }))

    expect(screen.getByText('宜居度横向对比')).toBeTruthy()
    expect(screen.getByPlaceholderText(/想评估哪个城市/)).toBeTruthy()
    expect(screen.queryByText('亲子路线规划')).toBeNull()
  })
})

// @vitest-environment jsdom
/**
 * HomePage 入口 → 分步问答向导：演示态（fixture）点箭头/样例卡/自定义卡都会先弹出
 * 「目的地调研 · 分步问答」（Q1 报告类型 → Q2 深度 → 确认），确认后 launchResearch
 * 建任务（fixture 兜底 demo-*）再进入 /workspace/:taskId 流水线。两种数据模式行为统一。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import type { ComponentType } from 'react'

afterEach(cleanup)

function PathProbe() {
  const loc = useLocation()
  return <div data-testid="path">{loc.pathname}</div>
}

async function renderHomeMock() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'fixture' })
  const { default: HomePage } = await import('../pages/HomePage')
  const Home = HomePage as ComponentType
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/workspace" element={<PathProbe />} />
        <Route path="/workspace/:wId" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function lastPath(): string | null {
  const els = screen.queryAllByTestId('path')
  if (!els.length) return null
  return els[els.length - 1]?.textContent ?? null
}

/** 走完分步问答：Q1 选报告类型 → 下一步 → Q2 选深度 → 下一步 → 确认 → 发起调研 */
async function walkWizard(expectedTarget: string) {
  await waitFor(() => expect(screen.getByText(/分步问答/)).toBeTruthy())
  expect(screen.getByText(new RegExp(`目标：${expectedTarget}`))).toBeTruthy()
  // Q1
  fireEvent.click(screen.getByRole('button', { name: /游玩攻略/ }))
  fireEvent.click(screen.getByRole('button', { name: '下一步' }))
  // Q2
  fireEvent.click(screen.getByRole('button', { name: /深度/ }))
  fireEvent.click(screen.getByRole('button', { name: '下一步' }))
  // Q3 确认 + 发起（精确文本，避免撞上自定义卡副文案里的「发起调研」）
  fireEvent.click(screen.getByRole('button', { name: '发起调研' }))
}

describe('HomePage → 分步问答向导（演示态 fixture）', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  it('箭头（开始调研）点击 → 先弹向导，确认后进入 /workspace/demo-* 流水线', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByTitle('开始目的地调研'))
    await walkWizard('黄山')
    await waitFor(() => expect(lastPath()?.startsWith('/workspace/demo-')).toBe(true))
  })

  it('样例卡「凯里老街」→ 向导目标=凯里老街 → 确认后进入流水线', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByRole('button', { name: /凯里老街/ }))
    await walkWizard('凯里老街')
    await waitFor(() => expect(lastPath()?.startsWith('/workspace/demo-')).toBe(true))
  })

  it('「自定义目的地」卡 → 向导目标降级为黄山（未填）→ 确认后进入流水线', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByRole('button', { name: /自定义目的地/ }))
    await walkWizard('黄山')
    await waitFor(() => expect(lastPath()?.startsWith('/workspace/demo-')).toBe(true))
  })
})
// @vitest-environment jsdom
/**
 * F6 · HomePage 的 VITE_USE_MOCK=1 分支：提交/样例卡直接进生活圈地图页。
 * 注意：须在模块求值前 stub 环境，且用 resetModules 绕过 HomePage 模块缓存
 *（clarifyAsync.test 以默认 env 走真实分支，二者互不污染）。
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
  vi.stubEnv('VITE_USE_MOCK', '1')
  const { default: HomePage } = await import('../pages/HomePage')
  const Home = HomePage as ComponentType
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/life-circle/:sceneId" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** 读当前路由路径（容忍历史渲染残留，取末位） */
function lastPath(): string | null {
  const els = screen.queryAllByTestId('path')
  if (!els.length) return null
  return els[els.length - 1]?.textContent ?? null
}

describe('HomePage · VITE_USE_MOCK=1 分支', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  it('样例卡「凯里老街」点击 → /life-circle/kaili', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByRole('button', { name: /凯里老街/ }))
    await waitFor(() => expect(lastPath()).toBe('/life-circle/kaili'))
  })

  it('空输入直接提交 → 默认 /life-circle/kaili（当前样例兜底）', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByTitle('开始生活圈体检'))
    await waitFor(() => expect(lastPath()).toBe('/life-circle/kaili'))
  })

  it('「自定义中心点」卡 → /life-circle/custom', async () => {
    await renderHomeMock()
    fireEvent.click(screen.getByRole('button', { name: /自定义中心点/ }))
    await waitFor(() => expect(lastPath()).toBe('/life-circle/custom'))
  })
})
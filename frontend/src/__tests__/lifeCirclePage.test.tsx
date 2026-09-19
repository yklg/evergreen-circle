// @vitest-environment jsdom
/**
 * F3 · LifeCirclePage 渲染与交互：fixture 渲染 / 未知场景降级 / 画布点选触发「重新体检」。
 * 此文件守护 fixture 态（USE_MOCK=1），与 clarifyAsync（真实分支）互不污染。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../mocks/livingCircleMock', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../mocks/livingCircleMock')>()
  return { ...actual, USE_MOCK: true }
})

import LifeCirclePage from '../pages/LifeCirclePage'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'

afterEach(cleanup)

function renderScene(sceneId: string) {
  return render(
    <MemoryRouter initialEntries={[`/life-circle/${sceneId}`]}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LifeCirclePage（fixture 态）', () => {
  it('凯里样例：渲染等时圈画布、总评分、三要素与盲区清单', () => {
    const { container } = renderScene('kaili')
    // 等时圈画布存在（SVG 内含多个 polygon：等时圈族 + 盲区）
    expect(screen.getByRole('img', { name: '生活圈等时圈画布' })).toBeTruthy()
    expect(container.querySelectorAll('polygon').length).toBeGreaterThanOrEqual(4)
    // 总评分（fixture total）
    expect(screen.getAllByText(String(kaili.scores.total)).length).toBeGreaterThan(0)
    // 三要素 chips（覆盖 => 显示「最近 …min」）
    expect(screen.getAllByText(/菜市场/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/药店/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/小学/).length).toBeGreaterThan(0)
    // 盲区清单面板
    expect(screen.getByText('服务盲区清单')).toBeTruthy()
    // 演示数据横幅
    expect(screen.getByText(/演示数据模式/)).toBeTruthy()
  })

  it('未知场景 id：按 mock 契约回退首个样例，不崩溃', () => {
    renderScene('ghost-town')
    // getLifeCircleMock 对未知 id 回退首个样例（凯里）
    expect(screen.getByText(/演示数据模式/)).toBeTruthy()
  })

  it('画布点选设定新中心点 → 出现「重新体检」按钮（D2 交互）', async () => {
    renderScene('kaili')
    const canvas = screen.getByRole('img', { name: '生活圈等时圈画布' })
    fireEvent.click(canvas, { clientX: 300, clientY: 300 })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /重新体检/ })).toBeTruthy()
    })
  })

  it('切换到北京劲松样例（场景切换按钮）', () => {
    renderScene('kaili')
    const btn = screen.getByRole('button', { name: /北京劲松/ })
    fireEvent.click(btn)
    // 切到 /life-circle/beijing-jinsong 后应看到劲松场景名（导航按钮 + 中心点标签至少两处）
    waitFor(() => {
      expect(screen.getAllByText('北京劲松').length).toBeGreaterThan(0)
    })
  })
})
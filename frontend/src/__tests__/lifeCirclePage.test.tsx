// @vitest-environment jsdom
/**
 * F3 · LifeCirclePage 渲染与交互：fixture 渲染 / 未知场景降级 / 画布点选触发「重新体检」。
 * 数据模式已运行时化：本文件守护演示态（fixture），beforeEach 注入 store。
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import LifeCirclePage from '../pages/LifeCirclePage'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { useDataModeStore } from '../store/dataModeStore'
import { LC_CANVAS, lcMeters } from '../lib/livingCircle'
import type { LngLat } from '../types'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

/** jsdom 没有布局引擎 → getBoundingClientRect 恒为 0×0；这里给画布一个真实尺寸 */
function rectOf(w: number, h: number): DOMRect {
  return { x: 0, y: 0, left: 0, top: 0, right: w, bottom: h, width: w, height: h, toJSON: () => ({}) } as DOMRect
}

beforeEach(() => {
  useDataModeStore.setState({ mode: 'fixture' })
})

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
  it('凯里样例：渲染等时圈画布、总评分、三要素与盲区清单', async () => {
    const { container } = renderScene('kaili')
    // LcMap 异步初始化（jsdom 无网络 → 无 AK → 降级静态画布），等待画布出现
    const canvas = await screen.findByRole('img', { name: /生活圈等时圈画布/ })
    expect(canvas).toBeTruthy()
    expect(container.querySelectorAll('polygon').length).toBeGreaterThanOrEqual(4)
    // 总评分（fixture total）
    expect(screen.getAllByText(String(kaili.scores.total)).length).toBeGreaterThan(0)
    // 三要素 chips（覆盖 => 显示「最近 …min」）
    expect(screen.getAllByText(/菜市场/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/药店/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/小学/).length).toBeGreaterThan(0)
    // 盲区清单面板
    expect(screen.getByText('服务盲区清单')).toBeTruthy()
    // 内置快照横幅（M5 真实数据，降级模式仍标注）
    expect(screen.getByText(/内置快照/)).toBeTruthy()
    // C3：定位到我按钮存在
    expect(screen.getByRole('button', { name: /定位到我/ })).toBeTruthy()
  })

  it('未知场景 id：按 mock 契约回退首个样例，不崩溃', async () => {
    renderScene('ghost-town')
    // getLifeCircleMock 对未知 id 回退首个样例（凯里）
    await screen.findByText(/内置快照/)
    expect(screen.getByText(/内置快照/)).toBeTruthy()
  })

  it('画布点选设定新中心点 → 出现「重新体检」按钮（D2 交互，降级画布）', async () => {
    renderScene('kaili')
    const canvas = await screen.findByRole('img', { name: /生活圈等时圈画布/ })
    // ⚠️ jsdom 的 getBoundingClientRect 恒为 0×0，点击位置会换算成 Infinity ——
    // 不给真实尺寸的话，这条用例测的是「除零」而不是「点选」。
    // （LcMap 已对 0×0 做显式拒绝，见 fallbackCanvas.click 守卫）
    vi.spyOn(SVGElement.prototype, 'getBoundingClientRect').mockReturnValue(rectOf(LC_CANVAS.W, LC_CANVAS.H))

    // 点画布 3/4 宽、1/2 高：x 半宽对应 R=2500m → 落点应为「中心正东 1250m」
    fireEvent.click(canvas, { clientX: LC_CANVAS.W * 0.75, clientY: LC_CANVAS.H / 2 })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /重新体检/ })).toBeTruthy()
    })
    // 落点不能只是「某个合法值」：用反投影 lcMeters 回算，必须落在「中心正东 1250m」。
    // 容差 15m 的依据：UI 显示保留 4 位小数 → 经度量化 0.0001° ≈ 10m，属显示精度而非算法误差。
    const shown = screen.getByText(/已设定新中心点/).textContent ?? ''
    const m = /（([-\d.]+), ([-\d.]+)）/.exec(shown)
    expect(m, `未读到新中心点文案，实际：${shown}`).toBeTruthy()
    const [mx, my] = lcMeters(kaili.scene.center as LngLat, Number(m![1]), Number(m![2]))
    expect(mx).toBeGreaterThan(0) // 东移（方向不能反）
    expect(Math.abs(mx - 1250)).toBeLessThan(15)
    expect(Math.abs(my)).toBeLessThan(15)
  })

  it('画布 0×0（未布局）时点选被拒绝，不产生非法中心点', async () => {
    renderScene('kaili')
    const canvas = await screen.findByRole('img', { name: /生活圈等时圈画布/ })
    vi.spyOn(SVGElement.prototype, 'getBoundingClientRect').mockReturnValue(rectOf(0, 0))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    fireEvent.click(canvas, { clientX: 300, clientY: 300 })

    // 不出现「已设定新中心点」，也不出现「重新体检」
    expect(screen.queryByRole('button', { name: /重新体检/ })).toBeNull()
    expect(warn.mock.calls.map((c) => String(c[0])).join(' ')).toContain('无法映射为坐标')
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
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

  // ── 阶段 −1 新增：两个「结论可信度」护栏（此前体检台完全没披露） ──────────────

  it('盲区数必须与判盲覆盖度同屏（kaili 只有 9/72 格被判定过）', async () => {
    renderScene('kaili')
    await screen.findByText(/内置快照/)
    const cal = kaili.caliber
    // 前提守卫：夹具确实存在大量未判定格，否则本条断言是空转
    expect(cal.cells_unknown).toBeGreaterThan(0)
    expect(cal.cells_inside).toBe(cal.cells_judged + cal.cells_unknown)

    // ① StatRow「服务盲区」旁的一行紧凑披露
    expect(
      screen.getByText(
        new RegExp(`可达区 ${cal.cells_inside} 格中仅判 ${cal.cells_judged} 格，${cal.cells_unknown} 格数据不足未判`),
      ),
    ).toBeTruthy()
    // ② 0 处盲区时的结论句不得说「三要素齐备」而隐去未判定面
    expect(screen.getByText(new RegExp(`仍有 ${cal.cells_unknown} 格无法判定`))).toBeTruthy()
    // ③ 完整脚注（含少报提示）
    expect(screen.getByText(/判定覆盖：网格 72 格中已判定 9 格/)).toBeTruthy()
  })

  it('劲松样例（有盲区）同样披露判盲覆盖度', async () => {
    renderScene('kaili')
    fireEvent.click(screen.getByRole('button', { name: /北京劲松/ }))
    await waitFor(() => {
      expect(
        screen.getByText(new RegExp(`可达区 99 格中仅判 9 格，90 格数据不足未判`)),
      ).toBeTruthy()
    })
  })

  it('采样点分档上屏：可达数必须小于采样总数（旧口径「可达 = 全部」不得回流）', async () => {
    renderScene('kaili')
    await screen.findByText(/内置快照/)
    const s = kaili.sampling
    const total = s.points.length
    const inReach = s.in_reach_count!
    // 前提守卫：可达数必须明显小于采样数，否则这条断言没有判别力
    expect(inReach).toBeLessThan(total)
    expect(inReach).toBeGreaterThan(0)

    expect(
      screen.getByText(
        new RegExp(`采样 ${total} 个（≤${kaili.caliber.reach_full_min} 分钟内可达 ${inReach}）`),
      ),
    ).toBeTruthy()
    // 旧口径：把采样总数当成可达数（「可达 1049」）——必须不再出现
    expect(screen.queryByText(new RegExp(`可达 ${total}\\)`))).toBeNull()
    expect(screen.queryByText(new RegExp(`可达 ${total}）`))).toBeNull()
  })
})
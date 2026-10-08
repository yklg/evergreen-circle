// @vitest-environment jsdom
/**
 * 体检台主图的「方位形状」层与右栏八方位条形卡（2026-10-08 深夜）。
 *
 * 这条能力的全部理由是：报告页那张 `draggableCenter={false}` 只能看，而形状是**以中心为原点**
 * 量的八方位最远可达 —— "挪一下中心，哪个方向变好了"只有在体检台问得出来。
 *
 * 台架照 `judgeScaleToggle.test.tsx:46-68` 那条既有先例：体检台的报告**不是 props 传进来的**
 * （页面按路由从样区注册表取），所以要改载荷只能 mock `livingCircleMock`。
 * 没有这条先例，"形状键不在场"那一态在 jsdom 里根本造不出来 —— 而造不出来时最容易的退路
 * 是"只测在场"，那正是本文件要防的恒真。
 *
 * 与右上角那颗 `role="switch"` 的开关（报告页第三屏专用）不同：体检台这颗是图例里的
 * **原生 `<input type=checkbox>`**，勾选态读 `element.checked` —— 原生复选框没有 `aria-checked`
 * 属性，按 `[aria-checked]` 去问会得到 `null`，那条断言就成了"永远不等于 'true'"的假绿。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { useDataModeStore } from '../store/dataModeStore'
import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import type { LivingCircleReport } from '../types'

const state = vi.hoisted(() => ({ stripShape: false }))

vi.mock('../lib/bmap', () => ({
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => { throw new Error('测试内不应注入 BMapGL') },
  geolocateMe: async () => null,
}))

vi.mock('../mocks/livingCircleMock', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../mocks/livingCircleMock')>()
  return {
    ...mod,
    getLifeCircleMock: (id: string) => {
      const base = mod.getLifeCircleMock(id)
      if (!base || !state.stripShape) return base
      return {
        ...base,
        isochrones: base.isochrones.map((z) => ({ ...z, shape: undefined })),
      } as LivingCircleReport
    },
  }
})

// mock 必须在 vi.mock 之后 import（hoisting 已把工厂提到最前）
const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')

const LABEL = '方位形状（八方位最远可达）'
const CARD_TITLE = '方位最远可达 · 15min'

async function openStage() {
  const view = render(
    <MemoryRouter initialEntries={['/life-circle/kaili-ev2']}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )
  // 等 getMapConfig 的 microtask 与 setMode('fallback') 的重渲染落地（同 lcReportLocalMap 的搭法）
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
  return view
}

/** 图例里那颗原生复选框（找不到就返回 null，让调用方去断"不出现"）。 */
function checkbox(): HTMLInputElement | null {
  const label = screen.queryByText(LABEL)?.closest('label')
  return (label?.querySelector('input[type="checkbox"]') as HTMLInputElement | null) ?? null
}
const sectors = (root: ParentNode = document) => [...root.querySelectorAll('[data-sector]')]

beforeEach(() => {
  useDataModeStore.setState({ mode: 'fixture' })
  state.stripShape = false
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    (globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {} unobserve() {} disconnect() {}
    }
  }
})
afterEach(cleanup)

describe('体检台 · 方位形状层与八方位条形卡', () => {
  it('前置自证：这份样区确实带 15min 形状键（漂了下面全是白测）', () => {
    const iso = (kailiEv2.isochrones as LivingCircleReport['isochrones']).find((z) => z.minutes === 15)
    const bins = iso?.shape?.bins_m
    expect(bins, '样区注册表换了 ⇒ 在场态的夹具前提没了').toHaveLength(8)
    expect(state.stripShape).toBe(false)
  })

  it('在场 ⇒ 图例里有这颗勾选，且默认关、画布上没有扇区', async () => {
    await openStage()
    const box = checkbox()
    expect(box, '形状键在场却不出现开关 ⇒ 体检台读不到方向性').not.toBeNull()
    expect(box!.checked, '默认必须关（解释层不是主叙事层）').toBe(false)
    expect(sectors(), '默认关时不该画楔形').toHaveLength(0)
  })

  it('勾上 ⇒ 8 个楔形；再取消 ⇒ 回到 0（集合差，不是"少了一个"）', async () => {
    await openStage()
    fireEvent.click(checkbox()!)
    expect(sectors().map((el) => el.getAttribute('data-sector')).sort())
      .toEqual(['0', '1', '2', '3', '4', '5', '6', '7'])
    fireEvent.click(checkbox()!)
    expect(sectors()).toHaveLength(0)
  })

  it('形状键抹掉 ⇒ 勾选不出现，**且**条形卡也不出现（两条一起断，禁恒真）', async () => {
    state.stripShape = true
    await openStage()
    expect(checkbox(), '没有形状键却摆一颗勾不动的复选框 ⇒ 假入口').toBeNull()
    expect(screen.queryByText(CARD_TITLE), '条形卡没跟着退场 ⇒ 卡的在场判据没走 shapeOfZone')
      .toBeNull()
  })

  it('条形卡不跟扇区开关走：默认关时卡仍在、八行齐全', async () => {
    await openStage()
    const card = screen.getByText(CARD_TITLE).parentElement as HTMLElement
    expect(checkbox()!.checked).toBe(false)
    expect(card.querySelectorAll('button')).toHaveLength(8)
  })

  it('互指通道只有一份 state：点卡里一行 ⇒ 图上那块变红；点图上楔形 ⇒ 卡里那行按下', async () => {
    await openStage()
    fireEvent.click(checkbox()!)   // 楔形要先在场上
    const card = screen.getByText(CARD_TITLE).parentElement as HTMLElement
    const rows = [...card.querySelectorAll('button')]
    expect(rows).toHaveLength(8)

    fireEvent.click(rows[2])
    expect(rows[2].getAttribute('aria-pressed')).toBe('true')
    expect(sectors().find((el) => el.getAttribute('data-sector') === '2')?.getAttribute('fill'))
      .toBe('#B9665E')

    fireEvent.click(rows[2])       // 再点同一行 ⇒ 取消（`onPick(on ? null : i)`）
    expect(sectors().find((el) => el.getAttribute('data-sector') === '2')?.getAttribute('fill'))
      .toBe('#7C9885')

    const hit = document.querySelector('[data-sector-hit="5"]')
    expect(hit, '命中层不在 ⇒ 反向通道无从点起').not.toBeNull()
    fireEvent.click(hit!)
    expect(rows[5].getAttribute('aria-pressed')).toBe('true')
  })

  it('那句口径整页只许出现一次；图例副句不许沾"评分"二字', async () => {
    await openStage()
    const text = document.body.textContent ?? ''
    // 唯一出口 livingCircle.ts:2399（在条形卡里）。两个措辞变体各自计数 ——
    // `LcMap.tsx:383` 那颗开关的 title 是「只诊断，不参与评分」，不含"综合"二字，
    // 只钉一个变体会漏掉它。
    expect((text.match(/不参与综合评分/g) ?? []).length).toBe(1)
    expect((text.match(/只诊断，不参与评分/g) ?? []).length,
      '右上角那颗开关属于报告页第三屏，体检台不该长出同名 title').toBe(0)
    expect(screen.getByText(LABEL).textContent).not.toContain('评分')
  })
})

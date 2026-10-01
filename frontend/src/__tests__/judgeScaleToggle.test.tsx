// @vitest-environment jsdom
/**
 * C1/C6 · 「判定尺」开关与那句口径的**接线**测试。
 *
 * 为什么值得单独一支：这两样是"没有尺就不出现"的条件渲染 —— 接线写错有两种坏法，
 * 都不会被单元层发现：① 条件永远为真 ⇒ 演示态摆一个勾不动的复选框（假入口）；
 * ② 半径从别处取 ⇒ 换档后文案还写着 1km。所以两头各测一次：无盲区时**不在**，
 * 注入一处带 800m 尺的盲区后**在**、且文案里那个数来自盲区自己。
 *
 * ⚠️ 这支只证明"页面把开关和文案接上了"。地图上的那一圈（C2）与"勾开后仍可拖中心点、
 * 点空白关卡"（`enableClicking:false` 至今无真机 spike）**不在这里销账** —— 那要真机点一次。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import kailiFixture from '../mocks/fixtures/livingCircle/kaili.json'
import ledgerContract from '../__tests__/fixtures/cellsLedgerContract.json'
import { useDataModeStore } from '../store/dataModeStore'
import type { CellsLedgerRaw, LivingCircleReport } from '../types'

const LEDGER_SAMPLE = ledgerContract.sample as unknown as CellsLedgerRaw

const KAILI = kailiFixture as unknown as LivingCircleReport

/** 演示态注入用的假盲区：半径故意取 800（不是常量 1000），用来证明文案里的数有来源。 */
const RULER_M = 800
const fakeBlind = (): LivingCircleReport['blindspots'] => {
  const [lng, lat] = KAILI.scene.center
  const ring = [[lng - 0.002, lat - 0.002], [lng + 0.002, lat - 0.002],
    [lng + 0.002, lat + 0.002], [lng - 0.002, lat + 0.002], [lng - 0.002, lat - 0.002]]
    .map(([a, b]) => [a, b])
  return [{
    id: 'bs-接线-1',
    center: [lng, lat],
    radius_m: RULER_M,
    missing_facilities: ['primary'],
    nearest: [{ facility: 'primary', name: '某小学', distance_m: 1155, direction: '东北' }],
    polygon: { type: 'Polygon', coordinates: [ring] },
    severity: 'light',
  }] as unknown as LivingCircleReport['blindspots']
}

const state = vi.hoisted(() => ({ withBlind: false, withLedger: false }))

vi.mock('../mocks/livingCircleMock', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../mocks/livingCircleMock')>()
  return {
    ...mod,
    getLifeCircleMock: (id: string) => {
      const base = mod.getLifeCircleMock(id)
      if (!base) return base
      let out = base
      if (state.withBlind) out = { ...out, blindspots: fakeBlind() }
      if (state.withLedger) {
        out = {
          ...out,
          caliber: { ...out.caliber!, cells_ledger: LEDGER_SAMPLE },
          // 台账的格阵中心必须与这份报告的 scene.center 同点，否则 `cellAt` 会算到别的格
          scene: { ...out.scene, center: LEDGER_SAMPLE.center },
        }
      }
      return out
    },
  }
})

// mock 必须在 vi.mock 之后 import（hoisting 已把上面的工厂提到最前）
const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')

beforeEach(() => {
  cleanup()
  useDataModeStore.setState({ mode: 'fixture' })
  state.withBlind = false
  state.withLedger = false
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

describe('判定尺开关（C1）与那句口径（C6）', () => {
  it('演示态出厂件（两城实测盲区都是 0）⇒ 开关与那句话都不出现', () => {
    expect(KAILI.blindspots).toHaveLength(0)   // 夹具前提，漂了本用例就白测
    renderScene('kaili')
    expect(screen.queryByText('判定尺（判一格用多大）')).toBeNull()
  })

  it('有一处盲区 ⇒ 开关出现，且半径取自盲区自己声明的那把尺（不是写死的 1km）', () => {
    state.withBlind = true
    renderScene('kaili')
    const label = screen.getByText('判定尺（判一格用多大）')
    expect(label).not.toBeNull()
    const sentence = screen.getByText(/判盲问的是/)
    expect(sentence.textContent).toContain(`${RULER_M}m`)
    expect(sentence.textContent).not.toContain('1000m')
    expect(sentence.textContent).toContain('不是眼前这一小块')
  })

  it('默认关着，勾上才把开关翻起来（受控组件，不是一勾就自嗨的静态块）', () => {
    state.withBlind = true
    renderScene('kaili')
    // 复选框的可及名包含嵌套的那句说明（label 包着 input），所以按 role + 正则取。
    const box = screen.getByRole('checkbox', { name: /判定尺/ }) as HTMLInputElement
    expect(box.checked).toBe(false)
    fireEvent.click(box)
    expect(box.checked).toBe(true)
    fireEvent.click(box)
    expect(box.checked).toBe(false)
  })
})

describe('逐格台账卡（C4）在页面里的出现条件', () => {
  it('出厂演示快照没有台账（`ev-2` 之前冻结）⇒ 整张卡不出现，也不留空壳', () => {
    state.withBlind = true      // 就算有盲区、开关能出现，没台账仍然不该有这张卡
    renderScene('kaili')
    expect(screen.queryByText('逐格台账')).toBeNull()
    expect(screen.getByText('判定尺（判一格用多大）')).not.toBeNull()
  })

  it('报告带台账 ⇒ 卡出现，格阵画出 n×n 个格子并给出五档计数', () => {
    state.withLedger = true
    renderScene('kaili')
    expect(screen.getByText('逐格台账')).not.toBeNull()
    expect(document.querySelectorAll('rect[data-cell]').length).toBe(LEDGER_SAMPLE.n ** 2)
    expect(screen.getByText('判盲 1')).toBeTruthy()
    expect(screen.getByText('未定 1')).toBeTruthy()
  })

  it('点卡里一格 ⇒ 选中态上屏（读数区出现该格的三类依据），再点一次清掉', () => {
    state.withLedger = true
    renderScene('kaili')
    fireEvent.click(document.querySelector('rect[data-cell="1-1"]')!)
    expect(screen.getByText('格 (1,1) · 相对中心 (0, 0)m')).toBeTruthy()
    fireEvent.click(document.querySelector('rect[data-cell="1-1"]')!)
    expect(screen.queryByText('格 (1,1) · 相对中心 (0, 0)m')).toBeNull()
  })
})

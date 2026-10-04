// @vitest-environment jsdom
/**
 * L-INV-3 / L-CT-2 · 逐格台账卡的 `foldable` 两态（计划 B-v1 的 TC-16）。
 *
 * ## 为什么必须有这支
 *
 * 右栏改成内部滚动后，这张 15×15 格阵 + 五档计数 + 读数区是右栏里最高的一块，
 * 于是 `CellsLedgerCard` 新增了 `foldable`（出厂折进 `<details>`）。
 * 既有 `cellsLedgerCard.test.tsx` 只跑过**平铺面**：折叠面一条断言都没有。
 *
 * 真正容易悄悄坏的是两件事：
 *  ① 折叠**不能把格阵从 DOM 里摘掉** —— `judgeScaleToggle.test.tsx` 那条
 *     `rect[data-cell]` 数量 == n² 的判据靠的就是"格阵始终在场"，
 *     折叠若改成条件渲染，那条判据会静默空过（数到 0 个格还以为通过）。
 *  ② 折叠面是新分支，**平铺面是既有消费方的现状形状**（报告页等）；
 *     平铺面一旦跟着换壳，就是被动改了别人的像素。
 *
 * ## 效力上限
 *
 * `<details>` 的开合是浏览器行为，本文件用 `open` 属性与点击 summary 验证；
 * 「折叠后这张卡矮了多少」是排版问题，jsdom 无排版引擎，答不了（见 TC-21）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import CellsLedgerCard from '../components/lifecircle/CellsLedgerCard'
import contract from '../__tests__/fixtures/cellsLedgerContract.json'
import { cellVerdict } from '../lib/livingCircle'
import type { CellsLedgerRaw, LivingCircleReport } from '../types'

const LED = contract.sample as unknown as CellsLedgerRaw
const host = { caliber: { cells_ledger: LED } } as unknown as LivingCircleReport
const verdictAt = (i: number, j: number) => cellVerdict(host, [i, j])

/** 平铺面的形状串（逐字抄自 `CellsLedgerCard.tsx` 未加 foldable 时的那一行）。
 *  钉它是为了让「换壳顺带改了别人的像素」当场变红。 */
const PLAIN_FACE = 'rounded-card border border-line bg-card p-4 shadow-card'

function renderFoldable(onPick = vi.fn(), selected: [number, number] | null = null) {
  const view = render(
    <CellsLedgerCard foldable led={LED} verdictAt={verdictAt} selected={selected} onPick={onPick} />,
  )
  return { ...view, onPick }
}

afterEach(cleanup)   // 不关上一支的 DOM，`document.querySelector` 会摸到旧卡

describe('逐格台账卡 · foldable 两态', () => {
  it('出厂是折上的，但格阵 n² 个格子仍在 DOM 里（折叠≠卸载）', () => {
    renderFoldable()
    const box = document.querySelector('details')
    expect(box).not.toBeNull()
    expect((box as HTMLDetailsElement).open).toBe(false)
    expect(screen.getByText('逐格台账')).toBeTruthy()
    expect(document.querySelectorAll('rect[data-cell]').length).toBe(LED.n ** 2)
  })

  it('点标题展开 ⇒ 读数照旧：点一格回调带的是那一格的 (行,列)', () => {
    const { onPick } = renderFoldable()
    const summary = document.querySelector('details > summary') as HTMLElement
    expect(summary).not.toBeNull()
    fireEvent.click(summary)
    expect((document.querySelector('details') as HTMLDetailsElement).open).toBe(true)

    fireEvent.click(document.querySelector('rect[data-cell="1-1"]')!)
    expect(onPick).toHaveBeenCalledWith([1, 1])
  })

  it('展开态里五档计数与读数链仍然通（折叠不该把语义一起藏掉）', () => {
    // 卡片是**受控**的：点格只回调，读数由父层把 selected 传回来才出现。
    // 所以这一支用 selected=[1,0]（那格里小学"没查全"）来验展开态的读数面。
    const { onPick } = renderFoldable(vi.fn(), [1, 0])
    fireEvent.click(document.querySelector('details > summary') as HTMLElement)
    expect(screen.getByText('判盲 1')).toBeTruthy()
    expect(screen.getByText('封顶 1')).toBeTruthy()
    // 精确匹配：那句解释文案里也写着「无从知道」，用正则 would 命中两处。
    expect(screen.getByText('无从知道')).toBeTruthy()

    fireEvent.click(document.querySelector('rect[data-cell="1-1"]')!)
    expect(onPick).toHaveBeenCalledWith([1, 1])
  })

  it('未传 foldable 的消费方维持平铺面：不是 details，形状串逐字不变', () => {
    const { container } = render(
      <CellsLedgerCard led={LED} verdictAt={verdictAt} selected={null} onPick={vi.fn()} />,
    )
    expect(container.querySelector('details')).toBeNull()
    expect((container.firstElementChild as HTMLElement).className).toBe(PLAIN_FACE)
    expect(document.querySelectorAll('rect[data-cell]').length).toBe(LED.n ** 2)
  })
})

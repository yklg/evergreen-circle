// @vitest-environment jsdom
/**
 * C4 · 逐格台账卡。用**契约夹具那份 3×3 样本** + 真实的 `cellVerdict` 解码器一起跑，
 * 所以这支同时覆盖"卡片画得对不对"和"卡片有没有偷偷重算判定"。
 *
 * 断言盯的是三件容易悄悄坏的事：
 *  ① 五档计数与夹具声明的一致（合并任何一档都会让总数对得上、语义却说假话）；
 *  ② 点一格回调带的是**那个格子**的 `(行,列)`，不是索引算反的 `(列,行)`；
 *  ③ 「无从知道」必须原样上屏成"无从知道"，不许被渲染成"没有"。
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

/** 格子的认法用 `data-cell="行-列"` 显式取，不按 rect 出现顺序反推 ——
 *  SVG 里行 0 画在最南边（y 翻转），按序号推会把 (行,列) 数反。 */
function renderCard(onPick = vi.fn(), selected: [number, number] | null = null) {
  const view = render(
    <CellsLedgerCard led={LED} verdictAt={verdictAt} selected={selected} onPick={onPick} />,
  )
  return { ...view, onPick }
}

afterEach(cleanup)   // 不关上一支的 DOM，`document.querySelector` 会摸到旧卡（本文件第一版就栽在这）

describe('逐格台账卡', () => {
  it('五档各占多少格，与夹具声明的逐格结论对得上（不合并、不吞）', () => {
    renderCard()
    const tally: Record<string, number> = {}
    for (let i = 0; i < LED.n; i += 1) {
      for (let j = 0; j < LED.n; j += 1) {
        const v = verdictAt(i, j)!.verdict
        tally[v] = (tally[v] ?? 0) + 1
      }
    }
    expect(tally).toEqual({ outside: 4, clear: 2, blind: 1, unknown: 1, capped: 1 })
    // 图例只报四档（outside 不上色也不进图例：可达区外画出来会被读成"这里没问题"）
    expect(screen.getByText('判盲 1')).toBeTruthy()
    expect(screen.getByText('不盲 2')).toBeTruthy()
    expect(screen.getByText('未定 1')).toBeTruthy()
    expect(screen.getByText('封顶 1')).toBeTruthy()
  })

  it('点一格 ⇒ 回调带的是这一格的 (行,列)，且读数区说出它的依据', () => {
    const { onPick } = renderCard()
    const target = document.querySelector('rect[data-cell="1-1"]')!
    fireEvent.click(target)
    expect(onPick).toHaveBeenCalledWith([1, 1])
  })

  it('再点同一格 ⇒ 取消选中（格阵是唯一入口时，"再点一次关掉"比另找一个关闭键顺手）', () => {
    const { onPick } = renderCard(vi.fn(), [1, 1])
    fireEvent.click(document.querySelector('rect[data-cell="1-1"]')!)
    expect(onPick).toHaveBeenCalledWith(null)
  })

  it('选中判盲格 (1,1) ⇒ 菜市场写「没有 + 1180m」，小学写「命中 + 420m」', () => {
    renderCard(vi.fn(), [1, 1])
    expect(screen.getByText('格 (1,1) · 相对中心 (0, 0)m')).toBeTruthy()
    expect(screen.getByText('判盲（至少一类有据且 1km 内确实没有）')).toBeTruthy()
    const rows = Array.from(document.querySelectorAll('tbody tr'))
    const text = rows.map((r) => r.textContent)
    expect(text.some((t) => t!.includes('菜市场') && t!.includes('没有') && t!.includes('1180m'))).toBe(true)
    expect(text.some((t) => t!.includes('小学') && t!.includes('命中') && t!.includes('420m'))).toBe(true)
  })

  it('选中未定格 (1,0) ⇒ 小学那一行是「无从知道」，**不是**「没有」', () => {
    renderCard(vi.fn(), [1, 0])
    expect(screen.getByText('未定（有类没查全 —— 我们的取证缺口）')).toBeTruthy()
    const primaryRow = Array.from(document.querySelectorAll('tbody tr'))
      .find((r) => r.textContent?.includes('小学'))!
    expect(primaryRow.textContent).toContain('无从知道')
    expect(primaryRow.textContent).not.toContain('没有')
    expect(primaryRow.textContent).toContain('—')      // 没有距离可报，不编一个数
  })

  it('「未定」与「封顶」两句话不合并 —— 一个是我们的缺口，一个是接口的天花板', () => {
    renderCard(vi.fn(), [1, 2])
    expect(screen.getByText('判不动（接口能力封顶）')).toBeTruthy()
    renderCard(vi.fn(), [1, 0])
    expect(screen.getByText('未定（有类没查全 —— 我们的取证缺口）')).toBeTruthy()
  })

  it('卡片正文里没有原样上屏的 markdown 星号', () => {
    // 真机第一轮抓到：那句「**不是**"确认没有"」把星号直接画到了页面上。
    // JSX 字符串不解析 markdown ⇒ 这类漏字只能靠扫渲染结果发现，不能靠读源码。
    const { container } = renderCard(vi.fn(), [1, 1])
    expect(container.textContent ?? '').not.toMatch(/\*\*/)
  })
})

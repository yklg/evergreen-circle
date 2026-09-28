// @vitest-environment jsdom
/**
 * 生活圈统计带的 DOM 形状判据（计划 v9 步骤 3 的**前置**，不是事后补的装饰）
 *
 * 为什么先钉再改：`RecordStatsStrip` 只有一个消费方（`pages/reports/LivingCircleView.tsx:53`），
 * 全仓没有任何一条断言碰过它的 DOM（`recordIndex.test.ts` 钉的是 `recordStats` 的**值**）。
 * 而步骤 3 要把它的私有 `StatBlock` 换成共享件 `VStatCard` —— 没有这条判据，
 * "视觉不变"就只剩肉眼看图，等于没承诺（架构评审 v9 风险 4）。
 *
 * 判据落在**逐条 class 串**上：换件后若共享件把 `p-4` 撑成 `p-6`、或把单位 span 的
 * 条件渲染改了形状，这里立刻红。**本文件在换件之前就必须是绿的**（钉的是现状形状）。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import RecordStatsStrip from '../components/RecordStatsStrip'
import type { RecordStats } from '../lib/recordIndex'

const STATS: RecordStats = { total: 12, visibleLcTotal: 15, latestScore: 88, avg: 79, blindspots: 34 }

/* 现状四格共用的形状串（逐字抄自 RecordStatsStrip.tsx:32-40） */
const TILE = 'rounded-card border border-line/60 bg-card p-4 shadow-card'
const ICON_BASE = 'grid h-8 w-8 place-items-center rounded-btn bg-primary-tint'
const NUM_ROW = 'mt-2.5 flex items-end gap-0.5'
const NUM = 'font-serif text-[26px] leading-none text-ink'
const UNIT = 'mb-0.5 text-aux text-ink-2'
const LABEL = 'mt-1 text-tag font-medium text-ink-2'
const GRID = 'mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4'

interface Expect {
  value: number
  unit: string
  label: string
  tip: string
  color: string
}

const CELLS: Expect[] = [
  {
    value: 12,
    unit: '次',
    label: '体检总数',
    tip: '归档可见 15 份生活圈记录中，有可比评分的 12 份',
    color: 'text-ok',
  },
  {
    value: 88,
    unit: '分',
    label: '最近一次评分',
    tip: '最新一轮体检的综合评分',
    color: 'text-primary',
  },
  {
    value: 79,
    unit: '分',
    label: '平均评分',
    tip: '全部可比体检综合得分的平均值（离线估算不参与）',
    color: 'text-ok',
  },
  {
    value: 34,
    unit: '处',
    label: '累计盲区',
    tip: '历次识别服务盲区的总量（可能重复计数）',
    color: 'text-warn',
  },
]

function renderTiles(): HTMLElement[] {
  const { container } = render(<RecordStatsStrip stats={STATS} />)
  const grid = container.firstElementChild as HTMLElement
  expect(grid.className).toBe(GRID)
  const tiles = [...grid.children] as HTMLElement[]
  // 宁可红，不空转：读不到 4 格说明选择器或结构变了，下面的逐条比对就全是空过
  expect(tiles).toHaveLength(4)
  return tiles
}

describe('生活圈统计带 · 形状与口径', () => {
  it('四格的面、图标面、数字行、标签行 class 逐条不变', () => {
    const tiles = renderTiles()
    tiles.forEach((tile, i) => {
      const want = CELLS[i]
      expect(tile.className, `第 ${i + 1} 格的外层面变了`).toBe(TILE)
      expect(tile.getAttribute('title'), `第 ${i + 1} 格的口径说明丢了`).toBe(want.tip)

      const icon = tile.children[0] as HTMLElement
      expect(icon.className).toBe(`${ICON_BASE} ${want.color}`)
      expect(icon.querySelector('svg'), `第 ${i + 1} 格丢了图标`).toBeTruthy()

      const row = tile.children[1] as HTMLElement
      expect(row.className).toBe(NUM_ROW)
      expect((row.children[0] as HTMLElement).className).toBe(NUM)
      expect(row.children[0].textContent).toBe(String(want.value))
      expect((row.children[1] as HTMLElement).className).toBe(UNIT)
      expect(row.children[1].textContent).toBe(want.unit)

      const label = tile.children[2] as HTMLElement
      expect(label.className).toBe(LABEL)
      expect(label.textContent).toBe(want.label)
    })
  })

  it('数字是静态值（统计带不参与滚动动画，动画中的数字不可断言）', () => {
    const tiles = renderTiles()
    const numbers = tiles.map((t) => (t.children[1].children[0] as HTMLElement).textContent)
    expect(numbers).toEqual(['12', '88', '79', '34'])
  })
})

// @vitest-environment jsdom
/**
 * 舆情面板逐景点口碑分布（TC-P03 前端位 / M2c）
 *
 * 守护契约：
 *   SS-1 by_spot 渲染逐景点口碑行：data-spot-id 直引冻结实体、样本量如实标注
 *   SS-2 旧报告无 by_spot 键 → 面板正常渲染且不崩（读兼容）
 *   SS-3 by_spot 为空数组 → 不出现「逐景点口碑分布」标题（不造空区块）
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { VSentimentPanel } from '../components/VSentimentPanel'
import type { SentimentResult } from '../types'

afterEach(() => cleanup())

const BASE: SentimentResult = {
  overall: { pos: 50, neu: 0, neg: 50 },
  by_platform: {
    douyin: { pos: 1, neu: 0, neg: 0 },
    xiaohongshu: { pos: 0, neu: 0, neg: 1 },
  },
  timeline: [],
  camps: [],
  sample_size: 2,
}

const WITH_SPOT: SentimentResult = {
  ...BASE,
  by_spot: [
    { spot_id: '大理_spot_1', spot_name: '大理古城', sample: 12, pos: 60, neu: 20, neg: 20, by_platform: { douyin: 7, xiaohongshu: 5 } },
    { spot_id: '大理_spot_2', spot_name: '洱海廊道', sample: 5, pos: 40, neu: 20, neg: 40, by_platform: { douyin: 5 } },
  ],
}

describe('VSentimentPanel 逐景点口碑分布', () => {
  it('SS-1：by_spot 行挂 data-spot-id，展示景点名与样本量', () => {
    const { container } = render(<VSentimentPanel sentiment={WITH_SPOT} />)
    expect(screen.getByText('逐景点口碑分布')).toBeTruthy()
    const rows = container.querySelectorAll('[data-spot-id]')
    expect(rows).toHaveLength(2)
    expect(rows[0].getAttribute('data-spot-id')).toBe('大理_spot_1')
    expect(screen.getByText('大理古城')).toBeTruthy()
    expect(screen.getByText('12 条')).toBeTruthy()
    expect(screen.getByText('5 条')).toBeTruthy()
  })

  it('SS-2：旧报告缺 by_spot 键 → 面板照常渲染不崩', () => {
    render(<VSentimentPanel sentiment={BASE} />)
    expect(screen.getByText('整体情感倾向')).toBeTruthy()
    expect(screen.queryByText('逐景点口碑分布')).toBeNull()
  })

  it('SS-3：by_spot 为空数组 → 不渲染空区块', () => {
    render(<VSentimentPanel sentiment={{ ...BASE, by_spot: [] }} />)
    expect(screen.queryByText('逐景点口碑分布')).toBeNull()
  })
})

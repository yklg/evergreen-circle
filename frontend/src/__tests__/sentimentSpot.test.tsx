// @vitest-environment jsdom
/**
 * 舆情面板逐景点口碑分布（TC-P03 前端位 / M2c）
 *
 * 守护契约：
 *   SS-1 by_spot 渲染逐景点口碑行：data-spot-id 直引冻结实体、样本量如实标注
 *   SS-2 旧报告无 by_spot 键 → 面板正常渲染且不崩（读兼容）
 *   SS-3 by_spot 为空数组 → 不出现「逐景点口碑分布」标题（不造空区块）
 *   口径呈现 → 可核验口碑与检索语料双数展示；low_sample 时情感降级为计数、
 *             阵营占比挂「方向性参考」限定语；存量报告缺新键时退回今天那句文案
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

/* ── 口径呈现（词云口碑化修复 步骤 8）：双数展示 + 小样本只报计数 ── */

const CALIBER: SentimentResult = {
  ...BASE,
  overall: { pos: 57, neu: 43, neg: 0 },
  overall_count: { pos: 4, neu: 3, neg: 0 },
  sample_size: 7,
  corpus_size: 25,
  doc_kind_counts: { review: 7, ticket_faq: 5, seo: 5, flight: 3, guide: 3, news: 1, chrome: 1 },
  low_sample: true,
}

describe('VSentimentPanel 舆情口径呈现', () => {
  it('双数展示：可核验口碑与检索语料同时可见（只报一个数就会被误读）', () => {
    render(<VSentimentPanel sentiment={CALIBER} />)
    expect(screen.getByText(/基于 7 条可核验用户口碑/)).toBeTruthy()
    expect(screen.getByText(/检索到 25 条相关内容/)).toBeTruthy()
  })

  it('low_sample ⇒ 情感呈现降级为计数，不出现百分比读数', () => {
    render(<VSentimentPanel sentiment={CALIBER} />)
    expect(screen.getByText('正面 4 · 中性 3 · 负面 0 条（样本有限，只报计数）')).toBeTruthy()
    expect(screen.queryByText(/正面 \d+%/)).toBeNull()
  })

  it('样本充足时仍按占比呈现（降级不是永久化）', () => {
    render(<VSentimentPanel sentiment={{ ...CALIBER, low_sample: false }} />)
    expect(screen.getByText(/正面 57% · 中性 43% · 负面 0%/)).toBeTruthy()
    expect(screen.queryByText(/只报计数/)).toBeNull()
  })

  it('存量报告缺 corpus_size/low_sample → 退回今天那句文案，不显新口径', () => {
    render(<VSentimentPanel sentiment={BASE} />)
    expect(screen.getByText('基于 2 条可核验用户口碑（抖音优先采集）')).toBeTruthy()
    expect(screen.queryByText(/检索到 \d+ 条相关内容/)).toBeNull()
    expect(screen.getByText(/正面 50%/)).toBeTruthy()
  })

  it('观点阵营占比：小样本时挂「方向性参考」限定语，占比数字本身不销毁', () => {
    const withCamps = {
      ...CALIBER,
      camps: [{ title: '风景党', ratio: 57, summary: '夸风景', quotes: [] }],
    } as unknown as SentimentResult
    const { unmount } = render(<VSentimentPanel sentiment={withCamps} />)
    expect(screen.getByText('样本有限，占比为方向性参考')).toBeTruthy()
    expect(screen.getByText('57%')).toBeTruthy()
    unmount()
    render(<VSentimentPanel sentiment={{ ...withCamps, low_sample: false }} />)
    expect(screen.queryByText('样本有限，占比为方向性参考')).toBeNull()
  })
})

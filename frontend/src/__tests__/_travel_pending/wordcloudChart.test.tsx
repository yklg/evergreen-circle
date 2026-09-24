// @vitest-environment jsdom
/**
 * 词云 DOM 渲染通道（E1 / rugged-lagoon-merlin W-F1~F6）
 *
 * 守护契约：
 *   W-F1 type=wordcloud 走 VWordCloud 纯 DOM 渲染（不再交给 ECharts）
 *   W-F3 双形状同渲：新 words 载荷与旧 option.series[0].data(name/value)
 *        渲染出相同词集与相同字号排序（存量旧报告读时兼容的前端位）
 *   W-F4 注册表分流：bar 等默认 → echarts 包装；wordcloud → DOM；未知 type → echarts 兜底
 *   W-F5 空词表 → 「暂无评论样本」占位，无白框
 *   W-F6 消费面 smoke：舆情面板 / 简报入口的 wordcloud 分流（四消费面代表位）
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

// echarts 真身不测：桩件记录收到的 option，断言分流契约（wordcloud 不得出现在这里）。
const seen = vi.hoisted(() => [] as any[])
vi.mock('echarts-for-react', () => ({
  default: ({ option }: any) => {
    seen.push(option)
    return <div data-testid="echarts" data-series={option?.series?.[0]?.type ?? ''} />
  },
}))

import { VChart } from '../components/VChart'
import { VSentimentPanel } from '../components/VSentimentPanel'
import ReportBriefView from '../components/ReportBriefView'
import type { ChartSpec, SentimentResult } from '../types'

afterEach(() => {
  cleanup()
  seen.length = 0
})

const WORDS = [
  { word: '古城', weight: 5 },
  { word: '洱海', weight: 9 },
  { word: '民宿', weight: 2 },
]

const CLOUD_NEW: ChartSpec = {
  chart_id: 'ch_1',
  type: 'wordcloud',
  title: '全网口碑热词词云',
  words: WORDS,
  evidence_ids: [],
}

// 旧契约形状（存量报告快照）：无 words，只有 echarts option。
const CLOUD_LEGACY: ChartSpec = {
  chart_id: 'ch_1_legacy',
  type: 'wordcloud',
  title: '全网口碑热词词云',
  option: {
    title: { text: '全网口碑热词词云' },
    series: [{ type: 'wordcloud', data: WORDS.map((w) => ({ name: w.word, value: w.weight })) }],
  },
  evidence_ids: [],
}

const BAR: ChartSpec = {
  chart_id: 'ch_2',
  type: 'bar',
  title: '对比柱图',
  option: { series: [{ type: 'bar', data: [1, 2] }] },
  evidence_ids: [],
}

function cloudWords(): string[] {
  return [...screen.getByTestId('wordcloud-dom').querySelectorAll('span')].map((s) => s.textContent ?? '')
}

function cloudFontSizes(): number[] {
  return [...screen.getByTestId('wordcloud-dom').querySelectorAll('span')].map(
    (s) => Number.parseFloat((s as HTMLElement).style.fontSize),
  )
}

describe('VChart wordcloud 通道（E1）', () => {
  it('W-F1：wordcloud 走 DOM 渲染，不经过 echarts 包装', () => {
    render(<VChart spec={CLOUD_NEW} />)
    expect(screen.getByTestId('wordcloud-dom')).toBeTruthy()
    expect(screen.queryByTestId('echarts')).toBeNull()
    expect(seen.length).toBe(0)
    expect(screen.getByText('全网口碑热词词云')).toBeTruthy() // 卡片壳仍在 VChart
  })

  it('W-F3：双形状同渲——新 words 与旧 option 形状词集/字号排序一致', () => {
    const { unmount } = render(<VChart spec={CLOUD_NEW} />)
    const newWords = cloudWords()
    const newSizes = cloudFontSizes()
    unmount()

    render(<VChart spec={CLOUD_LEGACY} />)
    expect(cloudWords()).toEqual(newWords)
    expect(cloudFontSizes()).toEqual(newSizes)
    // 权重降序：洱海(9) > 古城(5) > 民宿(2)，字号严格递减
    expect(newWords).toEqual(['洱海', '古城', '民宿'])
    expect(newSizes[0]).toBeGreaterThan(newSizes[1])
    expect(newSizes[1]).toBeGreaterThan(newSizes[2])
  })

  it('W-F4：注册表分流——bar 走 echarts、未知 type 兜底 echarts、wordcloud 走 DOM', () => {
    const { unmount } = render(<VChart spec={BAR} />)
    expect(screen.getByTestId('echarts')).toBeTruthy()
    expect(seen[0]).toBe(BAR.option)
    unmount()

    render(<VChart spec={{ ...BAR, chart_id: 'ch_x', type: 'mystery_chart' }} />)
    expect(screen.getByTestId('echarts')).toBeTruthy()
    unmount()

    render(<VChart spec={CLOUD_NEW} />)
    expect(screen.getByTestId('wordcloud-dom')).toBeTruthy()
  })

  it('W-F5：空 words / 旧形状空 data → 占位文案，无白框不崩', () => {
    const { unmount } = render(
      <VChart spec={{ ...CLOUD_NEW, words: [] }} />,
    )
    expect(screen.getByText(/暂无评论样本/)).toBeTruthy()
    expect(screen.queryByTestId('wordcloud-dom')).toBeNull()
    unmount()

    render(
      <VChart
        spec={{ ...CLOUD_LEGACY, option: { series: [{ type: 'wordcloud', data: [] }] } }}
      />,
    )
    expect(screen.getByText(/暂无评论样本/)).toBeTruthy()
  })

  it('W-F6：舆情面板 / 简报入口的 wordcloud 分流 smoke', () => {
    const sentiment = {
      overall: { pos: 3, neu: 1, neg: 1 },
      by_platform: {},
      by_spot: [],
      camps: [],
      voices: [],
      highlights: [],
      sample_size: 5,
    } as unknown as SentimentResult

    const { unmount } = render(<VSentimentPanel sentiment={sentiment} charts={[CLOUD_NEW, BAR]} />)
    expect(screen.getByTestId('wordcloud-dom')).toBeTruthy()
    expect(screen.getByTestId('echarts')).toBeTruthy() // 同面板内 bar 仍走 echarts
    unmount()

    const report = {
      id: 'r_w6',
      title: '简报 smoke',
      sections: [{ id: 'sentiment_report', title: '舆情', charts: [CLOUD_NEW] }],
      brief: { summary: '一句话', judgments: [], key_data: [], actions: [] },
    } as never
    render(<ReportBriefView report={report} />)
    expect(screen.getByTestId('wordcloud-dom')).toBeTruthy()
    expect(screen.queryByTestId('echarts')).toBeNull()
  })
})


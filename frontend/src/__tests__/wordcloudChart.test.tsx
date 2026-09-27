// @vitest-environment jsdom
/**
 * 词云 DOM 渲染通道（E1 / rugged-lagoon-merlin W-F1~F6）
 *
 * 守护契约：
 *   W-F1 type=wordcloud 走 VWordCloud 纯 DOM 渲染（不再交给 ECharts）
 *   W-F3 三形状同渲：裸 words / 带 kind words / 旧 option.series[0].data(name/value)
 *        —— 后两者字号与配色与今天逐位一致（存量旧报告读时兼容的前端位）
 *   W-F4 注册表分流：bar 等默认 → echarts 包装；wordcloud → DOM；未知 type → echarts 兜底
 *   W-F5 空词表 → 「暂无可核验口碑样本」占位，无白框；且文案不承诺不存在的 cookie 开关
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
import { wordStyle } from '../lib/wordcloudColors'
import ReportBriefView from '../components/ReportBriefView'
import backendColors from './fixtures/backendChartColors.json'
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

/* ── 分层渲染与存量兼容（词云口碑化修复 步骤 6/7 · TC-23 / TC-24）── */

const LAYERED_WORDS = [
  { word: '大理', weight: 7, kind: 'topic', polarity: 'neu' },
  { word: '清净', weight: 2, kind: 'opinion', polarity: 'pos' },
  { word: '宰客', weight: 1, kind: 'opinion', polarity: 'neg' },
] as unknown as ChartSpec['words']

function spans(): HTMLElement[] {
  return [...screen.getByTestId('wordcloud-dom').querySelectorAll('span')] as HTMLElement[]
}

function byWord(word: string): HTMLElement {
  const hit = spans().find((s) => s.textContent === word)
  if (!hit) throw new Error(`词云未渲染出「${word}」`)
  return hit
}

describe('词云分层渲染（评价词大字着色 · 话题词小灰字）', () => {
  it('TC-23a：三形状归一——裸 words / 带 kind words / 旧 option，后两者与今天同字号同配色', () => {
    const { unmount } = render(<VChart spec={{ ...CLOUD_NEW, words: WORDS }} />)
    const bare = spans().map((s) => `${s.style.fontSize}|${s.style.color}|${s.style.opacity}`)
    unmount()
    render(<VChart spec={CLOUD_LEGACY} />)
    const fromOption = spans().map((s) => `${s.style.fontSize}|${s.style.color}|${s.style.opacity}`)
    expect(fromOption).toEqual(bare)
  })

  it('话题词权重再高也压不动评价词：话题档上限 < 评价档下限', () => {
    render(<VChart spec={{ ...CLOUD_NEW, words: LAYERED_WORDS }} />)
    // 大理 7 次是话题档里唯一成员 ⇒ 退化跨度落该档**下限** 12px（与生产同规则）；
    // 关键不在它具体几 px，而在权重 1 的评价词（宰客 18px）仍然比它大——病灶已反。
    expect(parseFloat(byWord('大理').style.fontSize)).toBe(12)
    expect(parseFloat(byWord('宰客').style.fontSize)).toBe(18)
    expect(parseFloat(byWord('清净').style.fontSize)).toBe(44)
    expect(parseFloat(byWord('大理').style.fontSize))
      .toBeLessThan(parseFloat(byWord('宰客').style.fontSize))
  })

  it('话题层小字 + 55% 透明；评价层不透明', () => {
    render(<VChart spec={{ ...CLOUD_NEW, words: LAYERED_WORDS }} />)
    expect(byWord('大理').style.opacity).toBe('0.55')
    expect(byWord('清净').style.opacity).toBe('1')
  })

  it('TC-24：极性色与后端 charts.SENTIMENT 同步（前端不得自己调色）', () => {
    expect(wordStyle({ word: 'a', weight: 1, kind: 'opinion', polarity: 'pos' }, 0).color)
      .toBe(backendColors.sentiment.pos)
    expect(wordStyle({ word: 'a', weight: 1, kind: 'opinion', polarity: 'neg' }, 0).color)
      .toBe(backendColors.sentiment.neg)
    expect(wordStyle({ word: 'a', weight: 1, kind: 'opinion', polarity: 'neu' }, 0).color)
      .toBe(backendColors.sentiment.neu)
    // 评价词缺 polarity 时按中性着色，而不是退回轮换色环
    expect(wordStyle({ word: 'a', weight: 1, kind: 'opinion' }, 3).color)
      .toBe(backendColors.sentiment.neu)
  })

  it('kind 缺席 ⇒ 仍走 PALETTE 逐词轮换（存量报告视觉不变），且与后端 SERIES 同序', () => {
    WORDS.forEach((w, i) => {
      expect(wordStyle(w, i).color).toBe(backendColors.series[i % backendColors.series.length])
      expect(wordStyle(w, i).opacity).toBe(1)
    })
  })

  it('后端绝不注入缺省 kind：载荷里没有 kind 的词条，前端也不当它是话题词', () => {
    render(<VChart spec={{ ...CLOUD_NEW, words: [{ word: '大理', weight: 9 } as never] }} />)
    const el = byWord('大理')
    // 被当成话题词的话：opacity 0.55、字号 ≤15px。两者都没发生 ⇒ 走的是单档归一 +
    // PALETTE 轮换（今天的渲染路径）。单词条落 14px 是生产的既有退化语义，一并钉住。
    expect(el.style.opacity).toBe('1')
    expect(parseFloat(el.style.fontSize)).toBe(14)
  })
})

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
    expect(screen.getByText(/暂无可核验口碑样本/)).toBeTruthy()
    expect(screen.queryByTestId('wordcloud-dom')).toBeNull()
    unmount()

    render(
      <VChart
        spec={{ ...CLOUD_LEGACY, option: { series: [{ type: 'wordcloud', data: [] }] } }}
      />,
    )
    expect(screen.getByText(/暂无可核验口碑样本/)).toBeTruthy()
  })

  it('W-F5b：占位文案不得承诺不存在的能力（旧文案「可配置平台 cookie 后重跑」是假的）', () => {
    // 全库核查：douyin_cookie/xhs_cookie/bilibili_cookie 无任何消费方，携程在 platforms.py
    // 里标 `""`＝不支持采集。留这句等于把「采不到」推给一个不存在的开关。
    render(<VChart spec={{ ...CLOUD_NEW, words: [] }} />)
    expect(screen.getByText(/暂无可核验口碑样本/).textContent).not.toMatch(/cookie|重跑/)
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


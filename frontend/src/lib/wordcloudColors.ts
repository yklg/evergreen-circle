/**
 * 词云着色解析（与布局分离：布局管几何，本文件管颜色与透明度）。
 *
 * 为什么单独成文：`VWordCloud.tsx` 是组件文件，从它里面 export 函数会让 React Fast Refresh
 * 失效（eslint `react-refresh/only-export-components`）；而这套色值既被组件用、也被取证页与
 * 测试用，必须有一个非组件的落点。
 */
import type { Polarity, WordcloudWord } from '../types'

/** 与后端 charts.SERIES 同序的莫兰迪色环（**仅用于 kind 缺席的存量载荷**，逐词轮换）。 */
const PALETTE = ['#7C9885', '#E0B775', '#8FA8C0', '#CE9A92', '#A8C0A8', '#C2B59B']

/**
 * 与后端 charts.py:17 SENTIMENT 同值（前端无法 import Python，故为手工镜像）。
 * 同步由两侧守卫共同把住：backend `test_frontend_color_mirror_is_in_sync` 守「常量 ↔ fixture」，
 * frontend `wordcloudChart.test.tsx` 守「fixture ↔ 本文件」。
 */
const SENTIMENT_COLOR: Record<Polarity, string> = { pos: '#8AB58A', neu: '#C9CFC9', neg: '#CE9A92' }

/** 话题层灰 = 既有 token `ink-3`（`--verda-ink-3`），不新造色值。 */
const TOPIC_COLOR = '#9AA39C'
const TOPIC_OPACITY = 0.55

/**
 * 着色解析：评价词按极性、话题词固定灰、**kind 缺席时退回 PALETTE 逐词轮换**。
 * 第三条分支不是兜底写法，而是存量契约 —— 老报告的词云必须逐像素不变。
 */
export function wordStyle(word: WordcloudWord, index: number): { color: string; opacity: number } {
  if (word.kind === 'opinion') return { color: SENTIMENT_COLOR[word.polarity ?? 'neu'], opacity: 1 }
  if (word.kind === 'topic') return { color: TOPIC_COLOR, opacity: TOPIC_OPACITY }
  return { color: PALETTE[index % PALETTE.length], opacity: 1 }
}

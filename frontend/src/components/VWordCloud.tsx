import type { ChartSpec, WordcloudWord } from '../types'

// 与后端 charts.SERIES 同序的莫兰迪色环（词云逐词轮换）。
const PALETTE = ['#7C9885', '#E0B775', '#8FA8C0', '#CE9A92', '#A8C0A8', '#C2B59B']

/**
 * 双形状归一（E1 兼容契约）：
 * 新报告携带 spec.words（后端 wordcloud_words 归一）；
 * 存量旧报告只有 echarts option 形状 → 从 series[0].data 的 name/value 映射回来。
 */
function normalizeWords(spec: ChartSpec): WordcloudWord[] {
  if (spec.words && spec.words.length > 0) return spec.words
  const series = (spec.option as { series?: { data?: unknown }[] } | undefined)?.series
  const data = Array.isArray(series) ? series[0]?.data : undefined
  if (!Array.isArray(data)) return []
  return data
    .map((d) => {
      const item = d as { name?: unknown; value?: unknown }
      const word = String(item?.name ?? '').trim()
      return word ? { word, weight: Number(item?.value) || 0 } : null
    })
    .filter((w): w is WordcloudWord => w !== null)
}

/** 权重线性映射字号到 [13, 42]；全同权重取中值，单点不放大。 */
export function wordFontSize(weight: number, min: number, max: number): number {
  if (!(max > min)) return 27
  return 13 + ((weight - min) / (max - min)) * 29
}

/** 纯 DOM/CSS 词云（E1）：权重→字号，色环轮换，flex-wrap 居中铺排。 */
export function VWordCloud({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const words = normalizeWords(spec)
  if (words.length === 0) {
    return (
      <div
        className="grid place-items-center rounded-btn border border-dashed border-line/70 text-aux text-ink-3"
        style={{ height: Math.min(height, 120) }}
      >
        暂无评论样本，可配置平台 cookie 后重跑
      </div>
    )
  }
  const weights = words.map((w) => w.weight)
  const min = Math.min(...weights)
  const max = Math.max(...weights)
  const sorted = [...words].sort((a, b) => b.weight - a.weight)
  return (
    <div
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 overflow-hidden"
      style={{ height }}
      data-testid="wordcloud-dom"
    >
      {sorted.map((w, i) => (
        <span
          key={`${w.word}-${i}`}
          title={`${w.word}：权重 ${w.weight}`}
          style={{
            fontSize: wordFontSize(w.weight, min, max),
            color: PALETTE[i % PALETTE.length],
            lineHeight: 1.15,
          }}
          className="font-medium transition-transform hover:scale-105"
        >
          {w.word}
        </span>
      ))}
    </div>
  )
}

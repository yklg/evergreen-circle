import { useEffect, useRef, useState } from 'react'
import type { ChartSpec, WordcloudWord } from '../types'
import { layoutWords } from '../lib/wordcloudLayout'

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

/** P5 词云散布布局：absolute 定位 + ResizeObserver 测容器宽。 */
export function VWordCloud({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const words = normalizeWords(spec)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerW, setContainerW] = useState(640)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          setContainerW(entry.contentRect.width)
        }
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

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
  const placed = layoutWords(words, containerW, height)
  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden"
      style={{ height }}
      data-testid="wordcloud-dom"
    >
      {placed.map((w, i) => (
        <span
          key={`${w.word}-${i}`}
          title={`${w.word}：权重 ${w.weight}`}
          style={{
            position: 'absolute',
            left: w.x,
            top: w.y,
            fontSize: w.fontSize,
            color: PALETTE[i % PALETTE.length],
            lineHeight: 1.15,
            whiteSpace: 'nowrap',
          }}
          className="font-medium transition-transform hover:scale-105"
        >
          {w.word}
        </span>
      ))}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { ChartSpec, WordcloudWord } from '../types'
import { layoutWords } from '../lib/wordcloudLayout'
import { wordStyle } from '../lib/wordcloudColors'

/**
 * 三形状归一（E1 兼容契约）：
 * ① 新报告 `spec.words`（带 kind/polarity，分层渲染）；
 * ② 本次之前的报告 `spec.words`（裸 {word,weight}，kind 缺席 ⇒ 单层渲染）；
 * ③ 更旧的报告只有 echarts option 形状 → 从 series[0].data 的 name/value 映射回来（同样无 kind）。
 * 三条路径都**不补默认 kind**：给老词云兜一个 "topic" 会把地名全渲染成小灰字，
 * 那是把兼容问题伪装成设计。
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
        暂无可核验口碑样本
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
      {placed.map((w, i) => {
        const { color, opacity } = wordStyle(w, i)
        return (
          <span
            key={`${w.word}-${i}`}
            title={`${w.word}：权重 ${w.weight}${w.kind ? `（${w.kind === 'opinion' ? '评价词' : '话题词'}）` : ''}`}
            style={{
              position: 'absolute',
              left: w.x,
              top: w.y,
              fontSize: w.fontSize,
              color,
              opacity,
              lineHeight: 1.15,
              whiteSpace: 'nowrap',
            }}
            className="font-medium transition-transform hover:scale-105"
          >
            {w.word}
          </span>
        )
      })}
    </div>
  )
}

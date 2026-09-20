import { Quote } from 'lucide-react'

/**
 * 目的地调研（guide/assess/research）扁平的舆情口碑面板。
 *
 * 后端 research 流水线产出结构（与竞品/SentimentResult 无关）：
 *   { topic, positive, neutral, negative, themes: string[], quotes: {evidence_id, text}[] }
 * 命中数为「证据条数」（确定性聚合，非平台样本量），因此不展示旧的
 * 「基于 N 条评论」与各平台分布，只渲染整体倾向条 + 主题词 + 代表原声。
 */
export function VSentimentFlatPanel({
  sentiment,
}: {
  sentiment: {
    topic?: string
    positive?: number
    neutral?: number
    negative?: number
    themes?: string[]
    quotes?: { evidence_id?: string; text?: string }[]
  }
}) {
  const pos = Number(sentiment.positive ?? 0)
  const neu = Number(sentiment.neutral ?? 0)
  const neg = Number(sentiment.negative ?? 0)
  const total = pos + neu + neg || 1
  const pct = (n: number) => Math.round((n / total) * 100)
  const themes = sentiment.themes ?? []
  const quotes = (sentiment.quotes ?? []).filter((q) => (q?.text ?? '').trim())

  if (total <= 0) {
    return <div className="text-tag text-ink-3">暂无可用口碑证据，未生成本节聚合。</div>
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="text-tag text-ink-3">基于 {total} 条口碑证据的确定性舆情聚合（正/中/负计数 + 主题词频 + 代表原声）</div>

      {/* 整体情感条 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-tag text-ink-2">
          <span>整体口碑倾向</span>
          <span>
            正面 {pct(pos)}% · 中性 {pct(neu)}% · 负面 {pct(neg)}%
          </span>
        </div>
        <div className="flex h-3 w-full overflow-hidden rounded-chip">
          <div className="bg-ok" style={{ width: `${pct(pos)}%` }} />
          <div className="bg-ink-3/40" style={{ width: `${pct(neu)}%` }} />
          <div className="bg-risk" style={{ width: `${pct(neg)}%` }} />
        </div>
      </div>

      {/* 主题词频 */}
      {themes.length > 0 && (
        <div>
          <div className="mb-2 text-aux font-semibold text-ink">高频口碑主题</div>
          <div className="flex flex-wrap gap-2">
            {themes.map((t, i) => (
              <span
                key={i}
                className="rounded-chip border border-line/70 bg-card px-3 py-1 text-tag text-ink-2"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 代表原声 */}
      {quotes.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-2 text-aux font-semibold text-ink">
            <Quote size={15} className="text-primary" />
            代表原声 · 取自来源正文
          </div>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {quotes.slice(0, 8).map((q, i) => (
              <div
                key={q.evidence_id ?? i}
                className="rounded-card border border-line/60 bg-bg p-3"
              >
                <p className="text-tag leading-relaxed text-ink-2">“{q.text}”</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
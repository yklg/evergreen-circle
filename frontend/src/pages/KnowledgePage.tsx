import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Library,
  Search,
  Trash2,
  ExternalLink,
  Quote,
  FileText,
  Lightbulb,
  Image as ImageIcon,
  StickyNote,
  Tag as TagIcon,
} from 'lucide-react'
import { useAnnotationStore } from '../store/annotationStore'
import type { KBKind } from '../store/annotationStore'

const KIND_META: Record<KBKind, { label: string; icon: typeof FileText; cls: string }> = {
  claim: { label: '论点', icon: Lightbulb, cls: 'bg-ok/15 text-ok' },
  evidence: { label: '证据', icon: FileText, cls: 'bg-info/15 text-info' },
  quote: { label: '金句', icon: Quote, cls: 'bg-warn/15 text-warn' },
  figure: { label: '配图', icon: ImageIcon, cls: 'bg-primary-tint text-primary-deep' },
  note: { label: '摘录', icon: StickyNote, cls: 'bg-sun-soft text-warn' },
  highlight: { label: '高亮', icon: TagIcon, cls: 'bg-risk/15 text-risk' },
}

export default function KnowledgePage() {
  const navigate = useNavigate()
  const { knowledge, removeFromKB } = useAnnotationStore()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<KBKind | 'all'>('all')

  const filtered = useMemo(() => {
    return knowledge.filter((k) => {
      if (kind !== 'all' && k.kind !== kind) return false
      if (q.trim()) {
        const t = q.toLowerCase()
        return (
          k.content.toLowerCase().includes(t) ||
          k.reportTitle.toLowerCase().includes(t) ||
          k.tags.some((tg) => tg.toLowerCase().includes(t))
        )
      }
      return true
    })
  }, [knowledge, q, kind])

  // 按报告分组
  const grouped = useMemo(() => {
    const map = new Map<string, { title: string; items: typeof filtered }>()
    for (const k of filtered) {
      const g = map.get(k.reportId) ?? { title: k.reportTitle, items: [] }
      g.items.push(k)
      map.set(k.reportId, g)
    }
    return Array.from(map.entries())
  }, [filtered])

  const kindCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const k of knowledge) c[k.kind] = (c[k.kind] ?? 0) + 1
    return c
  }, [knowledge])

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      {/* 头部 */}
      <div className="flex items-center gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-card bg-primary-tint text-primary">
          <Library size={24} strokeWidth={1.8} />
        </span>
        <div>
          <h1 className="font-serif text-h1 text-ink">我的知识库</h1>
          <p className="text-aux text-ink-2">
            从各份调研报告中沉淀的 {knowledge.length} 条洞察 · 每条均可一键溯源回原始出处
          </p>
        </div>
      </div>

      {/* 搜索 + 过滤 */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索知识库内容、报告或标签…"
            className="h-11 w-full rounded-btn border border-line bg-card pl-9 pr-3 text-aux text-ink outline-none focus:border-primary"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <FilterChip active={kind === 'all'} onClick={() => setKind('all')} label={`全部 ${knowledge.length}`} />
          {(Object.keys(KIND_META) as KBKind[]).map((k) =>
            kindCounts[k] ? (
              <FilterChip
                key={k}
                active={kind === k}
                onClick={() => setKind(k)}
                label={`${KIND_META[k].label} ${kindCounts[k]}`}
              />
            ) : null,
          )}
        </div>
      </div>

      {/* 内容 */}
      {filtered.length === 0 ? (
        <div className="mt-16 flex flex-col items-center justify-center gap-3 text-center text-ink-3">
          <Library size={40} strokeWidth={1.4} />
          <p className="text-aux">
            {knowledge.length === 0
              ? '知识库还是空的。打开任意报告，选中文字或点击「收入知识库」即可沉淀洞察。'
              : '没有匹配的内容，换个关键词试试。'}
          </p>
        </div>
      ) : (
        <div className="mt-8 flex flex-col gap-8">
          {grouped.map(([reportId, g]) => (
            <div key={reportId}>
              <button
                onClick={() => navigate(`/report/${reportId}`)}
                className="mb-3 inline-flex items-center gap-1.5 text-aux font-semibold text-ink hover:text-primary-deep"
              >
                {g.title}
                <ExternalLink size={13} className="text-ink-3" />
              </button>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {g.items.map((k) => {
                  const meta = KIND_META[k.kind]
                  return (
                    <motion.div
                      key={k.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="group relative flex flex-col rounded-card border border-line/60 bg-card p-4 shadow-card transition-shadow hover:shadow-float"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1 rounded-chip px-2 h-6 text-tag font-medium ${meta.cls}`}>
                          <meta.icon size={12} /> {meta.label}
                        </span>
                        {k.destination && <span className="text-tag text-ink-3">{k.destination}</span>}
                        <button
                          onClick={() => removeFromKB(k.id)}
                          className="ml-auto text-ink-3 opacity-0 transition-opacity hover:text-risk group-hover:opacity-100"
                          title="移出知识库"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                      {k.imageSrc && (
                        <img
                          src={k.imageSrc}
                          alt=""
                          referrerPolicy="no-referrer"
                          className="mt-3 aspect-[16/9] w-full rounded-btn object-cover"
                          onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                        />
                      )}
                      <p className="mt-3 flex-1 text-aux leading-relaxed text-ink-2">{k.content}</p>
                      {k.tags.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {k.tags.map((t, i) => (
                            <span key={i} className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                      {k.sourceUrl && (
                        <a
                          href={k.sourceUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-3 inline-flex items-center gap-1 text-tag font-medium text-primary-deep hover:underline"
                        >
                          <ExternalLink size={12} /> 溯源原文
                        </a>
                      )}
                    </motion.div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FilterChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-chip px-3 h-8 text-tag font-medium transition-colors ${
        active ? 'bg-primary text-white' : 'bg-card border border-line text-ink-2 hover:bg-primary-tint/50'
      }`}
    >
      {label}
    </button>
  )
}

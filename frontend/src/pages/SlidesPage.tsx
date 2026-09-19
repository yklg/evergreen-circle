import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, Printer } from 'lucide-react'
import { fetchReport } from '../lib/api'
import MetricsStrip from '../components/MetricsStrip'
import { VChart } from '../components/VChart'
import { BRAND } from '../lib/brand'
import type { Report } from '../types'

/**
 * 幻灯片汇报页（/report/:reportId/slides）：16:9 全屏演示，精选 8 页模板。
 * 键盘（← → 空格 PgUp PgDn Home End）+ 按钮翻页；缺失章节自动跳过且页码连续；
 * 「打印为 PDF」：@media print 下每页一屏（A4 横向），输出汇报文件。
 */
export default function SlidesPage() {
  const { reportId } = useParams()
  const navigate = useNavigate()
  const rid = reportId ?? ''
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchReport(rid)
      .then((r) => {
        if (cancelled) return
        setReport(r)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError('报告加载失败')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [rid])

  // 幻灯片专属打印规则（@page 横向 + 每页一屏 + 隐藏工具条）。
  // 动态注入避免影响报告页原有的 window.print() 纵向打印行为。
  useEffect(() => {
    const style = document.createElement('style')
    style.textContent = `
      @media print {
        @page { size: A4 landscape; margin: 0; }
        .slides-toolbar, .slides-nav, .slides-caption { display: none !important; }
        .slides-page {
          page-break-after: always;
          break-after: page;
          width: 100% !important;
          height: 100vh !important;
          aspect-ratio: auto !important;
          border-radius: 0 !important;
          box-shadow: none !important;
        }
      }
    `
    document.head.appendChild(style)
    return () => {
      document.head.removeChild(style)
    }
  }, [])

  const pages = useMemo(() => buildPages(report), [report])
  const total = pages.length
  const safeIdx = Math.min(idx, total - 1)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
        e.preventDefault()
        setIdx((i) => Math.min(i + 1, total - 1))
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault()
        setIdx((i) => Math.max(i - 1, 0))
      } else if (e.key === 'Home') {
        setIdx(0)
      } else if (e.key === 'End') {
        setIdx(total - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [total])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg text-ink-2">
        正在加载幻灯片…
      </div>
    )
  }
  if (error || !report || !pages.length) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-bg text-ink-2">
        <p>{error ?? '报告为空，无法生成幻灯片'}</p>
        <button
          onClick={() => navigate(`/report/${rid}`)}
          className="rounded-btn bg-primary px-5 h-10 text-sm font-medium text-white"
        >
          返回报告
        </button>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#0f1613] px-4 py-4">
      {/* 顶部工具条（打印时隐藏） */}
      <div className="slides-toolbar mx-auto mb-3 flex w-full max-w-[1200px] items-center justify-between">
        <button
          onClick={() => navigate(`/report/${rid}`)}
          className="inline-flex items-center gap-1.5 rounded-btn border border-white/15 px-3 h-9 text-sm text-[#dfebe4] transition-colors hover:bg-white/10"
        >
          <ArrowLeft size={15} /> 返回报告
        </button>
        <span className="text-sm text-[#a9c2b4]">
          <span className="key-hint">← → 空格</span> 翻页 · {safeIdx + 1} / {total}
        </span>
        <button
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 rounded-btn bg-[#2f9d6e] px-4 h-9 text-sm font-medium text-white shadow transition-all hover:bg-[#1f7a54]"
        >
          <Printer size={15} /> 打印为 PDF
        </button>
      </div>

      {/* 16:9 画布（单页） */}
      <div className="relative mx-auto w-full max-w-[1200px] flex-1 self-center">
        <div className="slides-page aspect-[16/9] w-full overflow-hidden rounded-[16px] bg-white text-[#1d211f] shadow-[0_18px_60px_rgba(0,0,0,.45)]">
          {pages[safeIdx]?.()}
        </div>

        {/* 屏幕翻页按钮（打印时隐藏） */}
        <button
          aria-label="上一张"
          onClick={() => setIdx((i) => Math.max(i - 1, 0))}
          disabled={safeIdx === 0}
          className="slides-nav absolute left-3 top-1/2 -translate-y-1/2 grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-white/5 text-white backdrop-blur transition-colors hover:bg-white/15 disabled:opacity-30"
        >
          <ChevronLeft size={20} />
        </button>
        <button
          aria-label="下一张"
          onClick={() => setIdx((i) => Math.min(i + 1, total - 1))}
          disabled={safeIdx === total - 1}
          className="slides-nav absolute right-3 top-1/2 -translate-y-1/2 grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-white/5 text-white backdrop-blur transition-colors hover:bg-white/15 disabled:opacity-30"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      <div className="mx-auto mt-3 w-full max-w-[1200px] text-center text-xs text-[#7f9790]">
        缺失章节自动跳过 · 全屏演示 / 打印输出每屏一页汇报
      </div>
    </div>
  )
}

/* ── 8 页模板（缺失内容返回 null 自动跳过，页码保持连续）───────── */
function buildPages(r: Report | null): ((() => ReactNode) | null)[] {
  if (!r) return []
  const sec = (id: string) => r.sections.find((s) => s.id === id)
  const hasContent = (s?: { key_takeaway?: string; highlights?: string[] }) =>
    Boolean(s && (s.key_takeaway || (s.highlights && s.highlights.length > 0)))
  const overview = sec('overview') ?? sec('feature')

  const byType: Record<string, number> = {}
  r.evidence.forEach((e) => {
    byType[e.source_type] = (byType[e.source_type] ?? 0) + 1
  })

  return [
    // 1 封面
    () => <Slide title={r.title} subtitle={r.subtitle} center={<CoverMeta r={r} />} />,
    // 2 执行摘要
    hasContent(sec('summary'))
      ? () => (
          <Slide title="执行摘要 · 核心判断" center={<SectionKeys s={sec('summary')} isSummary />} />
        )
      : null,
    // 3 关键数据速览
    () => (
      <Slide
        title="关键数据速览"
        center={
          <div className="space-y-6">
            <div className="mx-auto max-w-2xl">
              <MetricsStrip report={r} />
            </div>
            {overview?.charts?.length ? <VChart spec={overview.charts[0]} height={200} /> : null}
          </div>
        }
      />
    ),
    // 4 竞争格局
    hasContent(overview)
      ? () => (
          <Slide
            title="竞争格局"
            center={
              <div className="space-y-5">
                <SectionKeys s={overview} inlineCharts />
              </div>
            }
          />
        )
      : null,
    // 5 护城河与反共识
    hasContent(sec('moat')) || hasContent(sec('contrarian')) ? (
      () => (
        <Slide
          title="护城河与反共识"
          center={
            <div className="space-y-6">
              {hasContent(sec('moat')) && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#2f9d6e]">护城河深度</h3>
                  <SectionKeys s={sec('moat')} />
                </div>
              )}
              {hasContent(sec('contrarian')) && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#2f9d6e]">反共识洞察</h3>
                  <SectionKeys s={sec('contrarian')} />
                </div>
              )}
            </div>
          }
        />
      )
    ) : null,
    // 6 结论与行动建议
    hasContent(sec('conclusion')) ? () => <Slide title="结论与行动建议" center={<SectionKeys s={sec('conclusion')} />} /> : null,
    // 7 风险清单
    hasContent(sec('risk')) ? () => <Slide title="风险清单与不确定性" center={<SectionKeys s={sec('risk')} />} /> : null,
    // 8 证据与信源
    () => (
      <Slide
        title="证据与信源"
        center={
          <div>
            <div className="mb-4 flex items-end gap-8">
              <div>
                <div className="font-serif text-[42px] font-bold leading-none text-[#1d211f]">{r.evidence.length}</div>
                <div className="mt-1 text-sm text-[#5b6560]">条联网证据 · {r.claims.length} 条结论</div>
              </div>
              <div className="flex-1">
                <SourceBars byType={byType} />
              </div>
            </div>
            <p className="text-sm text-[#5b6560]">
              全部结论可溯源至对应证据（证据库按来源类型分布，可点击下钻查看原始信源与可信度）。
            </p>
          </div>
        }
      />
    ),
  ].filter(Boolean)
}

/* 幻灯片页壳 */
function Slide({ title, subtitle, center }: { title: string; subtitle?: string; center: ReactNode }) {
  return (
    <div className="flex h-full flex-col px-14 py-12">
      <div className="text-xs uppercase tracking-[0.25em] text-[#2f9d6e]">{BRAND.en} · 竞品调研汇报</div>
      <h1 className="mt-2 font-serif text-[30px] font-bold leading-snug text-[#16211b]">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-[#5b6560]">{subtitle}</p>}
      <div className="mt-6 flex-1 overflow-hidden">{center}</div>
    </div>
  )
}

function CoverMeta({ r }: { r: Report }) {
  return (
    <div className="mt-4 space-y-2 text-sm text-[#5b6560]">
      <div>生成日期：{r.created_at}</div>
      {r.brands && r.brands.length > 0 && <div>竞品范围：{r.brands.join(' · ')}</div>}
      <div>
        {r.evidence.length} 条联网证据 · {r.claims.length} 条结论 · {r.experts.length} 位专家协作
      </div>
    </div>
  )
}

function SectionKeys({
  s,
  isSummary,
  inlineCharts,
}: {
  s?: { title?: string; key_takeaway?: string; highlights?: string[]; charts?: unknown[] }
  isSummary?: boolean
  inlineCharts?: boolean
}) {
  if (!s) return null
  return (
    <div className="space-y-4">
      {s.key_takeaway && (
        <div className="rounded-[10px] border-l-[4px] border-[#2f9d6e] bg-[#eef6f2] p-4">
          <p className="text-[17px] leading-relaxed text-[#24402f]">{s.key_takeaway}</p>
        </div>
      )}
      {(s.highlights ?? []).slice(0, 6).length > 0 && (
        <ul className="space-y-2">
          {(s.highlights ?? []).slice(0, 6).map((h, i) => (
            <li key={i} className="flex items-start gap-2 text-[15px] text-[#33403a]">
              <span className="mt-[8px] h-[6px] w-[6px] shrink-0 rounded-full bg-[#2f9d6e]" />
              <span>{h}</span>
            </li>
          ))}
        </ul>
      )}
      {inlineCharts && (s as { charts?: { chart_id: string }[] })?.charts?.slice(0, 1).map((c: { chart_id: string }) => (
        <VChart key={c.chart_id} spec={c as never} height={190} />
      ))}
      {isSummary && (
        <p className="pt-1 text-xs text-[#8aa094]">（供 30 秒扫读，详细论证见完整报告）</p>
      )}
    </div>
  )
}

function SourceBars({ byType }: { byType: Record<string, number> }) {
  const items = Object.entries(byType).map(([t, n]) => ({ type: t, n }))
  const total = items.reduce((a, b) => a + b.n, 0) || 1
  if (items.length === 0) return <div className="text-sm text-[#8aa094]">暂无来源数据</div>
  const palette = ['bg-[#2f9d6e]', 'bg-[#7fa891]', 'bg-[#b4c9be]', 'bg-[#5b8a73]']
  return (
    <div className="space-y-1.5">
      {items.map((it, i) => (
        <div key={it.type} className="flex items-center gap-2 text-xs text-[#5b6560]">
          <span className="w-24 shrink-0 truncate">{it.type}</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#eef1ef]">
            <div
              className={`h-full rounded-full ${palette[i % palette.length]}`}
              style={{ width: `${Math.round((it.n / total) * 100)}%` }}
            />
          </div>
          <span className="w-12 text-right">{Math.round((it.n / total) * 100)}%</span>
        </div>
      ))}
    </div>
  )
}
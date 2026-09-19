import { useEffect, useState } from 'react'
import { Sparkles, Lightbulb, ChevronDown, ChevronUp } from 'lucide-react'
import { generateReportBrief, openTaskStream } from '../lib/api'
import { VChart } from './VChart'
import { ChapterContentMap } from './ChapterContentMap'
import type { Report, ReportBrief } from '../types'

/**
 * 简报视图（只读快览）：一页纸精炼（AI 生成四段）+ 逐节核心判断/亮点/图表 + 展开全文折叠。
 * 原则：纯文本渲染（禁 dangerouslySetInnerHTML，防注入）；空章节自动过滤；亮点 ≤4 条。
 * G7 演进：生成走 kind='brief' 后台任务（POST 得 taskId → SSE 订阅 progress/done/error），
 * done 信号触发父级重载（onBriefDone）以落地持久化 brief；失败显式展示原因，可立即重试。
 */
export default function ReportBriefView({
  report,
  onBriefDone,
}: {
  report: Report
  onBriefDone?: () => void
}) {
  const [brief, setBrief] = useState<ReportBrief | undefined>(report.brief)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<{ percent: number; stage: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // 父级重载后（done → load）新 brief 随 report 落地，同步本地渲染态。
  useEffect(() => {
    // 同步 prop 派生的本地态（父组件重载驱动的有意模式）
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBrief(report.brief)
    if (report.brief) {
      setLoading(false)
      setProgress(null)
      setError(null)
    }
  }, [report.brief])

  const onGenerate = async () => {
    if (loading) return
    setLoading(true)
    setProgress({ percent: 0, stage: '创建任务…' })
    setError(null)
    let res: { taskId: string }
    try {
      res = await generateReportBrief(report.id)
    } catch (e) {
      setLoading(false)
      setProgress(null)
      setError(e instanceof Error ? e.message : '生成启动失败，请重试')
      return
    }
    const close = openTaskStream(res.taskId, {
      onEvent: (type, data: unknown) => {
        const d = data as { percent?: number; stage?: string; message?: string }
        if (type === 'progress') {
          setProgress({ percent: d.percent ?? 0, stage: d.stage ?? '' })
        } else if (type === 'done') {
          close()
          onBriefDone?.() // 父级重载报告，brief 随响应落地
        } else if (type === 'error') {
          close()
          setLoading(false)
          setProgress(null)
          setError(d.message || '生成失败，请重试')
        }
      },
      onError: () => {
        // 连接断开不代表任务失败（runner 后台继续跑）：任务终态由二期轮询/重连补齐，
        // 此处仅收起本地进度态，不伪装成功也不伪装失败。
        setLoading(false)
        setProgress(null)
        setError(null)
      },
    })
  }

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const sections = report.sections.filter(
    (s) => s.key_takeaway || (s.highlights && s.highlights.length > 0) || (s.charts && s.charts.length > 0),
  )

  return (
    <div className="relative mx-auto max-w-3xl px-6 py-8">
      {/* 一页纸精炼 */}
      <div className="rounded-card border border-line bg-card p-5 shadow-card">
        <div className="flex items-center gap-2 text-aux font-semibold text-primary-deep">
          <Sparkles size={16} /> 一页纸精炼
          {brief && <span className="text-tag font-normal text-ink-3">· 结论已压缩为汇报要点，完整论证见全文</span>}
        </div>

        {brief ? (
          <>
            <p className="mt-3 text-aux leading-relaxed text-ink">
              <span className="font-semibold text-primary-deep">一句话概括：</span>
              {brief.summary || '（暂无概括）'}
            </p>
            <BriefList title="核心判断" items={brief.judgments} />
            <BriefList title="关键数据" items={brief.key_data} />
            <BriefList title="行动建议" items={brief.actions} />
          </>
        ) : (
          <div className="mt-3 flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-tag text-ink-3">
                未生成一页纸精炼。点击右侧按钮由 AI 压缩整份报告，生成后随报告持久保存。
              </p>
              {progress && (
                <div className="mt-2">
                  <div className="flex items-center justify-between text-tag text-ink-3">
                    <span className="truncate">{progress.stage || '生成中…'}</span>
                    <span className="shrink-0 pl-2">{progress.percent}%</span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-chip bg-line">
                    <div
                      className="h-full rounded-chip bg-primary transition-all duration-200"
                      style={{ width: `${progress.percent}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={onGenerate}
              disabled={loading}
              title={loading ? '生成进行中' : 'AI 压缩整份报告为一页纸精炼'}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-primary px-4 h-9 text-sm font-medium text-white shadow-card transition-all hover:bg-primary-deep disabled:opacity-50"
            >
              <Sparkles size={14} />
              {loading ? '生成中…' : 'AI 生成一页纸精炼'}
            </button>
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-card border border-warn/40 bg-red-50 px-3 py-2 text-tag text-warn">
            生成失败：{error}
          </div>
        )}
      </div>

      {/* 章节简报卡片流 */}
      <div className="mt-6 space-y-3">
        {sections.length === 0 && (
          <p className="py-10 text-center text-tag text-ink-3">报告暂无可用章节要点</p>
        )}
        {sections.map((sec, idx) => {
          const isOpen = expanded.has(sec.id)
          return (
            <div key={sec.id} className="overflow-hidden rounded-card border border-line bg-card shadow-card">
              <div className="flex items-center gap-3 px-5 pt-4">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-chip bg-primary-tint font-serif text-[14px] font-semibold text-primary-deep">
                  {idx + 1}
                </span>
                <h3 className="text-aux font-semibold text-ink">{sec.title}</h3>
              </div>
              {sec.key_takeaway && (
                <div className="mx-5 mt-3 flex gap-2 rounded-card border-l-[3px] border-primary bg-primary-tint/40 p-3">
                  <Lightbulb size={15} className="mt-0.5 shrink-0 text-primary-deep" />
                  <p className="text-aux leading-relaxed text-ink-2">{sec.key_takeaway}</p>
                </div>
              )}

              {/* 本章内容结构图 */}
              <div className="mx-5 mt-3">
                <ChapterContentMap section={sec} mode="summary" collapsed={true} />
              </div>
              {(sec.highlights ?? []).slice(0, 4).length > 0 && (
                <ul className="mx-5 mt-3 space-y-1.5">
                  {(sec.highlights ?? []).slice(0, 4).map((h, i) => (
                    <li key={i} className="flex items-start gap-2 text-aux text-ink-2">
                      <span className="mt-[9px] h-[5px] w-[5px] shrink-0 rounded-full bg-primary" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              )}
              {sec.charts && sec.charts.length > 0 && (
                <div className="mx-5 mt-3">
                  {sec.charts.map((c) => (
                    <VChart key={c.chart_id} spec={c} />
                  ))}
                </div>
              )}
              {sec.paragraphs && sec.paragraphs.length > 0 && (
                <>
                  <button
                    type="button"
                    onClick={() => toggle(sec.id)}
                    className="mx-5 my-3 inline-flex items-center gap-1 text-tag text-primary-deep hover:underline"
                  >
                    {isOpen ? (
                      <>
                        <ChevronUp size={13} /> 收起全文
                      </>
                    ) : (
                      <>
                        <ChevronDown size={13} /> 展开全文（{sec.paragraphs.length} 段）
                      </>
                    )}
                  </button>
                  {isOpen && (
                    <div className="brief-para-expand space-y-3 border-t border-line px-5 py-4">
                      {sec.paragraphs.map((p, i) => (
                        <p key={i} className="text-aux leading-relaxed text-ink-2">{p}</p>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BriefList({ title, items }: { title: string; items: string[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="mt-3">
      <div className="text-tag font-semibold text-ink-3">{title}</div>
      <ul className="mt-1.5 space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2 text-aux text-ink-2">
            <span className="mt-[9px] h-[5px] w-[5px] shrink-0 rounded-full bg-primary" />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
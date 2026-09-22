import { useEffect, useState, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ChevronLeft,
  Network,
  Download,
  BookOpen,
  Quote,
  Users,
  Calendar,
  Lightbulb,
  Sparkles,
  Link2,
  FileText,
  Presentation,
  Image as ImageIcon,
  ExternalLink,
  Pencil,
  Eye,
  Highlighter,
  Trash2,
  BookmarkPlus,
} from 'lucide-react'
import { useReportStore } from '../store/reportStore'
import { useAnnotationStore } from '../store/annotationStore'
import type { Highlight, HighlightColor } from '../store/annotationStore'
import { VChart } from '../components/VChart'
import { VClaimCard } from '../components/VClaimCard'
import { VSentimentPanel } from '../components/VSentimentPanel'
import { VEvidenceCard } from '../components/VEvidenceFeed'
import { VEditableBlock } from '../components/VEditableBlock'
import { VSelectionToolbar } from '../components/VSelectionToolbar'
import { VMetricsPanel } from '../components/VMetricsPanel'
import { VQualityGate } from '../components/VQualityGate'
import { VAuditReview } from '../components/VAuditReview'
import { VDecisionReplay } from '../components/VDecisionReplay'
import { VDataGrid } from '../components/VDataGrid'
import { VStructuredBlock } from '../components/VStructured'
import { ChapterContentMap } from '../components/ChapterContentMap'
import { refineSection, submitFeedback, refineReportEvidence, openTaskStream } from '../lib/api'
import { VSkeleton } from '../components/ui'
import MetricsStrip from '../components/MetricsStrip'
import ReportBriefView from '../components/ReportBriefView'
import MethodologyNote from '../components/MethodologyNote'

const HL_DOT: Record<HighlightColor, string> = {
  sun: 'bg-sun',
  ok: 'bg-ok',
  risk: 'bg-risk',
  info: 'bg-info',
}
const HL_LABEL: Record<HighlightColor, string> = {
  sun: '重点',
  ok: '认同',
  risk: '存疑',
  info: '待办',
}

/**
 * 章节正文（C1）：首段作评注直出，其余段落收进 <details> 折叠。
 * 折叠只承载阅读态：编辑模式或本章有高亮命中时一次性置 open（评审②），
 * 其后用户仍可手动折叠；段落编辑键 `${secId}-p${i}` 与折叠前一致。
 */
function VSectionProse({
  rid,
  secId,
  paragraphs,
  editMode,
  highlights,
  getEdit,
  setEdit,
}: {
  rid: string
  secId: string
  paragraphs: string[]
  editMode: boolean
  highlights: Highlight[]
  getEdit: (reportId: string, blockId: string) => string | undefined
  setEdit: (reportId: string, blockId: string, text: string) => void
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null)
  const openedRef = useRef(false)
  const forceOpen = editMode || highlights.length > 0
  useEffect(() => {
    if (forceOpen && !openedRef.current) {
      openedRef.current = true
      detailsRef.current?.setAttribute('open', '')
    }
  }, [forceOpen])

  if (paragraphs.length === 0) return null
  const renderP = (p: string, i: number) => (
    <VEditableBlock
      key={i}
      as="p"
      value={getEdit(rid, `${secId}-p${i}`) ?? p}
      editable={editMode}
      onSave={(t) => setEdit(rid, `${secId}-p${i}`, t)}
      className="text-body leading-relaxed text-ink-2"
      highlights={highlights}
    />
  )
  const rest = paragraphs.slice(1)
  return (
    <div className="mt-4">
      {renderP(paragraphs[0], 0)}
      {rest.length > 0 && (
        <details
          ref={detailsRef}
          data-section-body={secId}
          className="report-body-collapse mt-3 rounded-card border border-line/60 bg-card/40 px-4 py-2"
        >
          <summary className="cursor-pointer select-none text-tag font-medium text-primary-deep">
            展开完整正文（还有 {rest.length} 段）
          </summary>
          <div className="report-body-inner mt-3 space-y-3 pb-1">{rest.map((p, i) => renderP(p, i + 1))}</div>
        </details>
      )}
    </div>
  )
}

export default function ReportPage() {
  const { reportId } = useParams()
  const navigate = useNavigate()
  const { current, loading, error, load } = useReportStore()
  const [activeSection, setActiveSection] = useState<string>('')
  const [readProgress, setReadProgress] = useState(0)
  const [editMode, setEditMode] = useState(false)
  const [briefMode, setBriefMode] = useState(false)
  const [highlightedEv, setHighlightedEv] = useState<string[]>([])
  const [refiningSec, setRefiningSec] = useState<string>('')
  const [refiningAll, setRefiningAll] = useState(false)
  const [refineProgress, setRefineProgress] = useState<{ percent: number; stage: string } | null>(null)
  const mainRef = useRef<HTMLElement>(null)
  const articleRef = useRef<HTMLDivElement>(null)
  const rid = reportId ?? ''
  const {
    annotations,
    setEdit,
    getEdit,
    addHighlight,
    removeHighlight,
    addToKB,
  } = useAnnotationStore()
  const reportHls = annotations[rid]?.highlights ?? []

  useEffect(() => {
    if (reportId) load(reportId)
  }, [reportId, load])

  // C1 打印同步：details 闭合时浏览器经匿名 slot 隐藏内部内容，CSS 无法强制展开，
  // beforeprint 统一置 open、afterprint 还原打印前状态（index.css 另有 summary 留底规则）。
  useEffect(() => {
    const COLLAPSE = 'details.report-body-collapse'
    let prev: Element[] = []
    const onBefore = () => {
      prev = Array.from(document.querySelectorAll(`${COLLAPSE}:not([open])`))
      prev.forEach((el) => el.setAttribute('open', ''))
    }
    const onAfter = () => prev.forEach((el) => el.removeAttribute('open'))
    window.addEventListener('beforeprint', onBefore)
    window.addEventListener('afterprint', onAfter)
    return () => {
      window.removeEventListener('beforeprint', onBefore)
      window.removeEventListener('afterprint', onAfter)
    }
  }, [])

  // 阅读进度条 + 目录滚动高亮（scroll-spy）
  useEffect(() => {
    const el = mainRef.current
    if (!el || !current) return
    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el
      const max = scrollHeight - clientHeight
      setReadProgress(max > 0 ? Math.min(100, (scrollTop / max) * 100) : 0)
      // 找到当前可视区顶部最近的章节
      let cur = ''
      for (const s of current.sections) {
        const node = document.getElementById(`sec-${s.id}`)
        if (node && node.getBoundingClientRect().top - el.getBoundingClientRect().top <= 120) {
          cur = s.id
        }
      }
      if (cur) setActiveSection(cur)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => el.removeEventListener('scroll', onScroll)
  }, [current])

  function jumpTo(id: string) {
    setActiveSection(id)
    const section = document.getElementById(`sec-${id}`)
    if (section && mainRef.current) {
      const container = mainRef.current
      const sectionTop = section.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
      container.scrollTo({
        top: sectionTop - 80, // 减去顶部进度条高度
        behavior: 'smooth'
      })
    }
  }
  function jumpToEvidence(ids: string[]) {
    if (ids[0]) document.getElementById(`ev-${ids[0]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedEv(ids)
    window.setTimeout(() => setHighlightedEv([]), 2400)
  }

  // 按批注深化章节（人工介入二次调研）
  async function handleRefine(sectionId: string) {
    if (!current) return
    const notes = (annotations[rid]?.highlights ?? [])
      .filter((h) => h.sectionId === sectionId)
      .map((h) => (h.comment ? `${h.comment}（针对：${h.text.slice(0, 40)}）` : `请深化：${h.text.slice(0, 60)}`))
    if (notes.length === 0) {
      flash('请先在该章节划线批注，再点深化')
      return
    }
    setRefiningSec(sectionId)
    flash('正在按批注深化该章节…')
    const res = await refineSection(rid, sectionId, notes)
    setRefiningSec('')
    if (res.ok && res.section) {
      // 局部更新报告（current + cache）
      const next = { ...current, sections: current.sections.map((s) => (s.id === sectionId ? res.section! : s)) }
      useReportStore.setState((st) => ({ current: next, cache: { ...st.cache, [rid]: next } }))
      flash('章节已按批注深化更新')
    } else {
      flash(res.message || '深化失败，请重试')
    }
  }

  // 基于新归属的高可信度证据异步精修整篇报告（P1-3：显式 SSE 接线 + 本地进度 + done→重载）
  async function handleRefineEvidence() {
    if (!current || refiningAll) return
    setRefiningAll(true)
    setRefineProgress({ percent: 0, stage: '准备中…' })
    const res = await refineReportEvidence(rid, { min_cred: 70 })
    if (!res.taskId) {
      setRefiningAll(false)
      setRefineProgress(null)
      flash('发起精修失败，请重试')
      return
    }
    const close = openTaskStream(res.taskId, {
      onEvent: (type, data: any) => {
        if (type === 'progress') {
          setRefineProgress({ percent: data?.percent ?? 0, stage: data?.stage ?? '' })
        } else if (type === 'done') {
          setRefiningAll(false)
          setRefineProgress(null)
          load(rid)
          flash('报告已基于新证据精修完成')
          close()
        } else if (type === 'error') {
          setRefiningAll(false)
          setRefineProgress(null)
          flash((data?.message as string) || '精修失败，请重试')
          close()
        }
      },
      onError: () => {
        // 连接断开不代表任务失败（runner 后台继续跑），仅收起进度 UI，不报错。
        setRefiningAll(false)
        setRefineProgress(null)
      },
    })
  }

  // ── 标注 / 知识库处理 ──
  function toggleEditMode() {
    setEditMode((v) => {
      const leaving = v
      if (leaving && current) {
        // 离开编辑模式时：把真实人工修正数据回传后端（驱动「人工修正率」指标）
        const edits = annotations[rid]?.edits ?? {}
        const editedBlocks = Object.keys(edits).length
        const totalBlocks = current.sections.reduce(
          (acc, s) => acc + (s.paragraphs?.length ?? 0) + (s.key_takeaway ? 1 : 0),
          0,
        )
        if (editedBlocks > 0) {
          submitFeedback(rid, editedBlocks, totalBlocks, { edits }).catch(() => {})
          flash(`已记录 ${editedBlocks}/${totalBlocks} 处人工修正`)
        }
      }
      return !v
    })
  }

  function handleHighlight(sectionId: string, text: string, color: HighlightColor) {
    addHighlight(rid, { sectionId, text, color, comment: '' })
  }
  function handleComment(sectionId: string, text: string) {
    const comment = window.prompt('添加批注：', '')
    if (comment != null) addHighlight(rid, { sectionId, text, color: 'info', comment: comment.trim() })
  }
  function handleSaveSelectionKB(sectionId: string, text: string) {
    if (!current) return
    const ok = addToKB({
      reportId: rid,
      reportTitle: current.title,
      kind: 'note',
      title: `摘录 · ${sectionId}`,
      content: text,
      tags: current.destinations ?? [],
    })
    flash(ok ? '已收入知识库' : '该内容已在知识库中')
  }
  function saveClaimToKB(claimText: string, evidenceIds: string[]) {
    if (!current) return
    const ev = current.evidence.find((e) => e.evidence_id === evidenceIds[0])
    const ok = addToKB({
      reportId: rid,
      reportTitle: current.title,
      kind: 'claim',
      title: '核心论点',
      content: claimText,
      sourceUrl: ev?.source_url,
      evidenceId: ev?.evidence_id,
      tags: current.destinations ?? [],
    })
    flash(ok ? '论点已收入知识库' : '该论点已在知识库中')
  }

  const [toast, setToast] = useState('')
  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(''), 1600)
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-read px-6 py-16">
        <VSkeleton className="h-48 w-full rounded-card" />
        <VSkeleton className="mt-4 h-6 w-2/3" />
        <VSkeleton className="mt-2 h-6 w-1/2" />
      </div>
    )
  }
  if (error || !current) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-bg text-ink-2">
        <p>{error ?? '报告不存在'}</p>
        <button onClick={() => navigate('/')} className="rounded-btn bg-primary px-5 h-10 text-aux font-medium text-white">
          返回首页
        </button>
      </div>
    )
  }

  const r = current
  // 证据 id → 序号（用于章节级溯源 chips）
  const evIndex = new Map(r.evidence.map((e, i) => [e.evidence_id, i + 1]))

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg">
      {/* 左：目录 TOC */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-card/50 lg:flex">
        <div className="flex h-14 items-center gap-2 border-b border-line px-5">
          <button onClick={() => navigate('/')} className="grid h-8 w-8 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint">
            <ChevronLeft size={18} />
          </button>
          <span className="text-aux font-semibold text-ink">报告目录</span>
        </div>
        {/* 阅读进度 */}
        <div className="px-5 pt-3">
          <div className="flex items-center justify-between text-tag text-ink-3">
            <span>阅读进度</span>
            <span>{Math.round(readProgress)}%</span>
          </div>
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-chip bg-line">
            <div className="h-full rounded-chip bg-primary transition-all duration-150" style={{ width: `${readProgress}%` }} />
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto p-3">
          {r.toc.map((t, i) => {
            const active = activeSection === t.id
            return (
              <button
                key={t.id}
                onClick={() => jumpTo(t.id)}
                className={`flex w-full items-start gap-2.5 rounded-btn px-3 py-2 text-left text-aux transition-colors ${
                  active ? 'bg-primary-tint font-medium text-primary-deep' : 'text-ink-2 hover:bg-primary-tint/50'
                }`}
              >
                <span
                  className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-chip text-[11px] font-semibold transition-colors ${
                    active ? 'bg-primary text-white' : 'bg-line/70 text-ink-3'
                  }`}
                >
                  {i + 1}
                </span>
                <span className="leading-snug">{t.title}</span>
              </button>
            )
          })}
        </nav>
        <div className="border-t border-line p-3">
          <button
            onClick={() => navigate(`/graph/${r.id}`)}
            className="flex w-full items-center justify-center gap-2 rounded-btn bg-primary-tint px-3 h-10 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
          >
            <Network size={16} /> 知识图谱
          </button>
        </div>
      </aside>

      {/* 中：正文 */}
      <main ref={mainRef} className="min-w-0 flex-1 overflow-y-auto">
        {/* 顶部阅读进度条（贯穿全宽） */}
        <div className="sticky top-0 z-20 h-0.5 w-full bg-transparent">
          <div className="h-full bg-primary transition-all duration-150" style={{ width: `${readProgress}%` }} />
        </div>
        {/* 英雄区：纯 CSS 渐变底 + 自然流布局。
            旧版渲染 coverFor(r) 封面图，图内烘死「标题 / 品牌行 / 标语」三段文字，
            与 DOM 标题前后重叠；且标题块 absolute bottom-0 向上生长，长标题会被
            overflow-hidden 裁剪。改为渐变底 + 自然流后高度随内容自适应，
            结构上不再可能重叠或裁剪。渐变色沿用原封面图配色，故白字对比度不变。
            打印留底见 index.css @media print 的 .report-hero。 */}
        <div className="report-hero bg-gradient-to-br from-[#0f766e] to-[#134e4a] px-8 pb-10 pt-6">
          {/* 操作行：原 absolute right-6 top-6，改为自然流 + 折行，窄列宽不再溢出右缘 */}
          <div className="mb-6 flex flex-wrap items-center justify-end gap-2">
            <button
              onClick={() => navigate('/knowledge')}
              className="inline-flex items-center gap-1.5 rounded-btn bg-card/90 px-3 h-9 text-aux font-medium text-ink-2 backdrop-blur hover:text-primary-deep"
            >
              <BookOpen size={15} /> 知识库
            </button>
            {r.trace && r.trace.length > 0 && (
              <button
                onClick={() => navigate(`/trace/${r.id}`)}
                className="inline-flex items-center gap-1.5 rounded-btn bg-card/90 px-3 h-9 text-aux font-medium text-ink-2 backdrop-blur hover:text-primary-deep"
              >
                <Network size={15} /> 决策链路
              </button>
            )}
            <button
              onClick={() => setBriefMode((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-btn px-3 h-9 text-aux font-medium backdrop-blur ${
                briefMode ? 'bg-primary text-white' : 'bg-card/90 text-ink-2 hover:text-primary-deep'
              }`}
            >
              <FileText size={15} /> 简报
            </button>
            <button
              onClick={() => navigate(`/report/${r.id}/slides`)}
              className="inline-flex items-center gap-1.5 rounded-btn bg-card/90 px-3 h-9 text-aux font-medium text-ink-2 backdrop-blur hover:text-primary-deep"
            >
              <Presentation size={15} /> 演示
            </button>
            <button
              onClick={toggleEditMode}
              className={`inline-flex items-center gap-1.5 rounded-btn px-3 h-9 text-aux font-medium backdrop-blur ${
                editMode ? 'bg-primary text-white' : 'bg-card/90 text-ink-2 hover:text-primary-deep'
              }`}
            >
              {editMode ? <><Eye size={15} /> 阅读</> : <><Pencil size={15} /> 编辑</>}
            </button>
            <button
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 rounded-btn bg-card/90 px-3 h-9 text-aux font-medium text-ink-2 backdrop-blur hover:text-primary-deep"
            >
              <Download size={15} /> 导出
            </button>
          </div>
          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="max-w-3xl font-serif text-[32px] leading-tight text-white"
          >
            {r.title}
          </motion.h1>
          <p className="mt-2 max-w-2xl text-aux text-white/85">{r.subtitle}</p>
          {r.answers_digest && r.answers_digest.length > 0 && (
            <p data-testid="answers-digest" className="mt-2 max-w-2xl text-tag text-white/80">
              你的需求：
              {r.answers_digest.map((d) => `${d.label} ${d.value}`).join(' · ')}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-4 text-tag text-white/75">
            <span className="inline-flex items-center gap-1"><Calendar size={13} /> {r.created_at}</span>
            <span className="inline-flex items-center gap-1"><Users size={13} /> {r.experts.length} 位专家</span>
            <span className="inline-flex items-center gap-1"><Quote size={13} /> {r.claims.length} 条结论 · {r.evidence.length} 条证据</span>
          </div>
        </div>

        {/* 关键指标速览数据带（指标定义单一来源，见 components/MetricsStrip.tsx） */}
        <div className="border-b border-line bg-card/60">
          <MetricsStrip report={r} />
        </div>

        {/* 正文章节（简报模式替换为简报视图） */}
        {briefMode ? (
          <ReportBriefView report={r} onBriefDone={() => load(rid)} />
        ) : (
        <article ref={articleRef} className="relative mx-auto max-w-3xl px-6 py-10">
          <VSelectionToolbar
            containerRef={articleRef}
            enabled
            onHighlight={handleHighlight}
            onComment={handleComment}
            onSaveKB={handleSaveSelectionKB}
          />

          {/* 效能与业务闭环指标 + 质检返工闭环 */}
          <VMetricsPanel metrics={r.metrics} />
          <VAuditReview review={r.audit_review} />
          <VQualityGate before={r.quality_before} after={r.quality_after} />
          {r.sections.map((sec, idx) => (
            <section key={sec.id} id={`sec-${sec.id}`} data-section-id={sec.id} className="mb-12 scroll-mt-6">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-card bg-primary-tint font-serif text-[18px] font-semibold text-primary-deep">
                  {idx + 1}
                </span>
                <h2 className="font-serif text-h2 text-ink">{sec.title}</h2>
              </div>
              {/* 核心判断（结论先行） */}
              {sec.key_takeaway && (
                <div className="mt-3 flex gap-3 rounded-card border-l-[3px] border-primary bg-primary-tint/40 p-4">
                  <Lightbulb size={18} className="mt-0.5 shrink-0 text-primary-deep" />
                  <VEditableBlock
                    as="p"
                    value={getEdit(rid, `${sec.id}-takeaway`) ?? sec.key_takeaway}
                    editable={editMode}
                    onSave={(t) => setEdit(rid, `${sec.id}-takeaway`, t)}
                    className="text-body font-medium text-ink"
                  />
                </div>
              )}

              {/* 本章内容结构图 */}
              <ChapterContentMap section={sec} mode="detail" collapsed={true} />

              {/* C1 版式（全章节统一）：核心判断 → 图表/结构化/数据表置顶 → 评注段 → 折叠正文 → 亮点/论点 */}
              {/* 图表 */}
              {sec.charts && sec.charts.length > 0 && (
                <div className="mt-4 grid grid-cols-1 gap-4">
                  {sec.charts.map((c) => (
                    <VChart key={c.chart_id} spec={c} onCite={jumpToEvidence} />
                  ))}
                </div>
              )}

              {/* 结构化调研知识（榜单/路线/住宿/花费 · 可达/配套/风险）*/}
              <VStructuredBlock block={sec.structured} />

              {/* 数据空间（CSV 表格）*/}
              {sec.data_grid && <VDataGrid grid={sec.data_grid} title={`${sec.title} · 数据空间`} />}

              {/* 正文：首段作评注直出，其余收进折叠（后端文字不删；编辑态/高亮命中自动展开） */}
              <VSectionProse
                rid={rid}
                secId={sec.id}
                paragraphs={sec.paragraphs ?? []}
                editMode={editMode}
                highlights={reportHls.filter((h) => h.sectionId === sec.id)}
                getEdit={getEdit}
                setEdit={setEdit}
              />

              {/* 亮点 / 独特洞察 */}
              {sec.highlights && sec.highlights.length > 0 && (
                <ul className="mt-4 space-y-2 rounded-card bg-card/60 p-4">
                  {sec.highlights.map((h, i) => (
                    <li key={i} className="flex gap-2 text-aux text-ink-2">
                      <Sparkles size={15} className="mt-0.5 shrink-0 text-warn" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* 论点卡 */}
              {sec.claims && sec.claims.length > 0 && (
                <div className="mt-5 space-y-3">
                  {sec.claims.map((c) => (
                    <div key={c.claim_id} className="group/claim relative">
                      <VClaimCard claim={c} onCite={jumpToEvidence} />
                      <button
                        onClick={() => saveClaimToKB(c.text, c.evidence_ids)}
                        title="收入知识库"
                        className="absolute right-3 top-3 grid h-7 w-7 place-items-center rounded-btn bg-card/80 text-ink-3 opacity-0 backdrop-blur transition-opacity hover:text-primary-deep group-hover/claim:opacity-100"
                      >
                        <BookmarkPlus size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* 舆情面板：旧报告的合成「sentiment」节与新报告的正式「sentiment_report」章节共用
                  （面板是章节级渲染器：情感条/平台分布/逐景点口碑/阵营；图表走 sec.charts 通用管线） */}
              {(sec.id === 'sentiment' || sec.id === 'sentiment_report') && r.sentiment && (
                <div className="mt-5">
                  <VSentimentPanel sentiment={r.sentiment} />
                </div>
              )}

              {/* 章节级信源溯源 */}
              {sec.source_evidence_ids && sec.source_evidence_ids.length > 0 && (
                <div className="mt-5 flex flex-wrap items-center gap-1.5 border-t border-line/60 pt-3">
                  <span className="inline-flex items-center gap-1 text-tag text-ink-3">
                    <Link2 size={13} /> 本章信源
                  </span>
                  {sec.source_evidence_ids.map((id) => (
                    <button
                      key={id}
                      onClick={() => jumpToEvidence([id])}
                      className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag font-medium text-primary-deep hover:bg-primary-soft/40"
                      title="跳转到该证据"
                    >
                      [{evIndex.get(id) ?? '?'}]
                    </button>
                  ))}
                </div>
              )}

              {/* 按批注深化（人工介入二次调研）*/}
              {!['sentiment', 'trace_note', 'figures'].includes(sec.id) && (
                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={() => handleRefine(sec.id)}
                    disabled={refiningSec === sec.id}
                    className="inline-flex items-center gap-1.5 rounded-btn border border-primary-soft bg-primary-tint/50 px-3 py-1.5 text-tag font-medium text-primary-deep hover:bg-primary-tint disabled:opacity-50"
                  >
                    <Sparkles size={13} />
                    {refiningSec === sec.id ? '深化中…' : '按批注深化本章'}
                  </button>
                  {sec.refined && (
                    <span className="rounded-chip bg-ok/10 px-2 py-0.5 text-tag text-ok">已按批注深化</span>
                  )}
                  <span className="text-tag text-ink-3">（先在本章划线写批注，再点此重做）</span>
                </div>
              )}
            </section>
          ))}

          {/* 实景图集 · 图文并茂可溯源 */}
          {r.figures && r.figures.length > 0 && (
            <section id="sec-figures" className="mb-12 scroll-mt-6">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-card bg-primary-tint font-serif text-[18px] font-semibold text-primary-deep">
                  <ImageIcon size={18} />
                </span>
                <h2 className="font-serif text-h2 text-ink">实景图集 · 采集自联网真实页面</h2>
              </div>
              <p className="mt-3 text-aux text-ink-2">
                以下图片均在调研过程中从官方文旅站点、媒体与社媒页面实时抓取（OG 预览图优先），每张图均可点击溯源至原始页面。
              </p>
              <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {r.figures.map((f, i) => (
                  <div
                    key={i}
                    className="group relative overflow-hidden rounded-card border border-line bg-card transition-shadow hover:shadow-md"
                  >
                    <a href={f.source_url} target="_blank" rel="noreferrer" title="点击溯源到原始页面">
                      <div className="relative aspect-[16/9] overflow-hidden bg-primary-tint/30">
                        <img
                          src={f.src}
                          alt={f.alt || f.title || '实景图'}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                          onError={(e) => {
                            const wrap = (e.target as HTMLImageElement).closest('.group') as HTMLElement | null
                            if (wrap) wrap.style.display = 'none'
                          }}
                        />
                        {f.destination && (
                          <span className="absolute left-2 top-2 rounded-chip bg-ink/70 px-2 py-0.5 text-tag font-medium text-white backdrop-blur">
                            {f.destination}
                          </span>
                        )}
                      </div>
                    </a>
                    <button
                      onClick={() => {
                        const ok = addToKB({
                          reportId: rid,
                          reportTitle: r.title,
                          kind: 'figure',
                          title: f.title || '联网实景图',
                          content: f.alt || f.title || '联网采集实景图',
                          sourceUrl: f.source_url,
                          imageSrc: f.src,
                          destination: f.destination,
                          tags: f.destination ? [f.destination] : [],
                        })
                        flash(ok ? '配图已收入知识库' : '该配图已在知识库中')
                      }}
                      title="收入知识库"
                      className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-btn bg-card/85 text-ink-3 opacity-0 backdrop-blur transition-opacity hover:text-primary-deep group-hover:opacity-100"
                    >
                      <BookmarkPlus size={14} />
                    </button>
                    <a
                      href={f.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between gap-2 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-aux font-medium text-ink">{f.title || f.alt || '联网实景图'}</div>
                        <div className="truncate text-tag text-ink-3">{f.domain || f.source_url}</div>
                      </div>
                      <ExternalLink size={14} className="shrink-0 text-ink-3 group-hover:text-primary-deep" />
                    </a>
                  </div>
                ))}
              </div>
            </section>
          )}
        </article>
        )}
      </main>

      {/* 右：知识库（证据 + 术语表） */}
      <aside className="hidden w-80 shrink-0 flex-col border-l border-line bg-card/50 xl:flex">
        <div className="flex h-14 items-center gap-2 border-b border-line px-5">
          <BookOpen size={16} className="text-primary" />
          <span className="text-aux font-semibold text-ink">知识库 · 标注</span>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {/* 我的标注 */}
          <div className="mb-2 flex items-center gap-1.5 text-tag font-semibold text-ink-3">
            <Highlighter size={13} /> 我的标注（{reportHls.length}）
          </div>
          {reportHls.length === 0 ? (
            <p className="mb-5 rounded-card border border-dashed border-line bg-bg/60 p-3 text-tag leading-relaxed text-ink-3">
              点击右上角「编辑」可双击修改正文；选中任意文字即可高亮、批注或收入知识库。
            </p>
          ) : (
            <div className="mb-5 flex flex-col gap-2">
              {reportHls.map((h) => (
                <div key={h.id} className="group rounded-card border border-line/60 bg-bg p-2.5">
                  <div className="flex items-start gap-2">
                    <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${HL_DOT[h.color]}`} />
                    <button
                      onClick={() => jumpTo(h.sectionId)}
                      className="flex-1 text-left text-tag leading-relaxed text-ink-2 hover:text-primary-deep"
                    >
                      <span className="line-clamp-3">{h.text}</span>
                    </button>
                    <button
                      onClick={() => removeHighlight(rid, h.id)}
                      className="shrink-0 text-ink-3 opacity-0 transition-opacity hover:text-risk group-hover:opacity-100"
                      title="删除标注"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5 pl-4.5">
                    <span className="rounded-chip bg-line/60 px-1.5 py-0.5 text-[10px] font-medium text-ink-3">
                      {HL_LABEL[h.color]}
                    </span>
                    {h.comment && (
                      <span className="line-clamp-1 text-[11px] italic text-ink-3">「{h.comment}」</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="text-tag font-semibold text-ink-3">证据来源（{r.evidence.length}）</span>
            <button
              onClick={handleRefineEvidence}
              disabled={refiningAll}
              title="基于高可信度（≥70）证据重写报告正文"
              className="inline-flex items-center gap-1.5 rounded-btn border border-primary-soft bg-primary-tint/50 px-2.5 py-1 text-tag font-medium text-primary-deep hover:bg-primary-tint disabled:opacity-50"
            >
              <Sparkles size={13} />
              {refiningAll ? '精修中…' : '高质证据精修'}
            </button>
          </div>
          {refiningAll && refineProgress && (
            <div className="mb-3">
              <div className="flex items-center justify-between text-tag text-ink-3">
                <span className="truncate">{refineProgress.stage}</span>
                <span className="shrink-0 pl-2">{refineProgress.percent}%</span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-chip bg-line">
                <div
                  className="h-full rounded-chip bg-primary transition-all duration-200"
                  style={{ width: `${refineProgress.percent}%` }}
                />
              </div>
            </div>
          )}
          <div className="flex flex-col gap-2.5">
            {r.evidence.map((ev, i) => (
              <div key={ev.evidence_id} className="group/ev relative">
                <VEvidenceCard ev={ev} index={i} highlighted={highlightedEv.includes(ev.evidence_id)} />
              </div>
            ))}
          </div>

          {r.glossary.length > 0 && (
            <>
              <div className="mb-3 mt-6 text-tag font-semibold text-ink-3">术语表</div>
              <div className="flex flex-col gap-2.5">
                {r.glossary.map((g, i) => (
                  <div key={i} className="rounded-card border border-line/60 bg-bg p-3">
                    <div className="text-aux font-semibold text-ink">{g.term}</div>
                    <p className="mt-1 text-tag leading-relaxed text-ink-2">{g.definition}</p>
                    {g.source && <div className="mt-1 text-tag text-primary-deep">— {g.source}</div>}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* 方法论与局限（v2.1 客观性披露：页首摘要 + 附录键值 + 矛盾陈述）*/}
          <MethodologyNote methodology={r.methodology} contradictions={r.contradictions} />
        </div>
      </aside>

      {/* 决策回放（可拖动进度条回溯每个 Agent 思考并高亮证据）*/}
      {r.trace && r.trace.length > 0 && (
        <VDecisionReplay trace={r.trace} onHighlightEvidence={jumpToEvidence} />
      )}

      {/* 轻提示 toast */}
      {toast && (
        <div className="pointer-events-none fixed bottom-8 left-1/2 z-50 -translate-x-1/2">
          <div className="flex items-center gap-2 rounded-card bg-ink/90 px-4 py-2.5 text-aux font-medium text-white shadow-float backdrop-blur">
            <BookmarkPlus size={15} /> {toast}
          </div>
        </div>
      )}
    </div>
  )
}

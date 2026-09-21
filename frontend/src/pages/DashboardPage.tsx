import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  ShieldCheck, Database, FileText, Sparkles, Search, Bell, BellPlus,
  Trash2, Users, ExternalLink, Layers, Activity, Radar, Crosshair,
  PieChart, TrendingUp, Target, Clock, Zap, Network, Gauge,
} from 'lucide-react'
import {
  fetchDashboard, fetchEvidences, fetchSubscriptions,
  createSubscription, deleteSubscription, fetchWorkload,
} from '../lib/api'
import type {
  DashboardStats, EvidenceQueryResp, EvidenceRecord, Subscription, ExpertWorkload,
} from '../types'
import { VCard, VCountUp } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'

function fmtSaved(min: number): { value: number; unit: string } {
  if (min >= 60) return { value: Math.round((min / 60) * 10) / 10, unit: '小时' }
  return { value: Math.round(min), unit: '分钟' }
}

const SOURCE_LABEL: Record<string, string> = {
  official: '官网', news: '新闻媒体', douyin: '抖音', xiaohongshu: '小红书',
  bilibili: 'B站', weibo: '微博', zhihu: '知乎', review: '评测', financial_report: '财报', web: '网页',
}
function sourceLabel(t: string) {
  return SOURCE_LABEL[t] ?? t
}

/* 信源三大结构：决定情报是否均衡（清晰、不打谜语） */
const SOURCE_CATEGORY: Record<string, '权威一手' | '媒体报道' | '社媒口碑'> = {
  official: '权威一手', financial_report: '权威一手',
  news: '媒体报道', web: '媒体报道', review: '媒体报道',
  douyin: '社媒口碑', xiaohongshu: '社媒口碑', bilibili: '社媒口碑',
  weibo: '社媒口碑', zhihu: '社媒口碑',
}
const CATEGORY_COLOR: Record<string, string> = {
  权威一手: 'bg-primary', 媒体报道: 'bg-info', 社媒口碑: 'bg-sun',
}

interface DestinationIntel {
  destination: string
  count: number
  sourceTypes: number
  avgCred: number
  lastAt: string
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [ev, setEv] = useState<EvidenceQueryResp>({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  const [subs, setSubs] = useState<Subscription[]>([])
  const [workload, setWorkload] = useState<ExpertWorkload[]>([])
  const [loading, setLoading] = useState(true)

  const [destinationFilter, setDestinationFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [subQuery, setSubQuery] = useState('')
  const [subDelError, setSubDelError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [d, e, s, w] = await Promise.all([
        fetchDashboard(),
        fetchEvidences(),
        fetchSubscriptions(),
        fetchWorkload(),
      ])
      if (cancelled) return
      setStats(d)
      setEv(e)
      setSubs(s)
      setWorkload(w)
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const items = useMemo(() => (Array.isArray(ev.items) ? ev.items : []), [ev])

  /* 目的地情报图谱：跨全部报告聚合每个目的地的情报厚度 */
  const destinationIntel = useMemo<DestinationIntel[]>(() => {
    const map = new Map<string, { count: number; types: Set<string>; cred: number; last: string }>()
    for (const it of items) {
      const b = (it.destination || '').trim()
      if (!b) continue
      const cur = map.get(b) ?? { count: 0, types: new Set<string>(), cred: 0, last: '' }
      cur.count += 1
      cur.types.add(it.source_type)
      cur.cred += it.credibility || 0
      if ((it.captured_at || '') > cur.last) cur.last = it.captured_at || ''
      map.set(b, cur)
    }
    return Array.from(map.entries())
      .map(([destination, v]) => ({
        destination,
        count: v.count,
        sourceTypes: v.types.size,
        avgCred: v.count ? v.cred / v.count : 0,
        lastAt: v.last,
      }))
      .sort((a, b) => b.count - a.count)
  }, [items])

  const maxDestinationCount = useMemo(
    () => destinationIntel.reduce((m, b) => Math.max(m, b.count), 1),
    [destinationIntel],
  )

  /* 信源结构：一手 / 媒体 / 社媒 三类占比 + 一句话研判 */
  const sourceStructure = useMemo(() => {
    const cat: Record<string, number> = { 权威一手: 0, 媒体报道: 0, 社媒口碑: 0 }
    for (const it of items) {
      const c = SOURCE_CATEGORY[it.source_type] ?? '媒体报道'
      cat[c] += 1
    }
    const total = items.length || 1
    const pct = (n: number) => Math.round((n / total) * 100)
    const segs = (['权威一手', '媒体报道', '社媒口碑'] as const).map((k) => ({
      label: k, n: cat[k], pct: pct(cat[k]),
    }))
    const top = [...segs].sort((a, b) => b.n - a.n)[0]
    const firstHand = pct(cat['权威一手'])
    let insight: string
    if (firstHand >= 40) {
      insight = `一手权威信源占 ${firstHand}%，情报根基扎实，结论可信度高。`
    } else if (firstHand >= 20) {
      insight = `当前以「${top.label}」为主（${top.pct}%），一手信源占 ${firstHand}%，建议追加官方文旅站点/平台公告以加固关键结论。`
    } else {
      insight = `情报偏向「${top.label}」（${top.pct}%），一手信源仅 ${firstHand}%，重要结论需补充官方文旅站点与平台公告佐证。`
    }
    return { segs, insight }
  }, [items])

  /* 证据列表：按目的地 / 信源类型客户端筛选（与图谱联动） */
  const filteredEv = useMemo<EvidenceRecord[]>(() => {
    return items.filter(
      (it) => (!destinationFilter || it.destination === destinationFilter) && (!typeFilter || it.source_type === typeFilter),
    )
  }, [items, destinationFilter, typeFilter])

  const facetDestinations = useMemo(
    () => Object.entries(ev.facets.by_destination).slice(0, 6),
    [ev],
  )
  const facetTypes = useMemo(
    () => Object.entries(ev.facets.by_type).slice(0, 6),
    [ev],
  )

  const activeWorkload = useMemo(
    () => (Array.isArray(workload) ? workload : []).filter((w) => w.missions > 0).slice(0, 6),
    [workload],
  )

  const handleCreateSub = async () => {
    const q = subQuery.trim()
    if (!q) return
    await createSubscription(q, [])
    setSubQuery('')
    setSubs(await fetchSubscriptions())
  }
  const handleDeleteSub = async (id: string) => {
    setSubDelError(null)
    try {
      await deleteSubscription(id)
      setSubs(await fetchSubscriptions())
    } catch (e) {
      // 写操作失败必须显式呈现，避免"假删除成功"（列表移除但后端未删）
      setSubDelError(e instanceof Error && e.message ? e.message : '删除订阅失败，请稍后重试')
    }
  }

  const empty = !loading && (!stats || stats.reports === 0)
  const coveredDestinations = destinationIntel.length
  const researchCards = stats?.research_cards ?? []

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header>
        <h1 className="font-serif text-h1 text-ink">目的地情报中心</h1>
        <p className="mt-1 text-aux text-ink-2">
          把每一次调研沉淀为可复用的旅行记忆 —— 目的地情报厚度、信源结构、全局溯源与持续追踪
        </p>
      </header>

      {loading ? (
        <div className="mt-16 text-center text-aux text-ink-3">正在加载真实情报数据……</div>
      ) : empty ? (
        <div className="mt-16 flex flex-col items-center gap-3 text-center">
          <div className="text-h3 text-ink">情报库还是空的</div>
          <p className="text-aux text-ink-2">完成第一次调研后，这里会自动沉淀目的地情报、证据溯源与信源结构</p>
          <button
            onClick={() => navigate('/')}
            className="mt-2 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
          >
            发起新调研
          </button>
        </div>
      ) : (
        <>
          {/* 1. 情报资产总览 */}
          <motion.div variants={stagger} initial="initial" animate="animate"
            className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
            <StatCard icon={Target} value={coveredDestinations} label="覆盖目的地"
              tip="已有情报沉淀的目的地数量，覆盖越广旅行视野越全" />
            <StatCard icon={Database} value={stats!.evidence_total} label="情报证据"
              tip={`累计联网取证，平均每篇报告 ${stats!.avg_evidence_per_report} 条`} />
            <StatCard icon={Sparkles} value={stats!.claim_total} label="产出结论"
              tip="全部报告输出的分析结论总数" />
            <StatCard icon={ShieldCheck} value={stats!.fact_accuracy} unit="%" color="text-ok"
              label="交叉验证率" tip="经 ≥2 个独立来源相互印证的结论占比（真实计算，越高越可信）" />
          </motion.div>

          {/* 1.5 业务闭环价值（相比人工的真实可量化提升）*/}
          <motion.div variants={fadeUp} initial="initial" animate="animate" className="mt-6">
            <VCard hover={false}>
              <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                <Gauge size={16} className="text-primary" /> 业务闭环价值
                <span className="ml-1 text-tag text-ink-3">相比传统人工旅游调研的真实可量化提升 · 公式透明可解释</span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <ImpactCard icon={Clock} color="text-primary"
                  value={fmtSaved(stats!.minutes_saved ?? 0).value}
                  unit={fmtSaved(stats!.minutes_saved ?? 0).unit}
                  label="累计节省人力"
                  tip="∑(人工估时 − AI 实际耗时)，按行业经验值每信息源约 8 分钟估算" />
                <ImpactCard icon={Zap} color="text-warn"
                  value={stats!.avg_efficiency ?? 0} unit="×"
                  label="平均效率提升"
                  tip="各报告『人工估时 ÷ AI 实际耗时』的平均倍数" />
                <ImpactCard icon={Layers} color="text-ok"
                  value={stats!.avg_coverage ?? 0} unit="×"
                  label="平均信源覆盖"
                  tip="各报告『独立信源数 ÷ 人工基线(6)』的平均倍数" />
                <ImpactCard icon={Activity} color="text-info"
                  value={Math.round((stats!.total_tokens ?? 0) / 1000)} unit="K"
                  label="累计 Token 算力"
                  tip="所有调研真实消耗的 LLM Token 总量（千）" />
              </div>
            </VCard>
          </motion.div>

          {/* 1.6 每次调研概览（数据 + 日志/决策链路入口）*/}
          {researchCards.length > 0 && (
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="mt-6">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <FileText size={16} className="text-primary" /> 每次调研概览
                  <span className="ml-1 text-tag text-ink-3">每份报告的关键数据 · 一键查看报告与决策链路日志</span>
                </div>
                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {researchCards.slice(0, 9).map((rc) => (
                    <div key={rc.id}
                      className="rounded-card border border-line/60 bg-bg p-4 transition-all hover:border-primary-soft hover:bg-card">
                      <div className="flex items-start justify-between gap-2">
                        <button onClick={() => navigate(`/report/${rc.id}`)}
                          className="line-clamp-2 text-left text-aux font-medium text-ink hover:text-primary-deep">
                          {rc.title}
                        </button>
                      </div>
                      {rc.destinations.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {rc.destinations.slice(0, 4).map((b) => (
                            <span key={b} className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">{b}</span>
                          ))}
                        </div>
                      )}
                      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                        <Mini label="证据" value={`${rc.evidence_count}`} />
                        <Mini label="结论" value={`${rc.claim_count}`} />
                        <Mini label="高置信" value={`${rc.high_conf_count}`} />
                        <Mini label="效率" value={rc.efficiency_multiple ? `${rc.efficiency_multiple}×` : '—'} accent />
                        <Mini label="省时" value={rc.minutes_saved ? `${Math.round(rc.minutes_saved)}m` : '—'} accent />
                        <Mini label="耗时" value={rc.elapsed_minutes ? `${rc.elapsed_minutes}m` : '—'} />
                      </div>
                      <div className="mt-3 flex items-center gap-2">
                        <button onClick={() => navigate(`/report/${rc.id}`)}
                          className="inline-flex items-center gap-1 rounded-btn bg-primary-tint px-2.5 h-7 text-tag font-medium text-primary-deep hover:bg-primary-soft/50">
                          <FileText size={12} /> 报告
                        </button>
                        <button onClick={() => navigate(`/trace/${rc.id}`)}
                          className="inline-flex items-center gap-1 rounded-btn bg-bg px-2.5 h-7 text-tag font-medium text-ink-2 ring-1 ring-line hover:text-primary-deep">
                          <Network size={12} /> 决策日志
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </VCard>
            </motion.div>
          )}

          {/* 2. 目的地情报图谱 + 信源结构分析 */}
          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="lg:col-span-2">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <Radar size={16} className="text-primary" /> 目的地情报图谱
                  <span className="ml-1 text-tag text-ink-3">按情报厚度排序 · 点击下钻溯源</span>
                </div>
                <p className="mt-1 text-tag text-ink-3">
                  情报厚度 = 证据数量（深度）× 信源种类（广度）× 平均可信度（质量），帮你识别「了如指掌」与「认知盲区」
                </p>

                {destinationIntel.length === 0 ? (
                  <div className="py-10 text-center text-tag text-ink-3">尚无带目的地标注的证据</div>
                ) : (
                  <div className="mt-4 space-y-3">
                    {destinationIntel.slice(0, 8).map((b) => {
                      const active = destinationFilter === b.destination
                      return (
                        <button
                          key={b.destination}
                          onClick={() => setDestinationFilter(active ? '' : b.destination)}
                          className={`block w-full rounded-card border p-3 text-left transition-all ${
                            active ? 'border-primary-soft bg-primary-tint/50' : 'border-line/60 bg-bg hover:border-primary-soft hover:bg-card'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="flex items-center gap-1.5 text-aux font-medium text-ink">
                              <Crosshair size={13} className="text-primary" /> {b.destination}
                            </span>
                            <span className="text-tag text-ink-3">
                              {b.count} 条 · {b.sourceTypes} 类信源 · 可信 {Math.round(b.avgCred * 100)}%
                            </span>
                          </div>
                          <div className="mt-2 h-2 w-full overflow-hidden rounded-chip bg-line">
                            <div
                              className="h-full rounded-chip bg-primary transition-all"
                              style={{ width: `${Math.max(6, (b.count / maxDestinationCount) * 100)}%` }}
                            />
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}
              </VCard>
            </motion.div>

            <motion.div variants={fadeUp} initial="initial" animate="animate">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <PieChart size={16} className="text-primary" /> 信源结构分析
                </div>
                <p className="mt-1 text-tag text-ink-3">情报是否均衡，决定结论站不站得住</p>

                {/* 三类信源占比条 */}
                <div className="mt-4 flex h-3 w-full overflow-hidden rounded-chip bg-line">
                  {sourceStructure.segs.map((s) => (
                    s.pct > 0 && (
                      <div key={s.label} className={CATEGORY_COLOR[s.label]} style={{ width: `${s.pct}%` }} />
                    )
                  ))}
                </div>
                <div className="mt-3 space-y-2">
                  {sourceStructure.segs.map((s) => (
                    <div key={s.label} className="flex items-center gap-2 text-tag">
                      <span className={`h-2.5 w-2.5 rounded-sm ${CATEGORY_COLOR[s.label]}`} />
                      <span className="text-ink-2">{s.label}</span>
                      <span className="ml-auto text-ink-3">{s.n} 条 · {s.pct}%</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 rounded-card border-l-2 border-primary bg-primary-tint/40 p-3">
                  <div className="flex items-center gap-1.5 text-tag font-semibold text-primary-deep">
                    <TrendingUp size={13} /> 结构研判
                  </div>
                  <p className="mt-1 text-tag leading-relaxed text-ink-2">{sourceStructure.insight}</p>
                </div>
              </VCard>
            </motion.div>
          </div>

          {/* 3. 全局证据溯源库 + 目的地持续追踪 */}
          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="lg:col-span-2">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <Search size={16} className="text-primary" /> 全局证据溯源库
                  <span className="ml-1 text-tag text-ink-3">共 {ev.facets.total} 条 · 当前 {filteredEv.length} 条</span>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <FilterChip active={!destinationFilter && !typeFilter}
                    onClick={() => { setDestinationFilter(''); setTypeFilter('') }} label="全部" />
                  {facetDestinations.map(([b, n]) => (
                    <FilterChip key={b} active={destinationFilter === b}
                      onClick={() => setDestinationFilter(destinationFilter === b ? '' : b)} label={`${b} ${n}`} />
                  ))}
                  {facetTypes.map(([t, n]) => (
                    <FilterChip key={t} active={typeFilter === t}
                      onClick={() => setTypeFilter(typeFilter === t ? '' : t)} label={`${sourceLabel(t)} ${n}`} />
                  ))}
                </div>

                <div className="mt-4 max-h-[420px] space-y-2 overflow-y-auto pr-1">
                  {filteredEv.length === 0 ? (
                    <div className="py-8 text-center text-tag text-ink-3">暂无匹配证据</div>
                  ) : filteredEv.map((it) => (
                    <a
                      key={it.evidence_id}
                      href={it.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="group block rounded-card border border-line/60 bg-bg p-3 transition-all hover:border-primary-soft hover:bg-card"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="line-clamp-1 text-aux font-medium text-ink">{it.title || it.domain}</div>
                          <p className="mt-0.5 line-clamp-2 text-tag text-ink-3">{it.excerpt}</p>
                        </div>
                        <ExternalLink size={14} className="mt-1 shrink-0 text-ink-3 group-hover:text-primary" />
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-tag text-ink-3">
                        <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-primary-deep">{sourceLabel(it.source_type)}</span>
                        {it.destination && <span className="rounded-chip bg-sun-soft/50 px-2 py-0.5">{it.destination}</span>}
                        <span className="truncate">{it.domain}</span>
                        <span className="ml-auto">可信度 {Math.round(it.credibility * 100)}%</span>
                      </div>
                    </a>
                  ))}
                </div>
              </VCard>
            </motion.div>

            <motion.div variants={fadeUp} initial="initial" animate="animate">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <Bell size={16} className="text-primary" /> 目的地持续追踪
                </div>
                <p className="mt-1 text-tag text-ink-3">订阅一个目的地主题，一键复跑获取最新动态</p>

                <div className="mt-3 flex gap-2">
                  <input
                    value={subQuery}
                    onChange={(e) => setSubQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCreateSub()}
                    placeholder="如：三亚 亲子游攻略"
                    className="h-10 flex-1 rounded-btn border border-line bg-bg px-3 text-aux text-ink outline-none focus:border-primary-soft"
                  />
                  <button
                    onClick={handleCreateSub}
                    className="grid h-10 w-10 place-items-center rounded-btn bg-primary text-white hover:bg-primary-deep"
                  >
                    <BellPlus size={16} />
                  </button>
                </div>

                <div className="mt-4 space-y-2">
                  {subs.length === 0 ? (
                    <div className="py-6 text-center text-tag text-ink-3">还没有追踪订阅</div>
                  ) : subs.map((s) => (
                    <div key={s.sub_id} className="rounded-card border border-line/60 bg-bg p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="line-clamp-2 text-aux font-medium text-ink">{s.query}</div>
                        <button onClick={() => handleDeleteSub(s.sub_id)}
                          className="shrink-0 text-ink-3 hover:text-warn">
                          <Trash2 size={14} />
                        </button>
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-tag text-ink-3">
                        <span>已复跑 {s.run_count} 次</span>
                        {s.last_report_id && (
                          <button onClick={() => navigate(`/report/${s.last_report_id}`)}
                            className="text-primary-deep hover:underline">查看最近报告</button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {subDelError && (
                  <div className="mt-3 flex items-start gap-2 rounded-card border border-warn/40 bg-red-50 px-3 py-2 text-tag text-warn">
                    <Activity size={14} className="mt-0.5 shrink-0" />
                    <span>删除失败：{subDelError}</span>
                  </div>
                )}
              </VCard>
            </motion.div>
          </div>

          {/* 4. 专家贡献（精简） */}
          {activeWorkload.length > 0 && (
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="mt-6">
              <VCard hover={false}>
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  <Users size={16} className="text-primary" /> 专家贡献榜
                  <span className="ml-1 text-tag text-ink-3">按真实参与任务量排序</span>
                </div>
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {activeWorkload.map((w) => (
                    <button
                      key={w.id}
                      onClick={() => navigate(`/experts/${w.id}`)}
                      className="flex items-center gap-3 rounded-card border border-line/60 bg-bg p-3 text-left transition-all hover:border-primary-soft hover:bg-card"
                    >
                      <img src={w.avatar} alt={w.name}
                        className="h-10 w-10 rounded-full object-cover"
                        onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-aux font-medium text-ink">{w.name}</span>
                          <span className="rounded-chip bg-primary-tint px-1.5 text-tag text-primary-deep">{w.layer}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-tag text-ink-3">
                          <span className="inline-flex items-center gap-1"><Layers size={11} /> {w.missions} 任务</span>
                          <span className="inline-flex items-center gap-1"><Activity size={11} /> {w.claims_authored} 结论</span>
                          <span className="inline-flex items-center gap-1"><Database size={11} /> {w.evidence_collected} 证据</span>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </VCard>
            </motion.div>
          )}
        </>
      )}
    </div>
  )
}

function StatCard({ icon: Icon, value, label, tip, unit, color = 'text-primary' }: {
  icon: typeof FileText
  value: number
  label: string
  tip: string
  unit?: string
  color?: string
}) {
  return (
    <motion.div variants={fadeUp}>
      <VCard hover={false}>
        <span className={`grid h-9 w-9 place-items-center rounded-btn bg-primary-tint ${color}`}>
          <Icon size={18} />
        </span>
        <div className="mt-3 flex items-end gap-0.5">
          <span className="font-serif text-[32px] leading-none text-ink"><VCountUp value={value} /></span>
          {unit && <span className="mb-1 text-h3 text-ink-2">{unit}</span>}
        </div>
        <div className="mt-1 text-aux font-medium text-ink">{label}</div>
        <p className="mt-1 text-tag leading-relaxed text-ink-3">{tip}</p>
      </VCard>
    </motion.div>
  )
}

function ImpactCard({ icon: Icon, value, label, tip, unit, color = 'text-primary' }: {
  icon: typeof FileText
  value: number
  label: string
  tip: string
  unit?: string
  color?: string
}) {
  return (
    <div className="rounded-card border border-line/60 bg-bg p-4" title={tip}>
      <span className={`grid h-8 w-8 place-items-center rounded-btn bg-primary-tint ${color}`}>
        <Icon size={16} />
      </span>
      <div className="mt-2.5 flex items-end gap-0.5">
        <span className="font-serif text-[26px] leading-none text-ink"><VCountUp value={value} /></span>
        {unit && <span className="mb-0.5 text-aux text-ink-2">{unit}</span>}
      </div>
      <div className="mt-1 text-tag font-medium text-ink-2">{label}</div>
    </div>
  )
}

function Mini({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-btn bg-card/60 py-1.5">
      <div className={`text-aux font-semibold ${accent ? 'text-primary-deep' : 'text-ink'}`}>{value}</div>
      <div className="text-tag text-ink-3">{label}</div>
    </div>
  )
}

function FilterChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-chip px-3 py-1 text-tag transition-colors ${
        active ? 'bg-primary text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
      }`}
    >
      {label}
    </button>
  )
}

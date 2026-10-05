import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ChevronLeft, BookText, Sparkles, Target, Award } from 'lucide-react'
import { EXPERT_DOMAINS, useExpertStore, type ExpertDomainName } from '../store/expertStore'
import { fetchWorkload } from '../lib/api'
import type { ExpertWorkload } from '../types'
import { DomainIcon } from '../components/DomainIcon'
import { VCard } from '../components/ui'

/** zustand selector 必须返回稳定引用，否则每次渲染都触发重渲染。 */
const EMPTY: never[] = []

/** 等级说明随域：L1 在旅游域是「行业 / 职能」，在生活圈域才是「设施 / 方法」。 */
const LEVEL_LABEL: Record<ExpertDomainName, Record<string, string>> = {
  travel: {
    L1: '执行层 · 行业 / 职能',
    L2: '策略层 · 规划顾问',
    L3: '决策层 · 统筹签发',
  },
  living_circle: {
    L1: '执行层 · 设施场景 / 方法执行',
    L2: '策略层 · 领域顾问',
    L3: '决策层 · 统筹签发',
  },
}

export default function ExpertDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // 同一个 id 在两本名册里是**两个人**（48 个 id 完全重叠）⇒ 详情页必须知道自己看的是哪一域，
  // 域从 URL 来（专家墙跳转时带上），分享链接才不会把生活圈的人渲染成旅游人设。
  const domain: ExpertDomainName = (EXPERT_DOMAINS as readonly string[]).includes(params.get('domain') ?? '')
    ? (params.get('domain') as ExpertDomainName)
    : 'travel'
  const byId = useExpertStore((s) => s.byId)
  const load = useExpertStore((s) => s.load)
  const experts = useExpertStore((s) => s.expertsByDomain[domain] ?? EMPTY)
  const [workload, setWorkload] = useState<ExpertWorkload[]>([])
  const expert = id ? byId(id, domain) : undefined

  useEffect(() => {
    void load(domain)
  }, [load, domain])
  useEffect(() => {
    // 出工数据只认真实累计值：名册 JSON 里写死的 stats 是虚构的（两域同为 119），
    // 展示它等于把"我们不知道这个人干过多少活"伪装成知道。
    let alive = true
    fetchWorkload(domain).then((r) => alive && setWorkload(r)).catch(() => alive && setWorkload([]))
    return () => { alive = false }
  }, [domain])

  if (!expert) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-ink-2">
        <p>未找到该专家</p>
        <button onClick={() => navigate(`/experts?domain=${domain}`)} className="rounded-btn bg-primary px-5 h-10 text-aux font-medium text-white">
          返回专家团
        </button>
      </div>
    )
  }

  const peers = experts.filter((e) => e.group === expert.group && e.id !== expert.id).slice(0, 6)
  const stat = workload.find((w) => w.id === expert.id)
  const hasWork = !!stat && (stat.missions > 0 || stat.claims_authored > 0 || stat.evidence_collected > 0)

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <button
        onClick={() => navigate(`/experts?domain=${domain}`)}
        className="inline-flex items-center gap-1.5 text-aux text-ink-2 transition-colors hover:text-primary-deep"
      >
        <ChevronLeft size={16} /> 返回专家团
      </button>

      {/* 头部 */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="mt-5 flex items-center gap-6 rounded-card border border-line/60 bg-card p-7 shadow-card"
      >
        <div className="relative shrink-0">
          <img src={expert.avatar} alt={expert.name} className="h-28 w-28 rounded-card object-cover shadow-float" />
          <span className="absolute -bottom-2 -right-2 grid h-9 w-9 place-items-center rounded-full bg-card text-primary shadow-card">
            <DomainIcon name={expert.domain_icon} size={18} />
          </span>
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="font-serif text-h1 text-ink">{expert.name}</h1>
            <span className="rounded-chip px-2.5 h-6 text-tag font-medium text-ink-2" style={{ background: expert.badge_color }}>
              {expert.level}
            </span>
          </div>
          <div className="mt-1 text-body text-primary-deep">{expert.role_title}</div>
          <div className="text-tag text-ink-3">{LEVEL_LABEL[domain][expert.level]}</div>
          <p className="mt-3 text-aux leading-relaxed text-ink-2">{expert.one_liner}</p>
        </div>
      </motion.div>

      {/* 详情网格 */}
      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2">
        <VCard hover={false}>
          <div className="flex items-center gap-2 text-aux font-semibold text-ink">
            <Sparkles size={16} className="text-primary" /> 核心技能
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {expert.skills.map((s) => (
              <span key={s} className="rounded-chip bg-primary-tint px-3 h-7 text-tag font-medium text-primary-deep">
                {s}
              </span>
            ))}
          </div>
        </VCard>

        <VCard hover={false}>
          <div className="flex items-center gap-2 text-aux font-semibold text-ink">
            <Target size={16} className="text-primary" /> 知识标签
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {expert.knowledge_tags.map((t) => (
              <span key={t} className="rounded-chip border border-line px-3 h-7 text-tag text-ink-2">
                {t}
              </span>
            ))}
          </div>
        </VCard>

        <VCard hover={false} className="md:col-span-2">
          <div className="flex items-center gap-2 text-aux font-semibold text-ink">
            <BookText size={16} className="text-primary" /> 知识库
          </div>
          <p className="mt-3 text-body leading-relaxed text-ink-2">{expert.knowledge_base}</p>
        </VCard>

        {/* 履历只认真实累计值。原先这里读名册 JSON 写死的 `stats.missions/avg_evidence`
            —— 两本名册同为 119，是编的；把它当数据展示，等于把"我们不知道这个人干过多少活"
            伪装成知道。取不到出工记录时**整块不出现**（不印 0，与逐格台账同一口径）。 */}
        {hasWork && stat && (
          <VCard hover={false} className="md:col-span-2">
            <div className="flex items-center gap-2 text-aux font-semibold text-ink">
              <Award size={16} className="text-primary" /> 履历
            </div>
            <div className="mt-3 flex gap-8">
              <div>
                <div className="font-serif text-h2 text-primary-deep">{stat.missions}</div>
                <div className="text-tag text-ink-3">{domain === 'living_circle' ? '累计参与体检' : '累计参与调研'}</div>
              </div>
              <div>
                <div className="font-serif text-h2 text-primary-deep">{stat.claims_authored}</div>
                <div className="text-tag text-ink-3">署名论点</div>
              </div>
              <div>
                <div className="font-serif text-h2 text-primary-deep">{stat.evidence_collected}</div>
                <div className="text-tag text-ink-3">采集证据</div>
              </div>
            </div>
          </VCard>
        )}
      </div>

      {/* 同组专家 */}
      {peers.length > 0 && (
        <div className="mt-8">
          <div className="mb-3 text-aux font-semibold text-ink">同组协作专家</div>
          <div className="flex flex-wrap gap-3">
            {peers.map((p) => (
              <button
                key={p.id}
                onClick={() => navigate(`/experts/${p.id}`)}
                className="flex items-center gap-2.5 rounded-card border border-line/60 bg-card p-2.5 pr-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float"
              >
                <img src={p.avatar} alt={p.name} className="h-9 w-9 rounded-full object-cover" />
                <div className="text-left">
                  <div className="text-aux font-medium text-ink">{p.name}</div>
                  <div className="text-tag text-ink-3">{p.nickname}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

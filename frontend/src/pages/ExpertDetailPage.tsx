import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ChevronLeft, BookText, Sparkles, Target, Award } from 'lucide-react'
import { useExpertStore } from '../store/expertStore'
import { DomainIcon } from '../components/DomainIcon'
import { VCard } from '../components/ui'

const LEVEL_LABEL: Record<string, string> = {
  L1: '执行层 · 设施场景 / 方法执行',
  L2: '策略层 · 规划顾问',
  L3: '决策层 · 统筹签发',
}

export default function ExpertDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const byId = useExpertStore((s) => s.byId)
  const experts = useExpertStore((s) => s.experts)
  const expert = id ? byId(id) : undefined

  if (!expert) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-ink-2">
        <p>未找到该专家</p>
        <button onClick={() => navigate('/experts')} className="rounded-btn bg-primary px-5 h-10 text-aux font-medium text-white">
          返回专家团
        </button>
      </div>
    )
  }

  const peers = experts.filter((e) => e.group === expert.group && e.id !== expert.id).slice(0, 6)

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <button
        onClick={() => navigate('/experts')}
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
          <div className="text-tag text-ink-3">{LEVEL_LABEL[expert.level]}</div>
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

        <VCard hover={false} className="md:col-span-2">
          <div className="flex items-center gap-2 text-aux font-semibold text-ink">
            <Award size={16} className="text-primary" /> 履历
          </div>
          <div className="mt-3 flex gap-8">
            <div>
              <div className="font-serif text-h2 text-primary-deep">{expert.stats.missions}</div>
              <div className="text-tag text-ink-3">累计参与体检</div>
            </div>
            <div>
              <div className="font-serif text-h2 text-primary-deep">{expert.stats.avg_evidence || '—'}</div>
              <div className="text-tag text-ink-3">平均点位溯源</div>
            </div>
          </div>
        </VCard>
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

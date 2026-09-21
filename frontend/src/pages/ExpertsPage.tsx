import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Search } from 'lucide-react'
import { useExpertStore } from '../store/expertStore'
import { DomainIcon } from '../components/DomainIcon'
import { fadeUp, stagger } from '../lib/motion'
import type { Expert, ExpertLevel } from '../types'

const LEVEL_TABS: { key: ExpertLevel | 'all'; label: string; desc: string }[] = [
  { key: 'all', label: '全部', desc: '48 位专家' },
  { key: 'L3', label: '决策层', desc: '3 位 · 统筹终审' },
  { key: 'L2', label: '策略层', desc: '9 位 · 方法顾问' },
  { key: 'L1', label: '执行层', desc: '36 位 · 行业职能' },
]

const LEVEL_BG: Record<ExpertLevel, string> = {
  L1: 'bg-[#EAF1EA]',
  L2: 'bg-[#FBF6E9]',
  L3: 'bg-[#F4E2B8]',
}

function ExpertCard({ expert, onClick }: { expert: Expert; onClick: () => void }) {
  return (
    <motion.button
      variants={fadeUp}
      onClick={onClick}
      className="group relative flex flex-col items-center rounded-card border border-line/60 bg-card p-4 text-center shadow-card transition-all hover:-translate-y-1 hover:shadow-float"
    >
      <span className={`absolute right-2.5 top-2.5 inline-flex items-center gap-1 rounded-chip px-2 h-5 text-tag font-medium text-ink-2 ${LEVEL_BG[expert.level]}`}>
        {expert.level}
      </span>
      <div className="relative">
        <img
          src={expert.avatar}
          alt={expert.name}
          className="h-16 w-16 rounded-full object-cover shadow-card ring-2 ring-card"
        />
        <span className="absolute -bottom-1 -right-1 grid h-6 w-6 place-items-center rounded-full bg-card text-primary shadow-card">
          <DomainIcon name={expert.domain_icon} size={13} />
        </span>
      </div>
      <div className="mt-3 text-aux font-semibold text-ink">{expert.name}</div>
      <div className="text-tag text-primary-deep">{expert.nickname}</div>
      <p className="mt-1.5 line-clamp-2 text-tag leading-relaxed text-ink-3">{expert.one_liner}</p>
    </motion.button>
  )
}

export default function ExpertsPage() {
  const navigate = useNavigate()
  const experts = useExpertStore((s) => s.experts)
  const [tab, setTab] = useState<ExpertLevel | 'all'>('all')
  const [kw, setKw] = useState('')

  const filtered = useMemo(() => {
    return experts.filter((e) => {
      const okLevel = tab === 'all' || e.level === tab
      const okKw =
        !kw ||
        e.name.includes(kw) ||
        e.role_title.includes(kw) ||
        e.knowledge_tags.some((t) => t.includes(kw)) ||
        e.skills.some((s) => s.includes(kw))
      return okLevel && okKw
    })
  }, [experts, tab, kw])

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-h1 text-ink">专家公会</h1>
        <p className="text-aux text-ink-2">48 位 AI 旅游调研专家 · 三层协作架构 · 决策 / 策略 / 执行</p>
      </header>

      {/* 搜索 + tab */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-btn border border-line bg-card px-3 h-10 shadow-card">
          <Search size={16} className="text-ink-3" />
          <input
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            placeholder="搜索专家、技能或知识标签"
            className="w-56 bg-transparent text-aux text-ink outline-none placeholder:text-ink-3"
          />
        </div>
        <div className="flex gap-1.5">
          {LEVEL_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex flex-col items-start rounded-btn px-3.5 py-1.5 text-left transition-all ${
                tab === t.key ? 'bg-primary text-white shadow-card' : 'bg-card text-ink-2 hover:bg-primary-tint'
              }`}
            >
              <span className="text-aux font-medium leading-tight">{t.label}</span>
              <span className={`text-tag ${tab === t.key ? 'text-white/80' : 'text-ink-3'}`}>{t.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 卡片网格 */}
      <motion.div
        key={tab + kw}
        variants={stagger}
        initial="initial"
        animate="animate"
        className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6"
      >
        {filtered.map((e) => (
          <ExpertCard key={e.id} expert={e} onClick={() => navigate(`/experts/${e.id}`)} />
        ))}
      </motion.div>

      {filtered.length === 0 && (
        <div className="py-16 text-center text-ink-3">未找到匹配的专家</div>
      )}
    </div>
  )
}

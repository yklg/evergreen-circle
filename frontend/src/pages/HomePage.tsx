import { useEffect, useMemo, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowUp,
  Paperclip,
  ChevronDown,
  Cpu,
  Sparkles,
  Compass,
  Building2,
  Car,
  BedDouble,
  Route,
  UtensilsCrossed,
  Wallet,
  TrendingUp,
  Laptop,
  ShieldCheck,
  Sparkle,
  Sprout,
  Zap,
  Gem,
  Crown,
} from 'lucide-react'
import { VSunGlow } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'
import { useUIStore } from '../store/uiStore'
import { useExpertStore } from '../store/expertStore'
import { createTask, fetchResearchTypes } from '../lib/api'
import { useSettingsStore } from '../store/settingsStore'
import { useProfileStore } from '../store/profileStore'
import { findProviderByBaseUrl } from '../lib/llmProviders'
import { candidatesFor } from '../lib/modelResolution'
import type { ResearchTypeOption } from '../types'

const MODE_OPTIONS = [
  { key: 'quick', icon: Zap, label: '快速', desc: '5 章 · 约 2 分钟 · 速览' },
  { key: 'deep', icon: Gem, label: '深度', desc: '9 章 · 约 4 分钟 · 含返工闭环' },
  { key: 'expert', icon: Crown, label: '专家级', desc: '12+ 章 · 约 6-8 分钟 · 创新板块+最深' },
]

/* 类型 → 图标（文案来自后端注册表，此处只做视觉映射；未知类型回落首图） */
const TYPE_ICONS: Record<string, typeof Compass> = {
  guide: Compass,
  assessment: Building2,
}

/* 类型 → 示例问题（示例是前端体验资产，随类型切换） */
const EXAMPLES: Record<string, { icon: typeof Car; title: string; desc: string; q: string }[]> = {
  guide: [
    {
      icon: Route,
      title: '亲子路线规划',
      desc: '大理 5 天怎么玩，含逐日行程与节奏安排',
      q: '帮我做一份大理 5 天亲子游攻略，含逐日路线、住宿区域与避坑提示',
    },
    {
      icon: BedDouble,
      title: '住宿区域选型',
      desc: '三亚住哪个区域最合适，含价格区间与踩坑点',
      q: '三亚住宿住哪个区域好？对比海棠湾、亚龙湾、大东海的优劣与价格',
    },
    {
      icon: UtensilsCrossed,
      title: '美食与预算',
      desc: '成都 4 天美食清单与人均花费拆解',
      q: '成都 4 天美食攻略：必吃清单、人均花费拆解与排队避坑',
    },
    {
      icon: Wallet,
      title: '季节与避坑',
      desc: '几月去最合适，旺季淡季差异与避坑要点',
      q: '去北海道几月份最合适？逐月气候客流差异、旺季淡季价格与避坑指南',
    },
  ],
  assessment: [
    {
      icon: Laptop,
      title: '宜居度横向对比',
      desc: '评估成都和杭州哪个更适合长期居住',
      q: '评估成都和杭州哪个更适合长期居住，主要看生活成本、配套与气候',
    },
    {
      icon: TrendingUp,
      title: '置业价值研判',
      desc: '区域房价、租售比与流动性评估',
      q: '从置业投资角度看，苏州和佛山哪个更值得买？关注价格、租售比与流动性',
    },
    {
      icon: ShieldCheck,
      title: '安全与风险画像',
      desc: '治安、自然灾害与医疗应急逐项评估',
      q: '评估海口长期居住的安全与风险：治安、台风灾害、医疗应急与生活配套',
    },
    {
      icon: Sparkle,
      title: '数字游民落地',
      desc: '网络、共享办公、居留与生活成本评估',
      q: '评估清迈作为数字游民长期落脚地：网络、共享办公、居留政策与生活成本',
    },
  ],
}

function ModelPicker() {
  const [open, setOpen] = useState(false)
  const { model, setModel } = useUIStore()
  const resp = useSettingsStore((s) => s.resp)

  // 选项 = Auto + 当前已保存的 4 个模型字段 + 命中厂商预设的候选模型（去重合并）。
  // 随 SettingsPage 保存实时刷新（store.load 后 resp 更新）。
  const options = useMemo<string[]>(() => {
    if (!resp) return ['Auto']
    const fromValues = (
      ['llm_model', 'llm_model_core', 'llm_model_aux', 'llm_model_fast'] as const
    )
      .map((k) => resp.values[k])
      .filter((v): v is string => typeof v === 'string' && v !== '')
    const preset = findProviderByBaseUrl(String(resp.values.llm_base_url ?? ''))
    const fromPreset = preset ? candidatesFor(preset, []) : []
    return ['Auto', ...Array.from(new Set([...fromValues, ...fromPreset]))]
  }, [resp])

  const defaultModel = resp?.values.llm_model
  const label =
    model === 'Auto'
      ? defaultModel
        ? `切换模型 · 默认 ${defaultModel}`
        : '切换模型'
      : model

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="切换分析模型"
        className="inline-flex items-center gap-1.5 px-3 h-9 rounded-chip bg-primary-tint text-primary-deep text-aux font-medium hover:bg-primary-soft/40 transition-colors"
      >
        <Cpu size={15} />
        <span className="max-w-[160px] truncate">{label}</span>
        <ChevronDown size={15} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute bottom-11 right-0 z-20 w-56 rounded-btn bg-card shadow-float border border-line p-1">
            <div className="px-3 pb-1 pt-1.5 text-tag text-ink-3">选择分析模型</div>
            {options.map((m) => (
              <button
                key={m}
                onClick={() => {
                  setModel(m)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between rounded-lg px-3 h-9 text-aux transition-colors hover:bg-primary-tint ${
                  model === m ? 'text-primary-deep font-medium' : 'text-ink-2'
                }`}
              >
                {m === 'Auto' ? 'Auto（智能编排）' : m}
                {m === 'Auto' && <span className="text-tag text-ink-3">默认</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [mode, setMode] = useState('deep')
  const [rtype, setRtype] = useState('')
  const [types, setTypes] = useState<ResearchTypeOption[]>([])
  const [typesFailed, setTypesFailed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const experts = useExpertStore((s) => s.experts)
  const wall = experts.slice(0, 14)
  const profile = useProfileStore()
  const avatarInitial = (profile.name || '研').trim().slice(0, 1) || '研'

  // 类型卡片文案来自 GET /api/research-types（后端注册表单一真相源，前端不复制）。
  // 接口不可用时整站本就不可用，因此显式暴露错误态而不是静默兜底默认类型。
  useEffect(() => {
    let alive = true
    fetchResearchTypes().then((items) => {
      if (!alive) return
      if (items.length === 0) {
        setTypesFailed(true)
        return
      }
      setTypes(items)
      setRtype((cur) => cur || items[0].key)
    })
    return () => {
      alive = false
    }
  }, [])

  async function submit(q: string) {
    const query = q.trim()
    if (!query || submitting || !rtype || typesFailed) return
    setSubmitting(true)
    try {
      // Auto = 不覆盖（走 settings 编排）；否则把用户选的模型透传后端 override
      const selectedModel = useUIStore.getState().model
      const modelOverride = selectedModel !== 'Auto' ? selectedModel : null
      const resp = await createTask(query, mode, modelOverride, rtype)
      // 永远进 clarify：问卷在 ClarifyPage 内通过 SSE 懒生成（根治「提交后等好久」）
      navigate(`/clarify/${resp.taskId}`, { state: { query } })
    } finally {
      setSubmitting(false)
    }
  }

  const examples = EXAMPLES[rtype] ?? []

  return (
    <div className="relative min-h-full overflow-hidden">
      {/* 叶影暖阳氛围层 */}
      <div
        className="pointer-events-none absolute inset-0 -z-0 opacity-[0.5]"
        style={{
          backgroundImage: 'url(/assets/brand/hero-bg.png)',
          backgroundSize: 'cover',
          backgroundPosition: 'right top',
          maskImage: 'linear-gradient(to bottom, rgba(0,0,0,1), rgba(0,0,0,0) 70%)',
          WebkitMaskImage: 'linear-gradient(to bottom, rgba(0,0,0,1), rgba(0,0,0,0) 70%)',
        }}
      />
      <VSunGlow className="opacity-40" />

      {/* 顶部右上：what's new + 头像 */}
      <div className="relative z-10 flex items-center justify-between px-8 pt-6">
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card/80 px-3 h-9 text-aux text-ink-2 backdrop-blur">
          <Sparkles size={14} className="text-primary" /> 新功能上线
        </span>
        <span className="grid h-9 w-9 place-items-center rounded-full bg-primary text-aux font-semibold text-white">
          {avatarInitial}
        </span>
      </div>

      {/* Hero 主体 */}
      <div className="relative z-10 mx-auto flex min-h-[calc(100vh-80px)] max-w-[820px] flex-col items-center justify-center px-6 pb-20">
        <motion.h1
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="text-center font-serif text-[44px] leading-tight text-ink"
        >
          下午好，{profile.name}
          <span className="ml-2 inline-block align-middle">
            <Sprout className="inline text-primary" size={34} />
          </span>
        </motion.h1>
        <motion.p
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="mt-3 text-lg text-ink-2"
        >
          你的 AI 旅游调研 Agent —— 48 位专家协作，无证据不立论
        </motion.p>

        {/* 调研类型选择器（两张卡，文案来自 /api/research-types） */}
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="mt-9 grid w-full grid-cols-1 gap-4 sm:grid-cols-2"
        >
          {types.map((t) => {
            const Icon = TYPE_ICONS[t.key] ?? Compass
            const active = rtype === t.key
            return (
              <motion.button
                key={t.key}
                variants={fadeUp}
                type="button"
                onClick={() => setRtype(t.key)}
                aria-pressed={active}
                className={`flex items-start gap-3 rounded-card border-2 bg-card/80 p-4 text-left shadow-card backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-float ${
                  active ? 'border-primary' : 'border-line/60'
                }`}
              >
                <span
                  className={`grid h-10 w-10 shrink-0 place-items-center rounded-btn ${
                    active ? 'bg-primary text-white' : 'bg-primary-tint text-primary'
                  }`}
                >
                  <Icon size={20} />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-semibold text-ink">{t.label}</span>
                  <span className="mt-1 block text-tag leading-relaxed text-ink-3">{t.subtitle}</span>
                </span>
              </motion.button>
            )
          })}
          {typesFailed && (
            <p className="col-span-full text-aux text-risk" role="alert">
              调研类型加载失败，请检查后端服务后刷新页面重试。
            </p>
          )}
        </motion.div>

        {/* 大输入框 */}
        <motion.div
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="mt-6 w-full rounded-card border-2 border-transparent bg-card p-4 shadow-float transition-all focus-within:border-primary focus-within:shadow-glow"
        >
          <textarea
            ref={taRef}
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(text)
            }}
            placeholder={
              rtype === 'assessment'
                ? '想评估哪个城市/地区，以及评估用途？例如：评估成都和杭州哪个更适合长期居住，看生活成本与配套'
                : '想去哪里玩、几天、和谁一起？例如：帮我做一份大理 5 天亲子游攻略，含路线与住宿选型'
            }
            className="w-full resize-none bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          />
          {/* 调研模式三档 */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-tag text-ink-3">调研模式</span>
            {MODE_OPTIONS.map((m) => {
              const Icon = m.icon
              const active = mode === m.key
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => setMode(m.key)}
                  title={m.desc}
                  className={`inline-flex items-center gap-1.5 rounded-chip px-3 h-8 text-aux font-medium transition-colors ${
                    active ? 'bg-primary text-white' : 'bg-primary-tint/60 text-ink-2 hover:bg-primary-tint'
                  }`}
                >
                  <Icon size={14} /> {m.label}
                </button>
              )
            })}
            <span className="text-tag text-ink-3">
              {MODE_OPTIONS.find((m) => m.key === mode)?.desc}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-tag text-ink-3">48 位专家 · 真实联网 · 无证据不立论</span>
            <div className="flex items-center gap-2">
              <ModelPicker />
              <button
                title="上传附件"
                className="grid h-9 w-9 place-items-center rounded-full text-ink-3 transition-colors hover:bg-primary-tint hover:text-primary-deep"
              >
                <Paperclip size={18} />
              </button>
              <button
                onClick={() => submit(text)}
                disabled={!text.trim() || submitting || !rtype || typesFailed}
                className="grid h-11 w-11 place-items-center rounded-full bg-primary text-white shadow-card transition-all hover:scale-105 hover:bg-primary-deep active:scale-95 disabled:opacity-40 disabled:hover:scale-100"
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </div>
        </motion.div>

        {/* 示例卡（随调研类型切换） */}
        <p className="mt-9 text-aux text-ink-3">试试这些示例</p>
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          key={rtype}
          className="mt-4 grid w-full grid-cols-2 gap-4 sm:grid-cols-4"
        >
          {examples.map((ex) => (
            <motion.button
              key={ex.title}
              variants={fadeUp}
              onClick={() => submit(ex.q)}
              className="group flex flex-col rounded-card border border-line/60 bg-card/80 p-4 text-left shadow-card backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-float"
            >
              <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
                <ex.icon size={18} />
              </span>
              <span className="mt-3 text-aux font-semibold text-ink">{ex.title}</span>
              <span className="mt-1 text-tag leading-relaxed text-ink-3">{ex.desc}</span>
            </motion.button>
          ))}
        </motion.div>

        {/* 专家墙 */}
        <div className="mt-12 flex w-full flex-col items-center">
          <div className="flex items-center -space-x-2">
            {wall.map((e, i) => (
              <img
                key={e.id}
                src={e.avatar}
                alt={e.name}
                title={`${e.name} · ${e.role_title}`}
                className="h-9 w-9 rounded-full border-2 border-card object-cover shadow-card"
                style={{ zIndex: wall.length - i }}
              />
            ))}
            <button
              onClick={() => navigate('/experts')}
              className="z-0 ml-1 inline-flex h-9 items-center rounded-chip bg-primary-tint px-3 text-tag font-medium text-primary-deep hover:bg-primary-soft/40"
            >
              查看全部 48 位 →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

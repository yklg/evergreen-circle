import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowUp,
  Paperclip,
  ChevronDown,
  Cpu,
  Sparkles,
  MapPin,
  Compass,
  Building2,
  Sprout,
  Zap,
  Diamond,
  Crown,
  ArrowRight,
} from 'lucide-react'
import { VSunGlow } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'
import { useUIStore } from '../store/uiStore'
import { useSettingsStore } from '../store/settingsStore'
import { useExpertStore } from '../store/expertStore'
import { findProviderByBaseUrl } from '../lib/llmProviders'
import { candidatesFor } from '../lib/modelResolution'
import { BRAND } from '../lib/brand'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'
import { launchResearch, buildResearchQuery } from '../lib/researchFlow'
import {
  domainOf,
  submitLanding,
  type DomainType,
  type ExamplesKey,
} from '../lib/taskDomains'
import { isFixtureMode } from '../store/dataModeStore'
import { fetchResearchTypes, type ResearchTypeOption } from '../lib/researchTypesClient'

// ── 调研三档（只显档名；章数随类型/模式由注册表决定，不在此硬编码）────────
const DEPTH_OPTIONS = [
  { value: 'quick', label: '快速', icon: Zap },
  { value: 'deep', label: '深度', icon: Diamond },
  { value: 'expert', label: '专家级', icon: Crown },
] as const

// ── C5 类型感知示例（点击填入输入框，改后再提交；生活圈样例直达场景页）────
interface TravelExample {
  icon: typeof Compass
  title: string
  desc: string
  text: string
}
const TRAVEL_EXAMPLES: Record<'travelGuide' | 'travelAssess', TravelExample[]> = {
  travelGuide: [
    { icon: MapPin, title: '亲子路线规划', desc: '大理 5 天怎么玩，含逐日行程与节奏', text: '大理 5 天亲子游攻略，含逐日路线与住宿选型' },
    { icon: Building2, title: '住宿区域选型', desc: '三亚住哪个区域最合适', text: '三亚旅游住宿区域选型攻略' },
    { icon: Sparkles, title: '美食与预算', desc: '成都美食清单与花费拆解', text: '成都 4 天美食清单与预算拆解攻略' },
    { icon: Compass, title: '季节与避坑', desc: '几月去最合适，淡旺季差异', text: '大理几月去最合适？淡季旺季差异与避坑提示' },
  ],
  travelAssess: [
    { icon: Building2, title: '双城宜居对比', desc: '成都和杭州哪个更适合长期居住', text: '评估成都和杭州哪个更适合长期居住' },
    { icon: Cpu, title: '居住成本评估', desc: '房租/餐饮/通勤的月度生活成本', text: '评估在杭州长期居住的月度生活成本（房租、餐饮、通勤）' },
    { icon: Compass, title: '可达性与配套', desc: '公共交通/医疗/教育配套完善度', text: '评估苏州工业园区的交通可达性与医疗教育配套' },
    { icon: Sparkles, title: '安全与性价比', desc: '治安、风险与生活性价比综合研判', text: '评估珠海和厦门的安全性与生活性价比' },
  ],
}

function ModelPicker() {
  const [open, setOpen] = useState(false)
  const { model, setModel } = useUIStore()
  const resp = useSettingsStore((s) => s.resp)

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
        title="切换 AI 解读模型"
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
            <div className="px-3 pb-1 pt-1.5 text-tag text-ink-3">选择 AI 解读模型</div>
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
  const [domain, setDomain] = useState<DomainType>('guide')
  const [travelTypes, setTravelTypes] = useState<ResearchTypeOption[]>([])
  const [text, setText] = useState('')
  const [depth, setDepth] = useState<string>('deep')
  const [submitting, setSubmitting] = useState(false)
  const [subErr, setSubErr] = useState('')

  // C1/C2 卡片：数据来自注册表端点（演示/离线回落快照），只在域切换时取一次
  useEffect(() => {
    let cancelled = false
    void fetchResearchTypes().then((opts) => {
      if (!cancelled) setTravelTypes(opts)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const descriptor = domainOf(domain)
  const isTravel = descriptor.family === 'travel'
  const expertDomain = descriptor.expertDomain
  const { expertsByDomain, load: loadExperts } = useExpertStore()
  const domainExperts = expertsByDomain[expertDomain] ?? []
  useEffect(() => {
    void loadExperts(expertDomain)
  }, [expertDomain, loadExperts])

  function pickDomain(type: DomainType) {
    setDomain(type)
    setSubErr('')
  }

  function pickExample(t: string) {
    setText(t)
  }

  /** 旅游域：建任务 → 按数据模式落澄清问卷（真实）或工作台（演示回放）。 */
  async function submitTravel() {
    if (submitting || !text.trim()) return
    setSubmitting(true)
    setSubErr('')
    try {
      const query = buildResearchQuery(text, domain)
      const { taskId } = await launchResearch(query, depth, domain)
      navigate(submitLanding(domain, isFixtureMode() ? 'fixture' : 'live', taskId), {
        state: { query, type: domain },
      })
    } catch (e) {
      setSubErr(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  /** 生活圈域：不建任务、不经问卷，文字随 state 带到地图中心点输入（不丢字）。 */
  function submitLivingCircle() {
    navigate('/life-circle/custom', { state: { query: text.trim() } })
  }

  function handleSubmit() {
    if (isTravel) void submitTravel()
    else submitLivingCircle()
  }

  // C1/C2 注册表卡片 + C3 生活圈固定卡（虚线视觉区分）
  const travelCards = useMemo(
    () =>
      travelTypes.map((o) => ({
        type: o.key as DomainType,
        label: o.label,
        subtitle: o.subtitle,
        icon: o.key === 'guide' ? Compass : Building2,
        dashed: false,
      })),
    [travelTypes],
  )
  const lcCard = {
    type: 'living_circle' as DomainType,
    label: '15 分钟生活圈体检',
    subtitle: '等时圈 · 设施覆盖 · 盲区识别 · 双社区对比',
    icon: Sprout,
    dashed: true,
  }
  const allCards = [...travelCards, lcCard]

  const examplesKey: ExamplesKey = descriptor.examplesKey

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

      {/* 顶部：双域 what's new + 品牌 */}
      <div className="relative z-10 flex items-center justify-between px-8 pt-6">
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card/80 px-3 h-9 text-aux text-ink-2 backdrop-blur">
          <Sparkles size={14} className="text-primary" /> 旅游双类型 · 景点实体地图 · 全章可视化已上线
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card/80 px-3 h-9 text-aux text-ink-2 backdrop-blur">
          {BRAND.zh} · 双域工作台
        </span>
      </div>

      {/* Hero */}
      <div className="relative z-10 mx-auto flex min-h-[calc(100vh-80px)] max-w-[880px] flex-col items-center justify-center px-6 pb-14">
        <motion.h1
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="text-center font-serif text-[42px] leading-tight text-ink"
        >
          一个工作台，完成<span className="mx-1 text-primary-deep">旅游调研</span>与
          <span className="mx-1 text-primary">生活圈体检</span>
        </motion.h1>
        <motion.p variants={fadeUp} initial="initial" animate="animate" className="mt-3 text-base text-ink-2">
          48 位虚拟专家协作 · 真实联网溯源 · 无证据不立论
        </motion.p>

        {/* C1/C2/C3 三域卡 */}
        <motion.div variants={stagger} initial="initial" animate="animate"
          className="mt-9 grid w-full grid-cols-3 gap-3.5">
          {allCards.map((c) => {
            const Icon = c.icon
            const active = domain === c.type
            return (
              <motion.button
                key={c.type}
                variants={fadeUp}
                type="button"
                aria-pressed={active}
                onClick={() => pickDomain(c.type)}
                className={`flex items-start gap-3 rounded-card border-2 bg-card/85 p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float ${
                  active ? 'border-primary' : c.dashed ? 'border-dashed border-line' : 'border-line/80'
                }`}
              >
                <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-btn ${
                  active ? 'bg-primary text-white' : 'bg-primary-tint text-primary-deep'}`}>
                  <Icon size={20} />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-aux font-semibold text-ink">
                    {c.label}
                    {c.dashed && (
                      <span className="rounded-chip bg-primary-tint px-1.5 text-[10px] font-normal text-primary-deep">现有</span>
                    )}
                  </span>
                  <span className="mt-1 block text-tag leading-relaxed text-ink-3">{c.subtitle}</span>
                </span>
              </motion.button>
            )
          })}
        </motion.div>

        {/* C4 统一输入框 */}
        <motion.div
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="mt-5 w-full rounded-card border-2 border-primary bg-card p-4 shadow-float"
        >
          <textarea
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
            }}
            placeholder={descriptor.queryHint}
            className="w-full resize-none bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          />

          {/* 调研三档（仅旅游域；生活圈体检模式在地图页选择） */}
          {isTravel && (
            <div className="mt-2.5 flex items-center gap-2">
              <span className="text-tag text-ink-3">调研模式</span>
              {DEPTH_OPTIONS.map((o) => {
                const Icon = o.icon
                const on = depth === o.value
                return (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => setDepth(o.value)}
                    aria-pressed={on}
                    className={`inline-flex items-center gap-1.5 h-[30px] rounded-chip px-3 text-tag font-medium transition-colors ${
                      on ? 'bg-primary text-white' : 'bg-primary-tint/70 text-ink-2 hover:bg-primary-tint'
                    }`}
                  >
                    <Icon size={13} /> {o.label}
                  </button>
                )
              })}
            </div>
          )}

          <div className="mt-3 flex items-center justify-between">
            <span className="text-tag text-ink-3">
              {isTravel ? '提交后进入澄清问卷，确认后专家在线调研' : '直达生活圈地图，在地图上确认中心点发起体检'}
            </span>
            <div className="flex items-center gap-2">
              {isTravel && <ModelPicker />}
              <button
                title="上传附件（规划中）"
                className="grid h-9 w-9 place-items-center rounded-full text-ink-3 transition-colors hover:bg-primary-tint hover:text-primary-deep"
              >
                <Paperclip size={18} />
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting || !text.trim()}
                className="grid h-11 w-11 place-items-center rounded-full bg-primary text-white shadow-card transition-all hover:scale-105 hover:bg-primary-deep active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
                title={isTravel ? '开始调研' : '前往生活圈地图'}
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </div>
          {subErr && (
            <div className="mt-2 rounded-btn bg-risk/10 px-3 py-1.5 text-tag text-risk" role="alert">
              调研任务创建失败：{subErr}（请确认后端已启动）
            </div>
          )}
        </motion.div>

        {/* C5 类型感知示例 */}
        <p className="mt-8 text-aux text-ink-3">试试这些示例 · 随所选类型切换</p>
        {isTravel ? (
          <motion.div variants={stagger} initial="initial" animate="animate"
            className="mt-3 grid w-full grid-cols-4 gap-3.5">
            {TRAVEL_EXAMPLES[examplesKey === 'travelAssess' ? 'travelAssess' : 'travelGuide'].map((ex) => {
              const Icon = ex.icon
              return (
                <motion.button
                  key={ex.title}
                  variants={fadeUp}
                  type="button"
                  onClick={() => pickExample(ex.text)}
                  className="group flex flex-col rounded-card border border-line/60 bg-card/85 p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float"
                >
                  <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
                    <Icon size={18} />
                  </span>
                  <span className="mt-3 text-aux font-semibold text-ink">{ex.title}</span>
                  <span className="mt-1 text-tag leading-relaxed text-ink-3">{ex.desc}</span>
                </motion.button>
              )
            })}
          </motion.div>
        ) : (
          <motion.div variants={stagger} initial="initial" animate="animate"
            className="mt-3 grid w-full grid-cols-2 gap-3.5">
            {SAMPLE_COMMUNITIES.map((ex, i) => (
              <motion.button
                key={ex.id}
                variants={fadeUp}
                type="button"
                onClick={() => navigate(`/life-circle/${ex.id}`)}
                className="group flex flex-col rounded-card border border-dashed border-line bg-card/80 p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-primary hover:shadow-float"
              >
                <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint/70 text-primary">
                  {i === 0 ? <MapPin size={18} /> : <Building2 size={18} />}
                </span>
                <span className="mt-3 text-aux font-semibold text-ink">{ex.title}</span>
                <span className="mt-0.5 text-tag text-ink-3">{ex.city}</span>
                <span className="mt-1 text-tag leading-relaxed text-ink-3">{ex.blurb}</span>
              </motion.button>
            ))}
          </motion.div>
        )}

        {/* C6 专家墙（按域名册） */}
        <div className="mt-8 flex items-center justify-center">
          <div className="flex items-center">
            {domainExperts.slice(0, 12).map((e) => (
              <span
                key={e.id}
                title={`${e.name} · ${e.nickname ?? e.role_title ?? ''}`}
                className="-ml-2 grid h-[34px] w-[34px] place-items-center rounded-full border-2 border-card bg-primary-soft text-[11px] font-semibold text-white first:ml-0"
              >
                {e.level ?? e.id.match(/^L\d/)?.[0] ?? e.id.slice(0, 2)}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigate('/experts')}
            className="ml-2.5 inline-flex h-8 items-center gap-1 rounded-chip border border-line bg-card/80 px-3 text-tag text-ink-2 transition-colors hover:border-primary hover:text-primary-deep"
          >
            专家团按域切换 · 查看 48 位 <ArrowRight size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}

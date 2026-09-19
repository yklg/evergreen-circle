import { useState, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowUp,
  Paperclip,
  ChevronDown,
  Cpu,
  Sparkles,
  MapPin,
  Building2,
  Crosshair,
  Zap,
  Gem,
  Crown,
  Sprout,
} from 'lucide-react'
import { VSunGlow } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'
import { useUIStore } from '../store/uiStore'
import { createLivingCircleTask } from '../lib/api'
import { useSettingsStore } from '../store/settingsStore'
import { findProviderByBaseUrl } from '../lib/llmProviders'
import { candidatesFor } from '../lib/modelResolution'
import { BRAND } from '../lib/brand'
import { SAMPLE_COMMUNITIES, USE_MOCK } from '../mocks/livingCircleMock'
import type { LifeCircleMode, LngLat } from '../types'

const MODE_OPTIONS = [
  { key: 'quick', icon: Zap, label: '速览', desc: '粗扫采样 · 约 1 分钟出圈' },
  { key: 'standard', icon: Gem, label: '标准', desc: '分级采样 · 约 2 分钟出圈' },
  { key: 'precise', icon: Crown, label: '精细', desc: '边界加密 · 约 3 分钟出圈' },
]

const FEATURES = [
  '5/10/15/20 分钟等时圈',
  '民生设施覆盖体检',
  '1km 服务盲区识别',
  '双社区对比',
  'AI 诊断解读',
  '开源 · AGPL-3.0',
]

function ModelPicker() {
  const [open, setOpen] = useState(false)
  const { model, setModel } = useUIStore()
  const resp = useSettingsStore((s) => s.resp)

  // 选项 = Auto + 当前已保存的 4 个模型字段 + 命中厂商预设的候选模型（去重合并）。
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
  const [text, setText] = useState('')
  const [mode, setMode] = useState('standard')
  const [submitting, setSubmitting] = useState(false)
  const [subErr, setSubErr] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)

  /** 发起体检：F 阶段 mock 直接进生活圈地图页；M 阶段走真实编排（任务 → 工作台 SSE） */
  function startCheck(target?: string) {
    if (USE_MOCK) {
      navigate(target ? `/life-circle/${target}` : '/life-circle/kaili')
      return
    }
    if (submitting) return
    const query = text.trim() || '凯里老街'
    // 入参解析：样例卡 → 携带样例中心；坐标输入 → center=[lng,lat]；纯地名 → 仅 scene_name（后端地理编码/样例匹配兜底）
    const sample = SAMPLE_COMMUNITIES.find((c) => c.id === target)
    const m = /^\s*([\d.]+)\s*,\s*([\d.]+)\s*$/.exec(query)
    let center: LngLat | undefined
    let city = ''
    if (sample) {
      center = sample.report.scene.center
      city = sample.city
    } else if (m) {
      center = [Number(m[1]), Number(m[2])]
    }
    setSubErr('')
    setSubmitting(true)
    createLivingCircleTask({
      query: sample?.title ?? query,
      mode: mode as LifeCircleMode,
      center,
      city,
    })
      .then((r) => navigate(`/workspace/${r.taskId}`, { state: { query } }))
      .catch((e) => {
        const msg = e instanceof Error ? e.message : String(e)
        setSubErr(msg)
        setSubmitting(false)
      })
      .finally(() => setSubmitting(false))
  }

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
          <Sparkles size={14} className="text-primary" /> 1km 菜市场 / 药店 / 小学盲区识别已上线
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card/80 px-3 h-9 text-aux text-ink-2 backdrop-blur">
          {BRAND.zh}
        </span>
      </div>

      {/* Hero 主体 */}
      <div className="relative z-10 mx-auto flex min-h-[calc(100vh-80px)] max-w-[840px] flex-col items-center justify-center px-6 pb-14">
        <motion.h1
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="text-center font-serif text-[44px] leading-tight text-ink"
        >
          给社区做一次
          <span className="mx-1 text-primary">生活圈体检</span>
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
          {BRAND.tagline}
        </motion.p>

        {/* 中心点输入 */}
        <motion.div
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="mt-9 w-full rounded-card border-2 border-transparent bg-card p-4 shadow-float transition-all focus-within:border-primary focus-within:shadow-glow"
        >
          <textarea
            ref={taRef}
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) startCheck()
            }}
            placeholder="输入社区名、地名或经度,纬度（BD-09）—— 例如：凯里老街 / 107.9758,26.5734"
            className="w-full resize-none bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          />
          {/* 体检模式三档 */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-tag text-ink-3">体检模式</span>
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
            <span className="text-tag text-ink-3">真实路网测时 · POI 覆盖统计 · 示范数据可离线演示</span>
            <div className="flex items-center gap-2">
              <ModelPicker />
              <button
                title="上传附件（M 阶段开放）"
                className="grid h-9 w-9 place-items-center rounded-full text-ink-3 transition-colors hover:bg-primary-tint hover:text-primary-deep"
              >
                <Paperclip size={18} />
              </button>
              <button
                onClick={() => startCheck()}
                disabled={submitting}
                className="grid h-11 w-11 place-items-center rounded-full bg-primary text-white shadow-card transition-all hover:scale-105 hover:bg-primary-deep active:scale-95 disabled:opacity-40 disabled:hover:scale-100"
                title="开始生活圈体检"
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </div>
          {subErr && (
            <div className="mt-2 rounded-btn bg-risk/10 px-3 py-1.5 text-tag text-risk" role="alert">
              体检任务创建失败：{subErr}（请确认后端已启动）
            </div>
          )}
        </motion.div>

        {/* 样例社区 + 自定义中心点 */}
        <p className="mt-9 text-aux text-ink-3">内置双样例 · 或自定义中心点</p>
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="mt-4 grid w-full grid-cols-2 gap-4 sm:grid-cols-3"
        >
          {SAMPLE_COMMUNITIES.map((ex, i) => (
            <motion.button
              key={ex.id}
              variants={fadeUp}
              onClick={() => startCheck(ex.id)}
              className="group flex flex-col rounded-card border border-line/60 bg-card/80 p-4 text-left shadow-card backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-float"
            >
              <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
                {i === 0 ? <MapPin size={18} /> : <Building2 size={18} />}
              </span>
              <span className="mt-3 text-aux font-semibold text-ink">{ex.title}</span>
              <span className="mt-0.5 text-tag text-ink-3">{ex.city}</span>
              <span className="mt-1 text-tag leading-relaxed text-ink-3">{ex.blurb}</span>
            </motion.button>
          ))}
          <motion.button
            variants={fadeUp}
            onClick={() => startCheck('custom')}
            className="group flex flex-col rounded-card border border-dashed border-line bg-card/60 p-4 text-left shadow-card backdrop-blur transition-all hover:-translate-y-0.5 hover:border-primary hover:shadow-float"
          >
            <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint/60 text-primary">
              <Crosshair size={18} />
            </span>
            <span className="mt-3 text-aux font-semibold text-ink">自定义中心点</span>
            <span className="mt-0.5 text-tag text-ink-3">任意城市 · 任意坐标</span>
            <span className="mt-1 text-tag leading-relaxed text-ink-3">在地图点选或输入坐标，立即体检</span>
          </motion.button>
        </motion.div>

        {/* 能力指示条 */}
        <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
          {FEATURES.map((f) => (
            <span
              key={f}
              className="rounded-chip border border-line/70 bg-primary-tint/30 px-3 h-7 text-tag font-medium text-ink-2"
            >
              {f}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
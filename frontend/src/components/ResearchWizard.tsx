import { useState } from 'react'
import { ChevronLeft, ChevronRight, Sprout, Sparkles, X } from 'lucide-react'

export type ResearchOut = 'guide' | 'assess'
export type ResearchDepth = 'quick' | 'deep' | 'expert'

const TYPE_OPTIONS: { value: ResearchOut; label: string; desc: string }[] = [
  { value: 'guide', label: '游玩攻略', desc: '交通 · 住宿 · 路线 · 美食 · 预算' },
  { value: 'assess', label: '调研评估', desc: '可达性 · 配套 · 安全 · 性价比' },
]

const DEPTH_OPTIONS: { value: ResearchDepth; label: string; desc: string }[] = [
  { value: 'quick', label: '快速', desc: '约 1 分钟 · 轻量结论' },
  { value: 'deep', label: '深度', desc: '约 2 分钟 · 多维度论证' },
  { value: 'expert', label: '专家级', desc: '约 3 分钟 · 逐项核查' },
]

const STEP_LABELS = ['报告类型', '调研深度', '确认']
// guide→攻略 / assess→评估，用于第 3 步确认摘要
const OUT_LABEL: Record<ResearchOut, string> = { guide: '攻略', assess: '评估' }
const DEPTH_LABEL: Record<ResearchDepth, string> = {
  quick: '快速',
  deep: '深度',
  expert: '专家级',
}

interface Props {
  open: boolean
  place: string
  onClose: () => void
  onLaunch: (out: ResearchOut, depth: ResearchDepth) => void
}

export default function ResearchWizard({ open, place, onClose, onLaunch }: Props) {
  const [step, setStep] = useState(0)
  const [out, setOut] = useState<ResearchOut>('guide')
  const [depth, setDepth] = useState<ResearchDepth>('deep')

  if (!open) return null

  const summary = `目的地「${place}」 · ${OUT_LABEL[out]}报告 · ${DEPTH_LABEL[depth]}调研`

  function next() {
    if (step < 2) setStep(step + 1)
    else onLaunch(out, depth)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-md rounded-card bg-card p-6 shadow-float">
        {/* 标题 + 关闭 */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
              <Sprout size={18} strokeWidth={1.8} />
            </span>
            <div>
              <div className="text-aux font-semibold text-ink">目的地调研 · 分步问答</div>
              <div className="text-tag text-ink-3">目标：{place}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
            className="text-ink-3 transition-colors hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        {/* 进度点 */}
        <div className="mt-4 flex items-center gap-2">
          {STEP_LABELS.map((l, i) => (
            <div
              key={l}
              className={`h-1.5 flex-1 rounded-full transition-colors ${i <= step ? 'bg-primary' : 'bg-line'}`}
            />
          ))}
        </div>
        <div className="mt-1.5 flex justify-between text-tag text-ink-3">
          {STEP_LABELS.map((l, i) => (
            <span key={l} className={i === step ? 'font-medium text-primary' : ''}>
              {i + 1}. {l}
            </span>
          ))}
        </div>

        {/* 步骤体 */}
        <div className="mt-5 min-h-[220px]">
          {step === 0 && (
            <>
              <div className="text-aux text-ink">你想让我为你产出一份什么？</div>
              <div className="mt-3 space-y-2">
                {TYPE_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => setOut(o.value)}
                    className={`flex w-full items-center justify-between rounded-btn border px-4 py-3 text-left transition-colors ${
                      out === o.value
                        ? 'border-primary bg-primary-tint text-primary-deep'
                        : 'border-line bg-card hover:bg-primary-tint/40'
                    }`}
                  >
                    <span>
                      <span className="block text-aux font-medium text-ink-2">{o.label}</span>
                      <span className="mt-0.5 block text-tag text-ink-3">{o.desc}</span>
                    </span>
                    {out === o.value && <Sparkles size={16} className="text-primary" />}
                  </button>
                ))}
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="text-aux text-ink">这次调研要多深入？</div>
              <div className="mt-3 space-y-2">
                {DEPTH_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => setDepth(o.value)}
                    className={`flex w-full items-center justify-between rounded-btn border px-4 py-3 text-left transition-colors ${
                      depth === o.value
                        ? 'border-primary bg-primary-tint text-primary-deep'
                        : 'border-line bg-card hover:bg-primary-tint/40'
                    }`}
                  >
                    <span>
                      <span className="block text-aux font-medium text-ink-2">{o.label}</span>
                      <span className="mt-0.5 block text-tag text-ink-3">{o.desc}</span>
                    </span>
                    {depth === o.value && <Sparkles size={16} className="text-primary" />}
                  </button>
                ))}
              </div>
            </>
          )}

          {step === 2 && (
            <div className="rounded-btn border border-line bg-primary-tint/30 p-4">
              <div className="flex items-center gap-2 text-aux font-medium text-primary-deep">
                <Sparkles size={16} /> 确认发起
              </div>
              <p className="mt-3 text-aux text-ink">{summary}</p>
              <p className="mt-2 text-tag text-ink-3">
                发起后将进入多角色专家 + LLM 在线调研，实时生成{OUT_LABEL[out]}报告。
              </p>
            </div>
          )}
        </div>

        {/* 底部导航 */}
        <div className="mt-5 flex items-center justify-between gap-2">
          {step === 0 ? (
            <span className="text-tag text-ink-3" />
          ) : (
            <button
              type="button"
              onClick={() => setStep(step - 1)}
              className="inline-flex h-9 items-center gap-1 rounded-btn border border-line px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint/40"
            >
              <ChevronLeft size={16} /> 上一步
            </button>
          )}
          <button
            type="button"
            onClick={next}
            className="inline-flex h-9 items-center gap-1 rounded-btn bg-primary px-4 text-aux font-medium text-white transition-colors hover:bg-primary-deep"
          >
            {step === 2 ? '发起调研' : '下一步'} <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
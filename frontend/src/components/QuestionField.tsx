import type { ClarifyQuestion } from '../types'

interface QuestionFieldProps {
  question: ClarifyQuestion
  value: unknown
  onChange: (next: unknown) => void
  // 仅 competitors 等需要补充自定义的题传入；三个齐备才渲染「补充」输入
  customInput?: string
  onCustomInputChange?: (v: string) => void
  onCustomAdd?: () => void
}

/**
 * 单题控件（受控、纯展示）。
 * 向导单步视图与核对屏共用此组件，杜绝「两套控件逻辑」漂移。
 * 覆盖 single / multi / text / slider 四种题型；competitors 等自定义补充经可选 props 透传。
 */
export default function QuestionField({
  question,
  value,
  onChange,
  customInput,
  onCustomInputChange,
  onCustomAdd,
}: QuestionFieldProps) {
  const { type, options = [] } = question

  if (type === 'text') {
    return (
      <textarea
        rows={2}
        value={(value as string) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder="选填，可补充背景信息"
        className="mt-3 w-full resize-none rounded-btn border border-line bg-bg px-3 py-2 text-aux text-ink outline-none transition-colors focus:border-primary"
      />
    )
  }

  if (type === 'slider') {
    const num = typeof value === 'number' ? value : 0
    return (
      <div className="mt-3">
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={num}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-primary"
        />
        <div className="mt-1 text-tag text-ink-3">当前值：{num}</div>
      </div>
    )
  }

  // single / multi 共用的 chips 渲染
  const selected = type === 'multi' ? ((value as string[]) ?? []) : []
  const chips =
    type === 'multi' ? Array.from(new Set([...options, ...selected])) : options

  const isSelected = (opt: string) =>
    type === 'single' ? value === opt : selected.includes(opt)

  const handleClick = (opt: string) => {
    if (type === 'single') {
      onChange(opt)
    } else {
      const cur = (value as string[]) ?? []
      const next = cur.includes(opt)
        ? cur.filter((v) => v !== opt)
        : [...cur, opt]
      onChange(next)
    }
  }

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {chips.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => handleClick(opt)}
          className={`rounded-chip px-4 h-9 text-aux font-medium transition-all ${
            isSelected(opt)
              ? 'bg-primary text-white shadow-card'
              : 'bg-primary-tint text-primary-deep hover:bg-primary-soft/40'
          }`}
        >
          {opt}
        </button>
      ))}

      {customInput !== undefined && onCustomInputChange && onCustomAdd && (
        <div className="mt-1 flex w-full items-center gap-2">
          <input
            value={customInput}
            onChange={(e) => onCustomInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                onCustomAdd()
              }
            }}
            placeholder="补充其他想调研的目的地/城市，回车添加（可用逗号分隔多个）"
            className="h-9 flex-1 rounded-btn border border-line bg-bg px-3 text-aux text-ink outline-none transition-colors focus:border-primary"
          />
          <button
            type="button"
            onClick={onCustomAdd}
            className="shrink-0 rounded-btn bg-primary px-4 h-9 text-aux font-medium text-white hover:bg-primary-deep"
          >
            添加
          </button>
        </div>
      )}
    </div>
  )
}

import type {
  ReactNode,
  ButtonHTMLAttributes,
  HTMLAttributes,
  ComponentType,
  KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { motion, useMotionValue, useTransform, animate } from 'framer-motion'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/* ── 卡片 VCard ─────────────────────────────────────────── */
export function VCard({
  children,
  className = '',
  hover = true,
  ...rest
}: { children: ReactNode; className?: string; hover?: boolean } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`bg-card rounded-card shadow-card p-6 border border-line/60 transition-all duration-300 ease-smooth ${
        hover ? 'hover:shadow-float hover:-translate-y-0.5' : ''
      } ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}

/* ── 按钮 VButton ───────────────────────────────────────── */
export function VButton({
  children,
  variant = 'primary',
  className = '',
  ...p
}: {
  children: ReactNode
  variant?: 'primary' | 'ghost' | 'soft'
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    'inline-flex items-center justify-center gap-2 px-5 h-11 rounded-btn font-medium text-sm transition-all duration-200 ease-smooth active:scale-95 disabled:opacity-50 disabled:pointer-events-none'
  const styles =
    variant === 'primary'
      ? 'bg-primary text-white hover:bg-primary-deep shadow-card hover:shadow-float'
      : variant === 'soft'
        ? 'bg-primary-tint text-primary-deep hover:bg-primary-soft/40'
        : 'bg-transparent text-ink-2 hover:bg-primary-tint hover:text-primary-deep'
  return (
    <button className={`${base} ${styles} ${className}`} {...p}>
      {children}
    </button>
  )
}

/* ── Chip / 置信度标签 VChip ────────────────────────────── */
const tone = {
  high: 'bg-ok/15 text-ok',
  medium: 'bg-warn/15 text-warn',
  low: 'bg-risk/15 text-risk',
  unverified: 'bg-ink-3/15 text-ink-3',
  neutral: 'bg-primary-tint text-primary-deep',
} as const

export function VChip({
  label,
  level = 'neutral',
  icon,
  className = '',
}: {
  label: ReactNode
  level?: keyof typeof tone
  icon?: ReactNode
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-3 h-7 rounded-chip text-xs font-medium ${tone[level]} ${className}`}
    >
      {icon}
      {label}
    </span>
  )
}

/* ── 柔光晕 VSunGlow（春日阳光氛围） ────────────────────── */
export function VSunGlow({ className = '' }: { className?: string }) {
  return (
    <div
      className={`pointer-events-none absolute -z-0 ${className}`}
      style={{
        width: 520,
        height: 520,
        top: -160,
        right: -120,
        background: 'radial-gradient(circle, #F4E2B8 0%, rgba(244,226,184,0) 70%)',
        opacity: 0.5,
        filter: 'blur(8px)',
      }}
    />
  )
}

/* ── 数字滚动 VCountUp（Agent 感关键） ──────────────────── */
export function VCountUp({ value, className = '' }: { value: number; className?: string }) {
  const mv = useMotionValue(0)
  const rounded = useTransform(mv, (v) => Math.round(v))
  useEffect(() => {
    const c = animate(mv, value, { duration: 0.8, ease: 'easeOut' })
    return () => c.stop()
  }, [value, mv])
  return <motion.span className={className}>{rounded}</motion.span>
}

/* ── 骨架占位 VSkeleton（降级用，绝不白屏） ─────────────── */
export function VSkeleton({ className = '' }: { className?: string }) {
  return <div className={`v-skeleton ${className}`} />
}

/* ── 通用弹窗 VModal（SettingsPage 弹窗化首用，未来可复用） ──
   结构：遮罩（点击关闭）+ 居中卡（标题行 + 内容体）。
   约束：
   - 内容体 overflow-hidden，纵向滚动由消费方内容区自行控制
     （惯例：children 根节点给 `flex h-full`，右内容区给 overflow-y-auto）；
   - 打开期间锁 body 滚动，关闭时还原前值（防多实例互踩）；Esc 关闭。 */
export function VModal({
  open,
  onClose,
  title,
  width = 780,
  height = 'min(720px,85vh)',
  children,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  width?: number
  /** 弹窗高度。默认 'min(720px,85vh)'（Settings 等大面板）；紧凑表单可传更小值，如 'min(360px,80vh)'。 */
  height?: string
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
      {/* 遮罩：点击关闭 */}
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]" onClick={onClose} />
      {/* 居中卡：固定高度避免切 tab 时 content-driven 伸缩；h-[min(720px,85vh)] 兼顾小屏与桌面 */}
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col bg-card shadow-float border border-line/60 rounded-card"
        style={{ width, maxWidth: 'calc(100vw - 32px)', height }}
      >
        {/* 标题行 */}
        <div className="flex shrink-0 items-center justify-between gap-4 border-b border-line/50 px-6 py-4">
          <div className="truncate text-base font-semibold text-ink">{title}</div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-btn text-xl leading-none text-ink-2 transition-colors duration-200 ease-smooth hover:bg-primary-tint hover:text-primary-deep"
          >
            ×
          </button>
        </div>
        {/* 内容体：overflow-hidden + overflow-y-scroll 让滚动条轨道常驻，切 tab 时右 pane 宽度恒定防抽搐 */}
        <div className="min-h-0 flex-1 overflow-hidden overflow-y-scroll">{children}</div>
      </div>
    </div>
  )
}

/* ── 可输入下拉 VCombobox ──────────────────────────────────────────
   根修原生 datalist「有值即按值过滤且不可关闭」的选型错位：
   - 候选恒显全部（不随输入过滤），输入只做命中高亮；自由输入保留（受控）
   - 键盘契约（计划 v3）：↓/↑ 循环（active=-1 时 ↓→0 / ↑→末项）、Enter 仅
     active≥0 提交、输入即重置 active、Esc 关闭且 stopPropagation（防误关
     VModal 的 window Esc 监听）、Tab 不拦截（原生 blur 监听 relatedTarget 判定关闭）、
     IME 组合期（isComposing）忽略方向/回车
   - a11y：combobox/listbox/option + aria-expanded + aria-controls +
     aria-activedescendant —— portal 把面板渲染到 body 会断开 DOM 祖先语义，必须显式回连
   - 定位：portal + fixed（弹窗 overflow-y-auto 内 absolute 会被裁剪），
     scroll/resize 捕获阶段重算，监听随 open/unmount 成对清理
   零业务知识：candidates / 实时标记 / 刷新回调全部由调用方注入。 */

/* 命中片段高亮：indexOf 定位（禁 RegExp——候选 ID 含 ( ) + * 等特殊字符也安全） */
function highlightText(text: string, query: string) {
  if (!query) return text
  const i = text.toLowerCase().indexOf(query)
  if (i < 0) return text
  return (
    <>
      {text.slice(0, i)}
      <span className="font-bold text-primary-deep">{text.slice(i, i + query.length)}</span>
      {text.slice(i + query.length)}
    </>
  )
}

export function VCombobox({
  value,
  onChange,
  candidates,
  liveCandidates = [],
  placeholder,
  onRefresh,
  refreshing = false,
}: {
  value: string
  onChange: (v: string) => void
  candidates: string[]
  /** 标「实时」角的候选子集（来自 /models 拉取），仅展示 */
  liveCandidates?: string[]
  placeholder?: string
  /** 传入则在候选头部渲染「↻ 刷新实时列表」；调用方负责绕缓存重拉 */
  onRefresh?: () => void
  refreshing?: boolean
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listboxRef = useRef<HTMLDivElement>(null)
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [rect, setRect] = useState<{ left: number; top: number; width: number } | null>(null)

  const liveSet = useMemo(() => new Set(liveCandidates), [liveCandidates])

  const place = useCallback(() => {
    const el = inputRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setRect({ left: r.left, top: r.bottom + 6, width: Math.max(r.width, 220) })
  }, [])

  const openDd = useCallback(() => {
    place()
    setActive(candidates.indexOf(value))
    setOpen(true)
  }, [place, candidates, value])

  const closeDd = useCallback(() => {
    setOpen(false)
    setActive(-1)
  }, [])

  /* 打开期间：滚动/缩放重算定位（捕获阶段，覆盖弹窗内 overflow-y-auto 容器的滚动） */
  useEffect(() => {
    if (!open) return
    const re = () => place()
    window.addEventListener('scroll', re, true)
    window.addEventListener('resize', re)
    return () => {
      window.removeEventListener('scroll', re, true)
      window.removeEventListener('resize', re)
    }
  }, [open, place])

  /* 点外关闭：pointerdown 捕获（不依赖 input blur，避开与选项点击的竞态）。
     放行范围必须含 portal 面板（listboxRef）：面板挂在 document.body，
     不在 wrapRef 子树内 —— 漏判会把「点击选项」误杀成外点（pointerdown 先
     关面板 → click 目标已卸载 → 鼠标选择永远丢失，只能靠 Enter）。 */
  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as Node
      if (wrapRef.current?.contains(t)) return
      if (listboxRef.current?.contains(t)) return
      closeDd()
    }
    document.addEventListener('pointerdown', onDoc, true)
    return () => document.removeEventListener('pointerdown', onDoc, true)
  }, [open, closeDd])

  /* Tab 焦点离开关闭：监听原生 blur（框架无关、确定性），relatedTarget 落在候选面板内则不关 */
  useEffect(() => {
    if (!open) return
    const el = inputRef.current
    if (!el) return
    const onB = (e: FocusEvent) => {
      const rt = e.relatedTarget as Node | null
      if (rt && document.getElementById(listboxId)?.contains(rt)) return
      closeDd()
    }
    el.addEventListener('blur', onB)
    return () => el.removeEventListener('blur', onB)
  }, [open, closeDd, listboxId])

  const commit = (id: string) => {
    onChange(id)
    closeDd()
  }

  const onKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return // IME 组合期：方向/回车全忽略（W3C APG）
    const n = candidates.length
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        openDd()
        return
      }
      if (n === 0) return
      setActive((a) => (a + 1) % n) // -1 → 0
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open || n === 0) return
      setActive((a) => (a === -1 ? n - 1 : (a - 1 + n) % n)) // -1 → 末项（契约），其余循环
    } else if (e.key === 'Enter') {
      if (open && active >= 0 && active < n) {
        e.preventDefault()
        commit(candidates[active])
      }
      // active=-1：no-op（不误 commit、不误关）
    } else if (e.key === 'Escape') {
      if (open) {
        e.stopPropagation() // 防 VModal 的 window Esc 监听连带关掉整个弹窗
        e.preventDefault()
        closeDd()
      }
    }
    // Tab 不拦截：原生焦点移动；关闭由原生 blur 监听（relatedTarget 判定）处理
  }

  const q = value.trim().toLowerCase()

  const panel =
    open && rect
      ? createPortal(
          <div
            id={listboxId}
            ref={listboxRef}
            role="listbox"
            className="fixed z-[60] overflow-hidden rounded-card border border-line/60 bg-card shadow-float"
            style={{ left: rect.left, top: rect.top, width: rect.width, maxWidth: 'calc(100vw - 24px)' }}
            onMouseDown={(e) => e.preventDefault()}
          >
            <div className="flex items-center justify-between gap-2 border-b border-line/50 px-3 py-2 text-tag text-ink-3">
              <span>全部候选 · 不随输入过滤</span>
              {onRefresh && (
                <button
                  type="button"
                  disabled={refreshing}
                  onClick={onRefresh}
                  className="inline-flex shrink-0 items-center gap-1 rounded-btn border border-dashed border-primary/60 px-2 py-0.5 text-tag text-primary-deep transition-colors duration-200 ease-smooth hover:bg-primary-tint/60 disabled:opacity-50"
                >
                  <span className={refreshing ? 'inline-block animate-spin' : 'inline-block'}>↻</span>
                  {refreshing ? '刷新中…' : '刷新实时列表'}
                </button>
              )}
            </div>
            <div className="max-h-56 overflow-y-auto py-1">
              {candidates.length === 0 ? (
                <div className="px-3 py-2 text-tag text-ink-3">无候选 · 可直接输入模型 ID</div>
              ) : (
                candidates.map((c, i) => {
                  const isLive = liveSet.has(c)
                  return (
                    <div
                      key={c}
                      id={`${listboxId}-opt-${i}`}
                      role="option"
                      aria-selected={c === value}
                      onMouseEnter={() => setActive(i)}
                      onPointerDown={(e) => {
                        // 在 pointerdown 阶段直接提交：抢在 blur/关闭时序之前；
                        // preventDefault 抑制焦点转移 → input 不失焦，blur 关闭路径不触发。
                        // （曾用 onClick：portal 误关时序下 click 目标已卸载，鼠标选择丢失）
                        e.preventDefault()
                        commit(c)
                      }}
                      className={[
                        'flex cursor-pointer items-center gap-2 px-3 py-2 font-mono text-tag break-all',
                        i === active ? 'bg-primary-tint text-primary-deep' : 'text-ink',
                      ].join(' ')}
                    >
                      <span>{highlightText(c, q)}</span>
                      {isLive && (
                        <span className="shrink-0 rounded bg-primary-tint px-1.5 py-px text-[10px] text-primary-deep">
                          实时
                        </span>
                      )}
                      <span className={`ml-auto shrink-0 text-primary-deep ${c === value ? 'visible' : 'invisible'}`}>
                        ✓
                      </span>
                    </div>
                  )
                })
              )}
            </div>
            <div className="border-t border-line/50 px-3 py-1.5 text-tag text-ink-3">
              点击 / ↑↓·Enter 选择 · Esc 关闭 · 可直接输入任意 ID
            </div>
          </div>,
          document.body,
        )
      : null

  return (
    <div ref={wrapRef} className="relative w-full">
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${listboxId}-opt-${active}` : undefined}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setActive(-1) // 输入即重置高亮，防 Enter 误 commit 陈旧 active
          if (!open) openDd()
        }}
        onFocus={openDd}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        className="h-10 w-full rounded-btn border border-line bg-card px-3.5 pr-8 font-mono text-tag text-ink outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/15"
      />
      <button
        type="button"
        aria-label="展开候选"
        tabIndex={-1}
        onMouseDown={(e) => e.preventDefault()} // 防止 input 先 blur 触发关闭，再被 click 又打开
        onClick={() => (open ? closeDd() : openDd())}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-ink-3"
      >
        ▾
      </button>
      {panel}
    </div>
  )
}

/* ── 统计卡 VStatCard（全仓唯一一份「数字 + 标签 + 口径说明」的卡面） ──
 *
 * 为什么要有它：同一形状的统计卡原先有**两份私有实现** —— `RecordStatsStrip.tsx`
 * 的 `StatBlock`（生活圈统计带）与 `pages/reports/ResearchIntelView.tsx` 的 `Stat`
 * （调研屏八块）。照参考图再抄一遍就是第三份 ⇒ "把数字字号调一档"要改三处。
 *
 * `surface` 三值不是审美枚举，是**现存三种面的清单**：`vcard`=源页 StatCard 面
 * （VCard，p-6 带阴影）· `tile`=仓内既有面（p-4 带阴影）· `flat`=源页 ImpactCard 面
 * （p-4 无阴影）。少一个值，收敛时就会被动改掉某一屏的像素。
 *
 * 口径说明的摆法跟着面走、不另开开关：`vcard` 摊在卡面上，`tile`/`flat` 留在 `title`
 * —— 换面就是换"要不要占卡高"，这两条路径各自都有屏在用。
 *
 * ⚠️ `countUp` 会**取整**（`VCountUp` 内部 `Math.round`）⇒ 带小数的口径
 * （11.1 小时、29.8×）必须关掉，否则数字被动画洗成整数。jsdom 里它首帧还是 0，
 * 所以数值判据也只允许落在 `countUp={false}` 这一支上。
 */
const STAT_FACE = {
  vcard: {
    icon: 'grid h-9 w-9 place-items-center rounded-btn bg-primary-tint',
    numRow: 'mt-3 flex items-end gap-0.5',
    num: 'font-serif text-[32px] leading-none text-ink',
    unit: 'mb-1 text-h3 text-ink-2',
    label: 'mt-1 text-aux font-medium text-ink',
  },
  tile: {
    icon: 'grid h-8 w-8 place-items-center rounded-btn bg-primary-tint',
    numRow: 'mt-2.5 flex items-end gap-0.5',
    num: 'font-serif text-[26px] leading-none text-ink',
    unit: 'mb-0.5 text-aux text-ink-2',
    label: 'mt-1 text-tag font-medium text-ink-2',
  },
  flat: {
    icon: 'grid h-8 w-8 place-items-center rounded-btn bg-primary-tint',
    numRow: 'mt-2.5 flex items-end gap-0.5',
    num: 'font-serif text-[26px] leading-none text-ink',
    unit: 'mb-0.5 text-aux text-ink-2',
    label: 'mt-1 text-tag font-medium text-ink-2',
  },
} as const

export function VStatCard({
  icon: Icon,
  value,
  label,
  tip,
  unit,
  color = 'text-primary',
  surface = 'tile',
  countUp = false,
}: {
  icon?: ComponentType<{ size?: number }>
  value: number
  label: string
  tip: string
  unit?: string
  color?: string
  surface?: keyof typeof STAT_FACE
  countUp?: boolean
}) {
  const face = STAT_FACE[surface]
  const body = (
    <>
      {Icon && (
        <span className={`${face.icon} ${color}`}>
          <Icon size={surface === 'vcard' ? 18 : 16} />
        </span>
      )}
      <div className={Icon ? face.numRow : 'flex items-end gap-0.5'}>
        <span className={face.num}>{countUp ? <VCountUp value={value} /> : value}</span>
        {unit && <span className={face.unit}>{unit}</span>}
      </div>
      <div className={face.label}>{label}</div>
      {surface === 'vcard' && <p className="mt-1 text-tag leading-relaxed text-ink-3">{tip}</p>}
    </>
  )
  if (surface === 'vcard') return <VCard hover={false}>{body}</VCard>
  const wrap =
    surface === 'tile'
      ? 'rounded-card border border-line/60 bg-card p-4 shadow-card'
      : 'rounded-card border border-line/60 bg-bg p-4'
  return (
    <div className={wrap} title={tip}>
      {body}
    </div>
  )
}

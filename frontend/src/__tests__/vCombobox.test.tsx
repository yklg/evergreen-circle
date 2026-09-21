// @vitest-environment jsdom
/**
 * VCombobox 组件单测（计划 blazing-beacon-lovelace-TcX-Ik81 v3 测试节 T1~T14）。
 *
 * 被测范围：frontend/src/components/ui/index.tsx 的 VCombobox（新增组件，含 portal 面板）。
 * 档位：组件为新增，落地后应全绿；🟢 防行为契约被改坏、🔵 防实现过度动作（T13）。
 * T15（SettingsPage 集成，🟠）为 P2 可选，【待生成】——不伪造覆盖。
 *
 * 实现约束（依赖核验节）：
 *  - 项目无 @testing-library/user-event → 全部 fireEvent；
 *  - vitest globals:false → afterEach 手动 cleanup（沿用 clarifyAsync.test.tsx 惯例）；
 *  - jsdom 无原生 PointerEvent，fireEvent.pointerDown 派发 type='pointerdown' 可触发捕获监听；
 *  - jsdom getBoundingClientRect 全 0 → portal 面板宽度走 220 兜底，不影响 DOM 断言；
 *  - React 17+ 对 focus/blur 用捕获委托，fireEvent.focus 可触发 onFocus。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { useState } from 'react'
import { VCombobox } from '../components/ui'

const CANDS = ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-pro-0918']

afterEach(cleanup)

type Opts = {
  initial?: string
  candidates?: string[]
  liveCandidates?: string[]
  onRefresh?: () => void
  refreshing?: boolean
}

/** 受控包装：父持 value（真实受控形态），onChange 透传 spy */
function Harness(props: Opts & { onChangeSpy: (v: string) => void }) {
  const [v, setV] = useState(props.initial ?? 'zzz-unknown')
  return (
    <VCombobox
      value={v}
      onChange={(x) => {
        props.onChangeSpy(x)
        setV(x)
      }}
      candidates={props.candidates ?? CANDS}
      liveCandidates={props.liveCandidates}
      placeholder="选择或直接输入模型 ID"
      onRefresh={props.onRefresh}
      refreshing={props.refreshing}
    />
  )
}

function mountCb(opts: Opts = {}) {
  const onChange = vi.fn()
  // 默认 initial 取「非候选值」：保证 T1 五等价类的每次 change 都是真实值变化
  // （React 会抑制未变化的 change 事件，若初始即等于输入值会用例假红）
  const utils = render(<Harness {...opts} onChangeSpy={onChange} />)
  const input = utils.container.querySelector('input') as HTMLInputElement
  const arrow = utils.container.querySelector('button[aria-label="展开候选"]') as HTMLButtonElement
  return { ...utils, input, arrow, onChange }
}

/** 打开下拉（focus 即开） */
function openDd(input: HTMLInputElement) {
  fireEvent.focus(input)
  return screen.getByRole('listbox')
}

describe('VCombobox · 候选不过滤不变量（T1/T2 🟢）', () => {
  // 五等价类：空串 / 完整命中 / 部分子串 / 无命中 / 含正则特殊字符
  const QUERIES = ['', 'deepseek-v4-pro', 'deepseek', 'zzz-nope', 'gpt-4o(v2+*)']

  it.each(QUERIES)('T1 输入 %j 打开后 option 数恒 == candidates.length（不过滤）', (q) => {
    const { input } = mountCb()
    fireEvent.change(input, { target: { value: q } }) // 输入自动打开
    expect(screen.getAllByRole('option')).toHaveLength(CANDS.length)
    expect(input.value).toBe(q) // 受控回写
  })

  it('T2 大小写不敏感高亮；特殊字符 query 不炸（indexOf 而非 RegExp）', () => {
    const { input } = mountCb()
    fireEvent.change(input, { target: { value: 'V4-PRO' } }) // 大写命中
    let opts = screen.getAllByRole('option')
    expect(opts).toHaveLength(CANDS.length)
    expect(opts[0].querySelector('span.font-bold')).not.toBeNull()
    fireEvent.change(input, { target: { value: 'gpt-4o(v2+*)' } }) // 无命中
    opts = screen.getAllByRole('option')
    expect(opts).toHaveLength(CANDS.length)
    expect(opts[0].querySelector('span.font-bold')).toBeNull()
  })
})

describe('VCombobox · 键盘契约（T3/T4 🟢）', () => {
  it('T3a value 未命中打开 active=-1：↓→0，Enter commit 首项并关闭', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // -1 → 0
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(CANDS[0])
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('T3b ↑ 从 -1 → 末项：Enter commit 最后一项', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    fireEvent.keyDown(input, { key: 'ArrowUp' }) // -1 → n-1
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(CANDS[CANDS.length - 1])
  })

  it('T3c Enter 在 active=-1 时 no-op（不 commit 不关闭）', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('listbox')).toBeTruthy()
  })

  it('T4 ↓ 高亮后继续输入 → active 重置 → Enter 不 commit 候选（防陈旧高亮误选）', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // active=0
    fireEvent.change(input, { target: { value: 'deep' } }) // 输入重置 active=-1，下拉保持开
    fireEvent.keyDown(input, { key: 'Enter' })
    // onChange 恰好 1 次 = 打字本身（'deep'）；Enter 未把任何候选 commit 进来
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('deep')
    expect(input.value).toBe('deep')
    expect(screen.getByRole('listbox')).toBeTruthy()
  })
})

describe('VCombobox · 受控与关闭路径（T5/T7 🟢）', () => {
  it('T5 父改 value prop → 输入框值跟随（受控同步）', () => {
    const onChange = vi.fn()
    const u = render(<VCombobox value="aaa" onChange={onChange} candidates={CANDS} />)
    const input = u.container.querySelector('input') as HTMLInputElement
    expect(input.value).toBe('aaa')
    u.rerender(<VCombobox value="bbb" onChange={onChange} candidates={CANDS} />)
    expect(input.value).toBe('bbb')
  })

  it('T7a Esc 关闭 + aria-expanded 翻转', () => {
    const { input } = mountCb()
    expect(input.getAttribute('aria-expanded')).toBe('false')
    openDd(input)
    expect(input.getAttribute('aria-expanded')).toBe('true')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(input.getAttribute('aria-expanded')).toBe('false')
  })

  it('T7b 点外（pointerdown 捕获）关闭', () => {
    const { input } = mountCb()
    openDd(input)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('T7c 点选项（pointerDown，真实浏览器首选径）commit 并关闭', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    const opts = screen.getAllByRole('option')
    // 真实浏览器点击 = pointerdown → mousedown → mouseup → click；
    // 选项提交已前移到 pointerdown（抢在 blur/关闭时序前），故用 pointerDown 驱动。
    // （曾用 fireEvent.click —— jsdom 不派发前置 pointerdown，掩盖过 portal 误关 bug）
    fireEvent.pointerDown(opts[1])
    expect(onChange).toHaveBeenCalledWith('deepseek-v4-flash')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('T7e 回归：portal 面板内（含 header）pointerdown 不判为外点、面板不关', () => {
    const { input } = mountCb()
    openDd(input)
    // 面板挂在 document.body 而非 wrapRef 子树 —— 放行判定必须覆盖 listboxRef
    fireEvent.pointerDown(screen.getByText('全部候选 · 不随输入过滤'))
    expect(screen.getByRole('listbox')).toBeTruthy()
  })

  it('T7f 回归：pointerDown 选项期间 input 不失焦（preventDefault 抑制焦点转移）', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    const blurSpy = vi.fn()
    input.addEventListener('blur', blurSpy)
    fireEvent.pointerDown(screen.getAllByRole('option')[0])
    expect(onChange).toHaveBeenCalledWith(CANDS[0])
    expect(blurSpy).not.toHaveBeenCalled()
  })

  it('T7d ▾ 双向：关→开→关（mousedown preventDefault 防先 blur 后重开）', () => {
    const { arrow } = mountCb()
    fireEvent.click(arrow) // 开
    expect(screen.getByRole('listbox')).toBeTruthy()
    fireEvent.click(arrow) // 关
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})

describe('VCombobox · Esc 隔离 / 空态 / C4（T6/T8/T9）', () => {
  it('T6 🟢 P1 专项：下拉开着按 Esc，window keydown 监听不触发、仅关下拉', () => {
    const winSpy = vi.fn()
    window.addEventListener('keydown', winSpy)
    try {
      const { input } = mountCb()
      openDd(input)
      fireEvent.keyDown(input, { key: 'Escape' })
      expect(screen.queryByRole('listbox')).toBeNull()
      expect(winSpy).not.toHaveBeenCalled() // stopPropagation 生效，VModal 不被误关
    } finally {
      window.removeEventListener('keydown', winSpy)
    }
  })

  it('T8a 🟢 空候选 → 空态文案，不出空壳', () => {
    const { input } = mountCb({ candidates: [] })
    openDd(input)
    expect(screen.getByText(/无候选 · 可直接输入模型 ID/)).toBeTruthy()
    expect(screen.queryByRole('option')).toBeNull()
  })

  it('T8b 🟢 liveCandidates 超集安全：仅交集项标「实时」，超集项不渲染', () => {
    const { input } = mountCb({ liveCandidates: ['x-not-in-cands', 'deepseek-v4-flash'] })
    openDd(input)
    const opts = screen.getAllByRole('option')
    expect(opts).toHaveLength(CANDS.length)
    const liveMarks = opts.filter((o) => o.textContent?.includes('实时'))
    expect(liveMarks).toHaveLength(1)
    expect(liveMarks[0].textContent).toContain('deepseek-v4-flash')
  })

  it('T9a 🔵 负向对照：未传 onRefresh → 无刷新按钮', () => {
    const { input } = mountCb()
    openDd(input)
    expect(screen.queryByRole('button', { name: /刷新实时列表/ })).toBeNull()
  })

  it('T9b 🟢 传 onRefresh → 点击触发；refreshing=true 时按钮禁用（fireEvent 会绕过 disabled 语义，真实浏览器本就不派发点击）', () => {
    const onRefresh = vi.fn()
    const u = mountCb({ onRefresh })
    fireEvent.focus(u.input)
    const btn = screen.getByRole('button', { name: /刷新实时列表/ }) as HTMLButtonElement
    fireEvent.click(btn)
    expect(onRefresh).toHaveBeenCalledTimes(1)
    u.rerender(
      <Harness initial="deepseek-v4-pro" onRefresh={onRefresh} refreshing onChangeSpy={vi.fn()} />,
    )
    const btn2 = screen.getByRole('button', { name: /刷新中…/ }) as HTMLButtonElement
    expect(btn2.disabled).toBe(true)
  })
})

describe('VCombobox · a11y 与边界（T10~T14）', () => {
  it('T10 🟢 a11y：role 三件套 + aria-controls 回连 + aria-activedescendant', () => {
    const { input } = mountCb({ initial: 'zzz-unknown' })
    expect(input.getAttribute('role')).toBe('combobox')
    const lb = openDd(input)
    const lbId = lb.getAttribute('id') ?? ''
    expect(lbId.length).toBeGreaterThan(0)
    expect(input.getAttribute('aria-controls')).toBe(lbId) // portal 语义回连
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // active=0
    expect(input.getAttribute('aria-activedescendant')).toBe(`${lbId}-opt-0`)
    const opt0 = screen.getAllByRole('option')[0]
    expect(opt0.getAttribute('id')).toBe(`${lbId}-opt-0`)
    expect(opt0.getAttribute('aria-selected')).toBe('false') // value 未命中任何候选
  })

  it('T11 🟢 多实例互不串扰（MODEL_FIELDS 4 实例的真实形态）', () => {
    const onChange = vi.fn()
    function Two() {
      const [a, setA] = useState('alpha-a')
      const [b, setB] = useState('beta-b')
      return (
        <div>
          <VCombobox
            value={a}
            onChange={(x) => {
              onChange('A:' + x)
              setA(x)
            }}
            candidates={['alpha-1', 'alpha-2']}
          />
          <VCombobox
            value={b}
            onChange={(x) => {
              onChange('B:' + x)
              setB(x)
            }}
            candidates={['beta-1', 'beta-2']}
          />
        </div>
      )
    }
    const u = render(<Two />)
    const inputs = u.container.querySelectorAll('input')
    const inputA = inputs[0] as HTMLInputElement
    const inputB = inputs[1] as HTMLInputElement
    fireEvent.focus(inputA)
    expect(screen.getAllByRole('option')).toHaveLength(2) // A 的候选
    fireEvent.pointerDown(inputB) // A 的点外关闭（B 在 A 的 wrapRef 外）
    fireEvent.focus(inputB)
    const opts = screen.getAllByRole('option') // 若 A 未关会看到 4 个 —— 串扰即红
    expect(opts).toHaveLength(2)
    expect(opts[0].textContent).toContain('beta-1') // 现在显示的是 B 的候选
  })

  it('T12 🟢 Tab 不拦截（不成键盘陷阱）+ 原生 blur 关闭下拉', () => {
    const { input } = mountCb()
    openDd(input)
    // 裸 dispatchEvent 不在 act() 内，setState 不会同步刷新 —— 必须走 fireEvent 泛型形式
    const tab = new window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    fireEvent(input, tab)
    expect(tab.defaultPrevented).toBe(false) // 不拦截 Tab
    expect(screen.getByRole('listbox')).toBeTruthy() // Tab 键本身不关（关闭走 blur）
    // 实现监听原生 blur（框架无关）：relatedTarget 不在面板内 → 关闭
    fireEvent(input, new window.FocusEvent('blur', { relatedTarget: document.body }))
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('T13 🔵 卸载哨兵：pointerdown 捕获监听随 unmount 成对清理（防泄漏）', () => {
    const addSpy = vi.spyOn(document, 'addEventListener')
    const rmSpy = vi.spyOn(document, 'removeEventListener')
    const { input, unmount } = mountCb()
    fireEvent.focus(input) // 打开 → 挂 document pointerdown 捕获监听
    expect(addSpy).toHaveBeenCalledWith('pointerdown', expect.any(Function), true)
    unmount()
    expect(rmSpy).toHaveBeenCalledWith('pointerdown', expect.any(Function), true)
    addSpy.mockRestore()
    rmSpy.mockRestore()
  })

  it('T14 🟢 IME 组合期（isComposing）：↑↓/Enter 全忽略；组合结束恢复', () => {
    const { input, onChange } = mountCb({ initial: 'zzz-unknown' })
    openDd(input)
    fireEvent.keyDown(input, { key: 'ArrowDown', isComposing: true }) // 组合期忽略
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('listbox')).toBeTruthy()
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // 组合结束 → active -1→0
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(CANDS[0])
  })
})

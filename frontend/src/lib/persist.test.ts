// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

/* persist.ts 单测 —— 覆盖「重启不丢」的每一条判定分支。
 *
 * 为什么这些用例必须存在：本模块的核心价值全在**时序分支**上
 * （远端为准 / 远端为空则上推 / pending 则本地为准 / 后端不可用则保留本地），
 * 而分支写错的表现是"用户资料莫名消失或莫名回滚" —— 只靠手点很难覆盖。
 *
 * 用 vi.hoisted 固定 mock 引用：vi.resetModules() 会清模块注册表（让 persister
 * 注册表在用例间隔离），但 hoisted 的 mock 对象引用不变，用例才能稳定断言。
 */
const io = vi.hoisted(() => {
  /** 与 api.ts 同名同义：用于断言「该部署没有 /api/prefs」被当作常态降级而非故障。 */
  class PrefsUnsupportedError extends Error {
    constructor(status = 404) {
      super(`该部署未提供 /api/prefs（HTTP ${status}）`)
      this.name = 'PrefsUnsupportedError'
    }
  }
  return {
    fetchPrefs: vi.fn(),
    savePrefs: vi.fn(),
    getPrefsApiCapability: vi.fn(() => 'unknown' as 'unknown' | 'supported' | 'unsupported'),
    PrefsUnsupportedError,
  }
})

vi.mock('./api', () => io)

import type { PrefsResp } from '../types'
import { BRAND } from './brand'

const PENDING_KEY = 'verda.prefs.pending.v1'
const LS_KEY = 'verda.test.prefs.v1'

type Spec = { name: string; collapsed: boolean }

const DEFAULTS: Spec = { name: '默认名', collapsed: false }

function remoteResp(values: Record<string, unknown>): PrefsResp {
  return {
    ok: true,
    values: values as PrefsResp['values'],
    stored: Object.keys(values),
    groups: {},
  }
}

/** 每个用例重新 import，保证 persist.ts 的模块级 registry/outboxes 干净。 */
async function freshPersist() {
  vi.resetModules()
  return await import('./persist')
}

function makeSpec(persistMod: typeof import('./persist')) {
  return persistMod.createPersister<Spec>({
    localKey: LS_KEY,
    prefs: { name: 'profile.name', collapsed: 'ui.sidebarCollapsed' },
    defaults: DEFAULTS,
  })
}

beforeEach(() => {
  localStorage.clear()
  io.fetchPrefs.mockReset()
  io.savePrefs.mockReset()
  io.savePrefs.mockResolvedValue(undefined)
  io.getPrefsApiCapability.mockReset()
  io.getPrefsApiCapability.mockReturnValue('unknown')
})

afterEach(() => {
  vi.useRealTimers()
})

/* ── coerceLike：类型归一的陷阱 ────────────────────────── */
describe('coerceLike', () => {
  it('bool 不用 Boolean(v)：字符串 "false" 必须归为 false', async () => {
    const { coerceLike } = await freshPersist()
    expect(coerceLike(false, 'false')).toBe(false)
    expect(coerceLike(false, '0')).toBe(false)
    expect(coerceLike(false, 'off')).toBe(false)
    expect(coerceLike(false, 'true')).toBe(true)
    expect(coerceLike(false, '1')).toBe(true)
    expect(coerceLike(false, false)).toBe(false)
    // 非法值 → undefined（调用方回退默认）
    expect(coerceLike(false, 'maybe')).toBeUndefined()
  })

  it('str / number 归一', async () => {
    const { coerceLike } = await freshPersist()
    expect(coerceLike('', '李工')).toBe('李工')
    expect(coerceLike('', 42)).toBe('42')
    expect(coerceLike(0, '12.5')).toBe(12.5)
    expect(coerceLike(0, 'abc')).toBeUndefined()
    expect(coerceLike('', null)).toBeUndefined()
    expect(coerceLike('', undefined)).toBeUndefined()
  })
})

/* ── readLocal：首屏同步读，永不抛错 ───────────────────── */
describe('readLocal（首屏同步读）', () => {
  it('无本地数据 → 回退默认值', async () => {
    const p = makeSpec(await freshPersist())
    expect(p.readLocal()).toEqual(DEFAULTS)
  })

  it('JSON 损坏 → 回退默认值，不抛错', async () => {
    localStorage.setItem(LS_KEY, '{不是合法json')
    const p = makeSpec(await freshPersist())
    expect(p.readLocal()).toEqual(DEFAULTS)
  })

  it('局部字段缺失 → 逐字段回落默认，已有字段保留', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '李工' }))
    const p = makeSpec(await freshPersist())
    expect(p.readLocal()).toEqual({ name: '李工', collapsed: false })
  })

  it('字段类型不符 → 该字段回落默认（不污染整包）', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: 123, collapsed: 'true' }))
    const p = makeSpec(await freshPersist())
    // name 是 number，按 str 默认无法归一 → String(123) = '123'（归一为字符串而非丢弃）
    expect(p.readLocal()).toEqual({ name: '123', collapsed: true })
  })
})

/* ── persist：本地即时落盘 + debounce 上推 ─────────────── */
describe('persist（写入）', () => {
  it('同步写 localStorage，且只写白名单字段（不把动作函数写进去）', async () => {
    const p = makeSpec(await freshPersist())
    p.persist({ name: '王研究员', collapsed: true, setName: () => {}, extra: 'x' })
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '王研究员', collapsed: true })
  })

  it('debounce：连续多次写入只上推一次，且带的是最后快照', async () => {
    vi.useFakeTimers()
    const p = makeSpec(await freshPersist())
    p.persist({ name: 'A', collapsed: false })
    p.persist({ name: 'B', collapsed: false })
    p.persist({ name: 'C', collapsed: false })
    expect(io.savePrefs).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(450)
    expect(io.savePrefs).toHaveBeenCalledTimes(1)
    expect(io.savePrefs).toHaveBeenCalledWith({
      'profile.name': 'C',
      'ui.sidebarCollapsed': false,
    })
  })

  it('上推成功 → 清除 pending 账本', async () => {
    vi.useFakeTimers()
    const p = makeSpec(await freshPersist())
    p.persist({ name: 'A', collapsed: false })
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toEqual({
      'profile.name': 'A',
      'ui.sidebarCollapsed': false,
    })
    await vi.advanceTimersByTimeAsync(450)
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toEqual({})
  })

  it('上推失败 → 保留 pending（供下次启动重推），且不抛错、不静默', async () => {
    vi.useFakeTimers()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    io.savePrefs.mockRejectedValue(new Error('backend down'))
    const p = makeSpec(await freshPersist())
    p.persist({ name: 'A', collapsed: false })
    await vi.advanceTimersByTimeAsync(450)
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toMatchObject({ 'profile.name': 'A' })
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })
})

/* ── 裁剪部署降级（Vercel 只读镜像无 /api/prefs）──────────
   这不是故障而是既定取舍（api/ 是 backend/ 的有意裁剪子集，只写 /tmp）。
   必须验证：本地持久化照常工作、不再空推、不再刷告警。 */
describe('部署未提供 /api/prefs → 纯本地模式（不空推、不告警）', () => {
  it('能力为 unsupported → 本地照常落盘，但不发 PUT', async () => {
    vi.useFakeTimers()
    io.getPrefsApiCapability.mockReturnValue('unsupported')
    const p = makeSpec(await freshPersist())
    p.persist({ name: '本地名', collapsed: true })
    await vi.advanceTimersByTimeAsync(450)
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '本地名', collapsed: true })
    expect(io.savePrefs).not.toHaveBeenCalled()
  })

  it('竞态兜底：能力尚为 unknown 但服务端返回 404 → 静默降级，不告警', async () => {
    vi.useFakeTimers()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    io.savePrefs.mockRejectedValue(new io.PrefsUnsupportedError(404))
    const p = makeSpec(await freshPersist())
    p.persist({ name: 'A', collapsed: false })
    await vi.advanceTimersByTimeAsync(450)
    expect(io.savePrefs).toHaveBeenCalledTimes(1)
    expect(warn).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('水合遇后端无接口（null）→ 保留本地值、不上推、不清空', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地存量', collapsed: true }))
    io.fetchPrefs.mockResolvedValue(null)
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()
    expect(onRemote).not.toHaveBeenCalled()
    expect(io.savePrefs).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '本地存量', collapsed: true })
  })
})

/* ── hydrate：启动水合的四条分支 ──────────────────────── */
describe('hydrate（启动水合：远端为真相源）', () => {
  it('远端有值 → 远端为准，回填回调 + 落回本地缓存', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地旧名', collapsed: true }))
    io.fetchPrefs.mockResolvedValue(
      remoteResp({ 'profile.name': '远端新名', 'ui.sidebarCollapsed': false }),
    )
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()

    expect(onRemote).toHaveBeenCalledWith({ name: '远端新名', collapsed: false })
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '远端新名', collapsed: false })
    // 远端已有值 → 不需要上推
    expect(io.savePrefs).not.toHaveBeenCalled()
  })

  it('远端为空（新库）→ 保留本地并自动上推（存量资料迁移，不丢）', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '存量本地名', collapsed: true }))
    io.fetchPrefs.mockResolvedValue(remoteResp({}))
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()

    expect(onRemote).not.toHaveBeenCalled() // 本地没变，无需回填
    expect(io.savePrefs).toHaveBeenCalledWith({
      'profile.name': '存量本地名',
      'ui.sidebarCollapsed': true,
    })
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '存量本地名', collapsed: true })
  })

  it('逐字段判定：远端只有 A 字段 → A 取远端，B 取本地并单独上推', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地名', collapsed: true }))
    io.fetchPrefs.mockResolvedValue(remoteResp({ 'profile.name': '远端名' }))
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()

    expect(onRemote).toHaveBeenCalledWith({ name: '远端名' })
    expect(io.savePrefs).toHaveBeenCalledWith({ 'ui.sidebarCollapsed': true })
  })

  it('本地有未成功推送的改动（pending）→ 本地为准并重推，绝不被远端旧值回滚', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '刚改的新名', collapsed: false }))
    localStorage.setItem(PENDING_KEY, JSON.stringify({ 'profile.name': '刚改的新名' }))
    io.fetchPrefs.mockResolvedValue(remoteResp({ 'profile.name': '远端旧名' }))
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()

    expect(onRemote).not.toHaveBeenCalled() // 本地未被远端覆盖
    // 名字走「pending → 本地为准重推」；collapsed 远端没有 → 也一并上推（存量迁移）
    expect(io.savePrefs).toHaveBeenCalledWith({
      'profile.name': '刚改的新名',
      'ui.sidebarCollapsed': false,
    })
  })

  it('后端不可用（fetchPrefs 返回 null）→ 保留本地值，不清空、不抛错', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地名', collapsed: true }))
    io.fetchPrefs.mockResolvedValue(null)
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()

    expect(onRemote).not.toHaveBeenCalled()
    expect(io.savePrefs).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({ name: '本地名', collapsed: true })
  })

  it('远端值类型脏（bool 传 "true" 字符串）→ 归一回本地 bool 并回填', async () => {
    // 本地 collapsed=false（默认），远端是字符串 'true' → 必须归一成 true 才算"变化"，
    // 若直接比较字符串会漏掉这次回填（真实 bug 形态）。
    io.fetchPrefs.mockResolvedValue(remoteResp({ 'ui.sidebarCollapsed': 'true' }))
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()
    expect(onRemote).toHaveBeenCalledWith({ collapsed: true })
    expect(JSON.parse(localStorage.getItem(LS_KEY)!).collapsed).toBe(true)
  })

  it('远端值与本地一致 → 不触发无谓回填（避免整树重渲染）', async () => {
    io.fetchPrefs.mockResolvedValue(remoteResp({ 'ui.sidebarCollapsed': false }))
    const mod = await freshPersist()
    const p = makeSpec(mod)
    const onRemote = vi.fn()
    p.register(onRemote)
    await mod.hydrateAllPrefs()
    expect(onRemote).not.toHaveBeenCalled()
  })
})

/* ── pending 竞态：飞行中又改了一次，不能被误清 ─────────── */
describe('pending 竞态的精确性', () => {
  it('上推在途时又发生一次改动 → 旧回包不得清掉新改动的 pending', async () => {
    vi.useFakeTimers()
    let release: () => void = () => {}
    io.savePrefs.mockImplementation(
      () => new Promise<void>((res) => { release = () => res() }),
    )
    const p = makeSpec(await freshPersist())

    // 第一次改动 → debounce 到期，发出版本 A（在途未回）
    p.persist({ name: 'A', collapsed: false })
    await vi.advanceTimersByTimeAsync(450)
    expect(io.savePrefs).toHaveBeenCalledTimes(1)

    // 在途期间改成 B
    p.persist({ name: 'B', collapsed: false })
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toMatchObject({ 'profile.name': 'B' })

    // A 的回包到达：pending 里是 'B' ≠ 已发送的 'A' → 必须**不**清除
    release()
    await vi.advanceTimersByTimeAsync(0)
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toMatchObject({ 'profile.name': 'B' })

    // 且 B 会在自己的窗口到期后继续上推
    io.savePrefs.mockResolvedValue(undefined)
    await vi.advanceTimersByTimeAsync(450)
    expect(io.savePrefs).toHaveBeenLastCalledWith({
      'profile.name': 'B',
      'ui.sidebarCollapsed': false,
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(JSON.parse(localStorage.getItem(PENDING_KEY)!)).toEqual({})
  })
})

/* ── 品牌漂移守卫 ─────────────────────────────────────── */
describe('brand', () => {
  it('BRAND 字段齐备且非空', () => {
    for (const [k, v] of Object.entries(BRAND)) {
      expect(typeof v, k).toBe('string')
      expect(String(v).trim().length, k).toBeGreaterThan(0)
    }
    expect(BRAND.themeColor).toBe('#7c9885')
  })
})

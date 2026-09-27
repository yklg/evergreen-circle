// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

/* profileStore 单测：默认回退、本地持久化、从 localStorage 还原，
 * 以及**本轮新增**的「服务端为真相源」水合契约。
 *
 * 为什么新增后两项：本 store 的持久化已从「localStorage 是唯一真相源」改为
 * 「localStorage 秒开缓存 + /api/prefs 为真相源」（见《用户设置持久化架构修复计划》）。
 * 若不把水合契约钉住，将来有人删掉 register() 调用，测试仍会全绿但线上会静默复发。
 *
 * 每条用例用 vi.resetModules() + 动态 import 保证 store 单例按「当时 localStorage」
 * 重新初始化，互不污染。
 */

vi.mock('../lib/api', () => ({
  fetchPrefs: vi.fn(),
  savePrefs: vi.fn(),
  // persist.ts 在 schedulePush 中查询部署是否提供 /api/prefs（裁剪镜像降级用）
  getPrefsApiCapability: vi.fn(() => 'unknown'),
  PrefsUnsupportedError: class extends Error {},
}))

const LS_KEY = 'verda.profile.v1'

beforeEach(() => {
  localStorage.clear()
  vi.resetModules()
})

describe('profileStore · 本地层（既有契约，保持不变）', () => {
  it('默认回退为 林研究员 / 常青圈', async () => {
    const { useProfileStore, DEFAULT_NAME, DEFAULT_COMPANY } = await import('./profileStore')
    const s = useProfileStore.getState()
    expect(s.name).toBe(DEFAULT_NAME)
    expect(s.company).toBe(DEFAULT_COMPANY)
  })

  it('setName / setCompany 写回 localStorage', async () => {
    const { useProfileStore } = await import('./profileStore')
    useProfileStore.getState().setName('李工')
    useProfileStore.getState().setCompany('某科技公司')
    const raw = JSON.parse(localStorage.getItem(LS_KEY)!)
    expect(raw).toEqual({ name: '李工', company: '某科技公司' })
    // store 内存同步
    expect(useProfileStore.getState().name).toBe('李工')
    expect(useProfileStore.getState().company).toBe('某科技公司')
  })

  it('setProfile 支持局部更新（只改昵称，公司保留）', async () => {
    const { useProfileStore } = await import('./profileStore')
    useProfileStore.getState().setCompany('保留公司')
    useProfileStore.getState().setProfile({ name: '王研究员' })
    const raw = JSON.parse(localStorage.getItem(LS_KEY)!)
    expect(raw).toEqual({ name: '王研究员', company: '保留公司' })
  })

  it('从 localStorage 还原（模拟刷新后重新初始化）', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '赵分析师', company: 'X Lab' }))
    vi.resetModules()
    const { useProfileStore } = await import('./profileStore')
    const s = useProfileStore.getState()
    expect(s.name).toBe('赵分析师')
    expect(s.company).toBe('X Lab')
  })

  it('localStorage 损坏时回退默认，不抛错', async () => {
    localStorage.setItem(LS_KEY, '{不是合法json')
    vi.resetModules()
    const { useProfileStore, DEFAULT_NAME, DEFAULT_COMPANY } = await import('./profileStore')
    const s = useProfileStore.getState()
    expect(s.name).toBe(DEFAULT_NAME)
    expect(s.company).toBe(DEFAULT_COMPANY)
  })

  it('空白昵称回落默认（normalize 口径与远端水合一致）', async () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '   ', company: 'X Lab' }))
    vi.resetModules()
    const { useProfileStore, DEFAULT_NAME } = await import('./profileStore')
    expect(useProfileStore.getState().name).toBe(DEFAULT_NAME)
    expect(useProfileStore.getState().company).toBe('X Lab')
  })
})

describe('profileStore · 服务端真相源（本轮修复的核心契约）', () => {
  it('远端有值 → 以远端为准回填 store 与本地缓存（换 origin / 清存储也能取回资料）', async () => {
    const api = await import('../lib/api')
    const persist = await import('../lib/persist')
    ;(api.fetchPrefs as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      values: { 'profile.name': '云端昵称', 'profile.company': '云端公司' },
      stored: ['profile.company', 'profile.name'],
      groups: {},
    })
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地旧昵称', company: '本地旧公司' }))

    const { useProfileStore } = await import('./profileStore')
    expect(useProfileStore.getState().name).toBe('本地旧昵称') // 首屏先给本地（秒开）

    await persist.hydrateAllPrefs()
    expect(useProfileStore.getState().name).toBe('云端昵称')
    expect(useProfileStore.getState().company).toBe('云端公司')
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({
      name: '云端昵称',
      company: '云端公司',
    })
  })

  it('远端为空（首次）→ 本地资料被自动上推，不丢', async () => {
    const api = await import('../lib/api')
    const persist = await import('../lib/persist')
    ;(api.fetchPrefs as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      values: {},
      stored: [],
      groups: {},
    })
    const saveSpy = api.savePrefs as ReturnType<typeof vi.fn>
    saveSpy.mockResolvedValue(undefined)
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '存量昵称', company: '存量公司' }))

    const { useProfileStore } = await import('./profileStore')
    await persist.hydrateAllPrefs()

    expect(useProfileStore.getState().name).toBe('存量昵称')
    expect(saveSpy).toHaveBeenCalledWith({
      'profile.name': '存量昵称',
      'profile.company': '存量公司',
    })
  })

  it('后端不可用 → 保留本地资料，不清空（降级不丢数据）', async () => {
    const api = await import('../lib/api')
    const persist = await import('../lib/persist')
    ;(api.fetchPrefs as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    localStorage.setItem(LS_KEY, JSON.stringify({ name: '本地昵称', company: '本地公司' }))

    const { useProfileStore } = await import('./profileStore')
    await persist.hydrateAllPrefs()

    expect(useProfileStore.getState().name).toBe('本地昵称')
    expect(JSON.parse(localStorage.getItem(LS_KEY)!)).toEqual({
      name: '本地昵称',
      company: '本地公司',
    })
  })

  it('改动会上推服务端（debounce 后 PUT 映射到 profile.* 键）', async () => {
    vi.useFakeTimers()
    const api = await import('../lib/api')
    const saveSpy = api.savePrefs as ReturnType<typeof vi.fn>
    saveSpy.mockResolvedValue(undefined)

    const { useProfileStore } = await import('./profileStore')
    useProfileStore.getState().setName('新昵称')
    await vi.advanceTimersByTimeAsync(450)

    expect(saveSpy).toHaveBeenCalledWith(
      expect.objectContaining({ 'profile.name': '新昵称' }),
    )
    vi.useRealTimers()
  })
})

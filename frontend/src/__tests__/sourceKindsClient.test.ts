// @vitest-environment node
/**
 * 信源类别注册表适配层契约（计划 v3 §二 G0 展示面 · §八 TC-46 同类守卫）。
 *
 * 三条判据的分工：
 * 1. **快照形状自测**（不依赖后端在线）：注册表里有的类别都进快照，`label` 非空。
 *    快照是"手抄"的替代品 —— 一旦有人直接改 JSON，这里的逐字段比对会先红；
 * 2. **未登记类别回落裸 key**：宁可显示 `gov`，也不许塌成一个统一的"未归类"文案，
 *    那会把"注册表少登记了一类"这件事从界面上抹掉；
 * 3. **真实态失败回落 + 显式 warn**：不允许静默兜底（silentFallbackGuard 同源纪律）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

beforeEach(() => {
  vi.resetModules()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

async function loadClient(dataMode: 'live' | 'fixture') {
  vi.doMock('../store/dataModeStore', () => ({
    isFixtureMode: () => dataMode === 'fixture',
  }))
  return await import('../lib/sourceKindsClient')
}

describe('快照形状自测（不依赖后端在线）', () => {
  it('每条都有 id/label/in_stats，且 label 非空', async () => {
    const { SOURCE_KINDS_FALLBACK } = await loadClient('fixture')
    expect(SOURCE_KINDS_FALLBACK.length).toBeGreaterThan(10)
    for (const k of SOURCE_KINDS_FALLBACK) {
      expect(typeof k.id).toBe('string')
      expect(k.label.length).toBeGreaterThan(0)
      expect(typeof k.in_stats).toBe('boolean')
    }
  })

  it('本功能新增的 user_supplied 在快照里，且中文名是「用户指定」', async () => {
    const { kindLabel } = await loadClient('fixture')
    expect(kindLabel('user_supplied')).toBe('用户指定')
  })

  it('未登记类别回落裸 key（不塌成"未归类"）', async () => {
    const { kindLabel } = await loadClient('fixture')
    expect(kindLabel('not_registered')).toBe('not_registered')
  })

  it('快照 id 集合无重复（重复会让 Object.fromEntries 静默吞掉前一条）', async () => {
    const { SOURCE_KINDS_FALLBACK } = await loadClient('fixture')
    const ids = SOURCE_KINDS_FALLBACK.map((k) => k.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe('真实态取端点 / 失败回落', () => {
  it('fetch 成功 → 用端点载荷（后端标签即界面标签）', async () => {
    const remote = [
      { id: 'official', label: '远端官网', in_stats: true },
      { id: 'user_supplied', label: '远端用户指定', in_stats: true },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ kinds: remote }), { status: 200 })))
    const { fetchSourceKinds } = await loadClient('live')
    const kinds = await fetchSourceKinds()
    expect(kinds.map((k) => k.label)).toEqual(['远端官网', '远端用户指定'])
  })

  it('演示态零网络，直接返回快照', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { fetchSourceKinds, SOURCE_KINDS_FALLBACK } = await loadClient('fixture')
    expect(await fetchSourceKinds()).toEqual(SOURCE_KINDS_FALLBACK)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('端点 500 → 回落快照且 console.warn 留痕一次（不静默）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('err', { status: 500 })))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { fetchSourceKinds, SOURCE_KINDS_FALLBACK } = await loadClient('live')
    expect(await fetchSourceKinds()).toEqual(SOURCE_KINDS_FALLBACK)
    expect(warn).toHaveBeenCalledTimes(1)
    warn.mockRestore()
  })

  it('载荷形状非法（缺 label）→ 回落快照', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ kinds: [{ id: 'x' }] }), { status: 200 })))
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { fetchSourceKinds, SOURCE_KINDS_FALLBACK } = await loadClient('live')
    expect(await fetchSourceKinds()).toEqual(SOURCE_KINDS_FALLBACK)
  })
})

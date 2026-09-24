// @vitest-environment node
/**
 * researchTypesClient 适配层契约（FE-10~13 / R1 注册表单一 / R4 双态同构 / R7 回落不崩）：
 * 真实态 fetch 端点；演示态零网络读快照；快照形状自测；真实态异常回落快照 + warn。
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
  return await import('../lib/researchTypesClient')
}

describe('FE-12 · 快照形状自测（不依赖后端在线）', () => {
  it('恰好 guide/assessment 两 key，且 label/subtitle 非空字符串', async () => {
    const { RESEARCH_TYPES_FALLBACK } = await loadClient('fixture')
    expect(RESEARCH_TYPES_FALLBACK.map((x) => x.key)).toEqual(['guide', 'assessment'])
    for (const o of RESEARCH_TYPES_FALLBACK) {
      expect(o.label.length).toBeGreaterThan(0)
      expect(o.subtitle.length).toBeGreaterThan(0)
    }
  })
})

describe('FE-10 · 真实态取端点', () => {
  it('fetch 成功 → 返回端点载荷（后端文案即卡片文案）', async () => {
    const remote = [
      { key: 'guide', label: '远端攻略', subtitle: 'S1' },
      { key: 'assessment', label: '远端评估', subtitle: 'S2' },
    ]
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify(remote), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    const { fetchResearchTypes } = await loadClient('live')
    const opts = await fetchResearchTypes()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(opts.map((x) => x.label)).toEqual(['远端攻略', '远端评估'])
  })
})

describe('FE-11 · 演示态零网络', () => {
  it('fixture 模式不调 fetch，直接返回快照', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { fetchResearchTypes, RESEARCH_TYPES_FALLBACK } = await loadClient('fixture')
    const opts = await fetchResearchTypes()
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(opts).toEqual(RESEARCH_TYPES_FALLBACK)
  })
})

describe('FE-13 · 真实态异常回落快照不崩', () => {
  it('端点 500 → 回落快照且 console.warn 一次', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('err', { status: 500 })))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { fetchResearchTypes, RESEARCH_TYPES_FALLBACK } = await loadClient('live')
    const opts = await fetchResearchTypes()
    expect(opts).toEqual(RESEARCH_TYPES_FALLBACK)
    expect(warn).toHaveBeenCalledTimes(1)
    warn.mockRestore()
  })

  it('载荷形状非法（缺字段）→ 回落快照', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ key: 'x' }]), { status: 200 })))
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { fetchResearchTypes, RESEARCH_TYPES_FALLBACK } = await loadClient('live')
    expect(await fetchResearchTypes()).toEqual(RESEARCH_TYPES_FALLBACK)
  })

  it('网络抛错（离线）→ 回落快照', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { fetchResearchTypes, RESEARCH_TYPES_FALLBACK } = await loadClient('live')
    expect(await fetchResearchTypes()).toEqual(RESEARCH_TYPES_FALLBACK)
  })
})

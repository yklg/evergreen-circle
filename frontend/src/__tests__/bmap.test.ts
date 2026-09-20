/**
 * M5.1 · BMapGL 加载器：getMapConfig 优先级与降级（后端 map-config 优先；不可达 → 空值降级）。
 * 纯逻辑单测：fetch 经 vi.stubGlobal mock，不触真实网络。
 * 注：VITE_* 环境变量回退在 Vite 构建期注入，非运行时单测范围。
 */
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getMapConfig, loadBMapGL } from '../lib/bmap'

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('script[src*="api.map.baidu.com"]').forEach((s) => s.remove())
  delete (window as unknown as { BMapGL?: unknown }).BMapGL
})

describe('getMapConfig', () => {
  it('后端 map-config 返回 AK + styleId 时优先采用', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, browser_ak: 'backend-ak', map_style_id: 'style-123' }),
      }),
    )
    const cfg = await getMapConfig()
    expect(cfg).toEqual({ browserAk: 'backend-ak', mapStyleId: 'style-123' })
  })

  it('后端不可达（fetch 抛错）时返回空值，不抛异常 → LcMap 降级静态画布', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const cfg = await getMapConfig()
    expect(cfg).toEqual({ browserAk: '', mapStyleId: '' })
  })

  it('后端返回非 200 时同样走空值降级', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))
    const cfg = await getMapConfig()
    expect(cfg).toEqual({ browserAk: '', mapStyleId: '' })
  })
})

/**
 * 加载器 URL 构造守卫（回归）：
 * 百度 v=3.0 不带 type=webgl 时返回的是**经典版** JS API（只注入 window.BMap），
 * window.BMapGL 永不存在 → 回调即便触发也会 reject → 地图必然降级静态画布。
 * 该缺陷不会被 getMapConfig 单测覆盖，故此处对注入的 script src 做断言。
 */
describe('loadBMapGL 脚本注入', () => {
  it('script src 必须带 type=webgl（否则 window.BMapGL 永不出现 → 必然降级）', async () => {
    const pending = loadBMapGL('test-ak')
    const script = document.querySelector('script[src*="api.map.baidu.com"]') as HTMLScriptElement
    expect(script).toBeTruthy()
    expect(script.src).toContain('type=webgl')
    expect(script.src).toContain('ak=test-ak')
    expect(script.src).toContain('callback=__lc_bmap_ready__')

    // 模拟 SDK 就绪：注入命名空间后触发回调 → 应 resolve（证明回调链可用）
    ;(window as unknown as { BMapGL: object }).BMapGL = { Map: class {} }
    ;(window as unknown as { __lc_bmap_ready__: () => void }).__lc_bmap_ready__()
    await expect(pending).resolves.toBeTruthy()
  })
})

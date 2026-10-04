// @vitest-environment jsdom
/**
 * L-INV-4 · 地图尺寸跟随交给 **SDK 自己的监听**（计划 B-v1 的 S2 关闭件）。
 *
 * ## 这支为什么经历过一次反转（写下来，免得下一个人在同一个坑里再翻一次）
 *
 * 1. 我先按直觉写了 `ResizeObserver → map.resize?.()`；
 * 2. 评审要核验时，我查的是社区类型包 `@types/bmapgl@0.0.7` 的 `Map` 面 —— 里面**没有**
 *    `resize`，于是我判定那是条"假通道"并整体撤除。**结论错了，错在取证方法**：
 *    社区包是子集，不能拿来否证厂商 API；
 * 3. 真机直查 `window.BMapGL.Map.prototype`（本仓实际加载 `type=webgl&v=1.0`）：
 *    244 个方法，`resize` / `checkResize` / `enableAutoResize` / `disableAutoResize` 都是
 *    function，`willResize` 不存在；`resize` 源码是
 *    `function(){ if(!apiVersionIsGL()){console.warn("[BMap] resize is only for GL version,
 *    use checkResize instead")} this._watchSize() }`
 *    ⇒ 它不是"手动重画一帧"，而是**打开 SDK 的尺寸监听**。
 *
 * 正解因此变成：建图时调一次 `map.resize()`，**不要**自建 ResizeObserver（两件事会重复订阅）。
 * 另注：「GL 默认是否已开监听」我**没有**定论 —— 现场试过改容器高、画布未跟随，但当时标签页
 * 处于 hidden 状态，rAF/observer 会被节流，不足以作数。显式调用是幂等的正解，所以不必赌这个答案。
 *
 * ## 被守护的契约
 *
 * | # | 契约 | 反例 |
 * |---|---|---|
 * | 1 | live 建图后 `resize()` 恰好调一次 | 忘调 ⇒ 体检台改高度后画布不重绘、出灰边 |
 * | 2 | 调的是 SDK 的方法，不是我们手搓观察器 | 有人再加一条 `new ResizeObserver` ⇒ 双份监听、卸载还得自己管 |
 * | 3 | 地图替身必须**记账** `resize` | 空桩 ⇒ 这条链在测试里免疫（`bmapGLFake.ts` 开档的教训） |
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'

import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { instances, mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'
import { observedElements, resetResizeObservers, roStats } from './helpers/resizeObserverStub'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  class Map extends H.BMapMapBase {}
  return H.fakeBMapModule({ Map })
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const BASE = kaili as unknown as LivingCircleReport
const LC_MAP = join(process.cwd(), 'src', 'components', 'lifecircle', 'LcMap.tsx')
const BMAP = join(process.cwd(), 'src', 'lib', 'bmap.ts')

type FakeMap = { calls: Array<[method: string, args: unknown[]]> }
const methodsOf = (m: FakeMap) => m.calls.map((c) => c[0])
function theMap(): FakeMap {
  if (instances.maps.length === 0) throw new Error('还没建出地图（live 分支没走到？）')
  return instances.maps[0] as FakeMap
}

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  resetResizeObservers()
  mapConfig.browserAk = 'test-ak'
  mapConfig.mapStyleId = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

async function mountLive() {
  render(<LcMap report={BASE} selectedCell={null} onCellPick={vi.fn()} />)
  await waitFor(() => expect(instances.maps.length).toBeGreaterThan(0))
  await waitFor(() => {
    if (!document.querySelector('[data-lc-map="true"]')) throw new Error('地图容器还没出现')
  })
  return theMap()
}

describe('尺寸跟随交给 SDK 的 _watchSize', () => {
  it('正对照：接口确实声明了 resize，且本仓实际加载的是 GL 版', () => {
    const api = readFileSync(BMAP, 'utf8')
    expect(api).toMatch(/^\s*resize\(\): void\s*$/m)
    expect(api).toContain('type=webgl')            // `resize` 是 GL 专用；换了加载方式这条就得重议
  })

  it('live 建图 ⇒ SDK resize() 恰好被打开一次', async () => {
    const map = await mountLive()
    const seq = methodsOf(map)
    expect(seq.filter((m) => m === 'resize').length).toBe(1)
    expect(seq.indexOf('resize')).toBeGreaterThan(seq.indexOf('constructor'))
  })

  it('不自建 ResizeObserver —— 监听交给 SDK，避免双份订阅与多一份卸载负担', async () => {
    const src = readFileSync(LC_MAP, 'utf8')
    expect(src).not.toContain('new ResizeObserver')
    await mountLive()
    expect(roStats.created).toBe(0)
    expect(observedElements()).toHaveLength(0)
  })
})

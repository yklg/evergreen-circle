// @vitest-environment jsdom
/**
 * C5 · 地图点选格的**坐标契约 + 四条静默分支**（计划 tender-harbor-bull.md 的 P0 用例）。
 *
 * ## 为什么这份文件存在
 *
 * 「逐格台账」卡有两条选格入口：卡片格阵（DOM，早已可测）与**在地图上点一块**。
 * 后者此前一条断言都没有 —— 因为拿不到真实指针点击：百度 GL 不认合成事件，
 * CDP 点击只能落在元素中心，而地图中心恰被可拖的中心标记占着。于是连续两轮
 * "猜字段名"都靠用户真机点一次来试错。
 * 现在 `BMapMapBase.handlers` 能把真 handler 取出来 ⇒ 喂载荷即可测。
 *
 * ## 被守护的契约
 *
 * `onBlankClick` 里"没选上格"有**四条互不相同**的原因，一条都不许静默：
 *
 * | # | 原因 | 期望 |
 * |---|---|---|
 * | 1 | 事件里没有经纬度字段（键名不对 / 压根没带） | 不采纳 + 探针报真实键名 |
 * | 2 | 投影平面坐标（`point`，墨卡托米） | **永不采纳**（北极圈事故，见 `geo.ts`） |
 * | 3 | 这份报告没台账（ev-1 / 离线骨架） | 不选格、关卡照旧、探针说"台账没读到" |
 * | 4 | 点落在格阵外 | 清选中 + 关卡，**不许回落到最近一格** |
 *
 * 另钉一条等价性：**地图点 (i,j) 的格心 ⇒ 必须报回 (i,j)**。用的格心取自
 * `cellCenter`，也就是卡片格阵与 C5 那对方框共用的同一处换算 —— 这条红了就意味着
 * "点在这格、卡片说那格"（行/列被转置是这类代码最经典的错法）。
 *
 * ## 效力上限（防"测试全绿＝全对"错觉）
 *
 * 本文件喂的是**我们假设的**载荷形状，钉的是"取到之后对不对、取不到时伤不伤人"。
 * 它**答不了**"真机上地图级 click 到底带哪个键名"—— 那只有真机一次点击能答，
 * 探针（`点选分诊`）就是为那一次准备的。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import contract from './fixtures/cellsLedgerContract.json'
import type { CellsLedgerRaw, LivingCircleReport } from '../types'
import { cellCenter } from '../lib/livingCircle'
import { instances, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

const h = vi.hoisted(() => ({ warnings: [] as string[] }))

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  class Map extends H.BMapMapBase {
    private _c: HTMLElement | null = null
    override getContainer(): HTMLElement {
      this._c ??= document.createElement('div')
      return this._c
    }
    override pointToPixel(p: { lng: number; lat: number }) {
      return { x: p.lng * 100, y: p.lat * 100 }
    }
  }
  // AK 非空 ⇒ 走 live 分支（降级画布上没有地图级 click，本文件只测真实态那条链）
  return H.fakeBMapModule({ Map })
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const LEDGER = contract.sample as unknown as CellsLedgerRaw
const BASE = kaili as unknown as LivingCircleReport
const WITH_LEDGER: LivingCircleReport = {
  ...BASE,
  caliber: { ...BASE.caliber!, cells_ledger: LEDGER },
}

/** 台账里"在可达区内"的格 —— 点它们的格心必须各自命中。 */
const INSIDE: Array<[number, number]> = LEDGER.inside.flatMap(
  (row: string, i: number) => [...row]
    .map((ch: string, j: number) => ({ ch, cell: [i, j] as [number, number] }))
    .filter((x) => x.ch === '1')
    .map((x) => x.cell),
)

/** 已建出的假地图（`BMapMapBase` 构造时自报家门）。取不到＝live 分支没走到，报错要说人话。 */
function mapList(): Array<{ handlers: Record<string, (...a: unknown[]) => unknown> }> {
  if (instances.maps.length === 0) throw new Error('还没建出地图（live 分支没走到？）')
  return instances.maps as Array<{ handlers: Record<string, (...a: unknown[]) => unknown> }>
}

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  h.warnings.length = 0
  vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => {
    h.warnings.push(args.map(String).join(' '))
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

async function mount(report: LivingCircleReport, onCellPick = vi.fn()) {
  render(<LcMap report={report} showJudgeScale selectedCell={null} onCellPick={onCellPick} />)
  await waitFor(() => expect(typeof clickHandler()).toBe('function'))
  return onCellPick
}

function clickHandler(): (e?: unknown) => unknown {
  return mapList()[0].handlers.click as (e?: unknown) => unknown
}

function fire(payload?: unknown) {
  act(() => { clickHandler()(payload) })
}

const probeLines = () => h.warnings.filter((w) => w.includes('点选分诊'))

describe('LcMap 地图点选格 · 坐标契约与四条静默分支', () => {
  it('点 (i,j) 的格心 ⇒ 报回的就是 (i,j)（与卡片格阵同一处换算，行/列不许转置）', async () => {
    expect(INSIDE.length).toBeGreaterThan(0)
    const onCellPick = await mount(WITH_LEDGER)
    for (const [i, j] of INSIDE) {
      const [lng, lat] = cellCenter(LEDGER, i, j)
      // 轴映射单独钉一层：只有"格心→索引"的往返时，若 cellCenter 与 cellIndex **一起**
      // 转置（行拿去比经度、列拿去比纬度），往返照样自洽、测试照样绿 —— 而卡片说这格、
      // 地图选那格。故这里用台账中心做基准把"行=纬度、列=经度"分开验一遍。
      if (i !== 1) expect((lat - LEDGER.center[1]) * (i - 1), `行 ${i} 应沿纬度排布`).toBeGreaterThan(0)
      if (j !== 1) expect((lng - LEDGER.center[0]) * (j - 1), `列 ${j} 应沿经度排布`).toBeGreaterThan(0)
      if (i === 1) expect(lat, '中心行的纬度必须与台账中心同').toBeCloseTo(LEDGER.center[1], 9)
      if (j === 1) expect(lng, '中心列的经度必须与台账中心同').toBeCloseTo(LEDGER.center[0], 9)

      onCellPick.mockClear()
      fire({ latlng: { lng, lat } })
      expect(onCellPick, `格 (${i},${j}) 的格心应选回自己`).toHaveBeenCalledWith([i, j])
    }
  })

  it('分支 1：事件不带任何经纬度字段 ⇒ 不选格、关卡照旧、探针报出真实键名', async () => {
    const onCellPick = await mount(WITH_LEDGER)
    expect(() => fire()).not.toThrow()               // 无 payload
    expect(onCellPick).toHaveBeenCalledWith(null)     // 「点空白关卡」没被连带打死
    expect(probeLines().at(-1)).toContain('实际键=[]')
    expect(probeLines().at(-1)).toContain('经纬度=null')
  })

  it('分支 2：只带墨卡托平面 `point` ⇒ 永不采纳（北极圈那类值域合法的脏值）', async () => {
    const onCellPick = await mount(WITH_LEDGER)
    fire({ point: { lng: 11440230.81, lat: 2860409.52 } })
    expect(onCellPick).toHaveBeenCalledWith(null)
    expect(h.warnings.join('\n')).toContain('拒绝该坐标来源')
    // 采纳的那一路必须是 null：有人把 `point` 加进白名单，这行立刻变成坐标。
    expect(probeLines().at(-1)).toContain('经纬度=null')
    // 脏值不能只是被吞掉 —— 探针要把它的真实形状留给下一轮真机。
    expect(probeLines().at(-1)).toContain('point={"lng":11440230.81,"lat":2860409.52}')
  })

  it('分支 3：报告不带台账（ev-1 / 离线骨架）⇒ 不选格、关卡照旧、探针说"台账没读到"', async () => {
    const onCellPick = await mount(BASE)             // kaili 出厂件没有 cells_ledger
    const [lng, lat] = cellCenter(LEDGER, 1, 1)
    fire({ latlng: { lng, lat } })
    expect(onCellPick).toHaveBeenCalledWith(null)
    expect(probeLines().at(-1)).toContain('台账=没读到')
    expect(probeLines().at(-1)).toContain('经纬度=')   // 坐标其实取到了
  })

  it('分支 4：点落在格阵外 ⇒ 清选中并关卡，探针给出距中心多远（不许回落到最近一格）', async () => {
    const onCellPick = await mount(WITH_LEDGER)
    fire({ latlng: { lng: 107.9758, lat: 26.58 } })   // 夹具里现成的"格阵外"坐标
    expect(onCellPick).toHaveBeenCalledWith(null)
    const line = probeLines().at(-1) ?? ''
    expect(line).toContain('台账=读到')
    expect(line).toMatch(/格=无（距中心 \d+m）/)
  })

  it('探针每个实例只打一次，且四路信息齐（缺一路＝下次又得靠猜）', async () => {
    await mount(WITH_LEDGER)
    fire({})
    fire({})
    fire({})
    expect(probeLines()).toHaveLength(1)
    const line = probeLines()[0]
    for (const key of ['实际键=', '经纬度=', '台账=', '格=']) expect(line).toContain(key)
  })
})

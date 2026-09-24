// @vitest-environment jsdom
/**
 * 阶段 0（T-FE-05）· 底图注记纪律：**关掉第三方设施名与图钉，保留空间参照**。
 *
 * ## 被守护的两起事故（都不是假想）
 *
 * **事故一 · 改了等于没改。** `bmapStyle.ts` 里的注记关闭规则写了很久，却从未生效：
 * `backend/.env` 配了 `BAIDU_MAP_STYLE_ID`（2026-09-21 发布的「高对比浅色 · 清晰标注」样式），
 * 而 `LcMap` 的分支是「styleId 有值就用 styleId」。内置模板成了**死代码**，
 * 百度第三方设施名照旧上屏。「文件改了 / 注释写了 / 单测没有」＝ 谁都不知道运行时走哪条分支。
 *
 * **事故二 · 规则本身是无效的。** 2026-09-22 用真实底图实测（凯里老街，zoom 13/15/17）发现：
 * 只写 `{poilabel, labels: off}` 时，图上仍有「和谐家园 / 香枫庭院 / 居然之家 / 交通驾校」，
 * 且**百度自带的 POI 图钉一个不少** —— 而那些图钉正是「第三方点冒充自家数据」的最强观感来源。
 * 详见 `bmapStyle.ts` 文件头的 ①~⑤ 条实测结论。
 *
 * ## 本文件锁五件事
 *
 * 1. **通配 + 图钉**：必须同时关 `all/labels` 与 `all/labels.icon`（后者单列，关不到就是漏点）。
 * 2. **顺序即语义**：白名单必须排在通配关**之后**（颠倒 = 参照系全灭）。
 * 3. **白名单不得带 `color`**：带上会把刚开回的可见性再次打掉（实测 zoom 13 一片空白）。
 * 4. **分支行为**：`mapStyleId` 空 → 下发 `styleJson`（且同一引用）；非空 → 下发 `styleId`。
 * 5. **面层只留 `land` 一条**：道路/水系/绿地交还百度默认 —— 任何道路面层键都会把整层打掉
 *    （2026-09-24 真机实测，见 `bmapStyle.ts` ⑪⑫）。⚠️ 本文件旧版只查 land/water/green
 *    而漏查 road，正是那次「道路被涂白」漂移静默数月的原因。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { LC_KEEP_LABELS, LC_MAP_STYLE_LIGHT } from '../lib/bmapStyle'
import {
  assertBasemapStylesSound,
  mapConfig,
  resetInstances,
  resetStyleCalls,
  styleCalls,
} from './helpers/bmapGLFake'

/**
 * 替身取自 `helpers/bmapGLFake`（全套件唯一出口）。本文件是 `setMapStyleV2` 记录契约的
 * 定义方 —— 其余 4 个地图测试文件必须复用同一份，不得再各写一个空桩。
 */
vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule()
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')
/** 真实实现（绕过上面的模块 mock）—— 契约层用例验的是解析逻辑本身，必须用真模块。 */
const realBmap = await vi.importActual<typeof import('../lib/bmap')>('../lib/bmap')

const REPORT = kaili as unknown as LivingCircleReport

type Rule = { featureType?: string; elementType?: string; stylers?: Record<string, unknown> }
const RULES = LC_MAP_STYLE_LIGHT as Rule[]
const ruleOf = (ft: string, et: string) =>
  RULES.find((r) => r.featureType === ft && r.elementType === et)
const idxOf = (ft: string, et: string) =>
  RULES.findIndex((r) => r.featureType === ft && r.elementType === et)

/** 记录每次 `setMapStyleV2` 的入参 —— 分支行为的唯一可观测出口。 */
beforeEach(() => {
  resetStyleCalls()
  resetInstances()
  mapConfig.browserAk = 'test-ak'
  mapConfig.mapStyleId = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('阶段 0 · 注记纪律（内容层）', () => {
  it('文字注记用通配 `all` 全关 —— 枚举 POI 家族不可行（实测 20 个候选名全部无效）', () => {
    const r = ruleOf('all', 'labels')
    expect(r, '缺少 `all/labels` 通配规则 ⇒ 叫不出名字的 POI 家族会漏网（居然之家/和谐家园就是这么漏的）').toBeTruthy()
    expect(r!.stylers?.visibility).toBe('off')
  })

  it('图钉必须**单独**关（`labels.icon` 是独立 elementType，关 labels 关不掉它）', () => {
    const r = ruleOf('all', 'labels.icon')
    expect(r, '缺少 `all/labels.icon` ⇒ 百度自带 POI 图钉照旧上屏，被读成自家数据').toBeTruthy()
    expect(r!.stylers?.visibility).toBe('off')
  })

  it('白名单开回「空间参照」（行政区名 + 各级路名），且**只写 visibility**', () => {
    expect(LC_KEEP_LABELS.length).toBeGreaterThanOrEqual(6)
    for (const ft of LC_KEEP_LABELS) {
      const r = ruleOf(ft, 'labels')
      expect(r, `白名单要素 ${ft} 没有开回规则`).toBeTruthy()
      expect(r!.stylers?.visibility).toBe('on')
      // ⚠️ 带 color 会把刚开回的可见性再次打掉（官方「最后一条生效」语义；实测 zoom 13 一片空白）
      expect(
        r!.stylers?.color,
        `${ft} 的开回规则带了 color —— 实测会让整层注记再次消失，见 bmapStyle.ts 第 ④ 条`,
      ).toBeUndefined()
    }
    // 白名单里不得混入 POI 家族（`*label` 形态的第三方经营主体名）
    for (const ft of LC_KEEP_LABELS) {
      expect(String(ft)).not.toMatch(/poilabel|estatelabel|shoppinglabel|companylabel/)
    }
  })

  it('顺序即语义：**先关后开**（颠倒 = 参照系全灭）', () => {
    const hideAt = idxOf('all', 'labels')
    const hideIconAt = idxOf('all', 'labels.icon')
    expect(hideAt).toBeGreaterThanOrEqual(0)
    expect(hideIconAt).toBeGreaterThanOrEqual(0)
    for (const ft of LC_KEEP_LABELS) {
      expect(
        idxOf(ft, 'labels'),
        `白名单 ${ft} 排在通配关之前 —— 会被后置的通配规则覆盖，等于没开`,
      ).toBeGreaterThan(Math.max(hideAt, hideIconAt))
    }
  })

})

describe('阶段 0 · 面层纪律（内容层）', () => {
  it('面层只保留 land 一条 —— 道路分级交还百度默认（实测：任何道路面层键都会把整层打掉）', () => {
    expect(ruleOf('land', 'geometry')?.stylers?.color, '缺少 land 面色（画布底色对齐）').toBeTruthy()
    // ⚠️ 此处曾只查 land/water/green「三类齐全」而从不查 road —— 于是 8 条面层规则里 4 条
    // 把道路涂白的漂移静默了很久（本次事故）。现在改为**负向不变量**：道路键一条都不许有。
    for (const ft of ['road', 'arterial', 'highway', 'local']) {
      for (const et of ['geometry', 'geometry.stroke']) {
        expect(
          ruleOf(ft, et),
          `${ft}/${et} —— 实测会让整条道路层不可见（见 bmapStyle.ts ⑪），不得写回`,
        ).toBeUndefined()
      }
    }
    // 未经验证有效的面色键同样不得留：写了等于没写，属死代码（见 ⑫）
    for (const ft of ['water', 'green', 'building']) {
      expect(ruleOf(ft, 'geometry'), `${ft} 面色未被真机验证有效（见 ⑫），不得留在下发数组里`).toBeUndefined()
    }
    const faceRules = RULES.filter((r) => !String(r.elementType ?? '').startsWith('labels'))
    expect(faceRules, '面层规则恰好 1 条（land），多一条即越线').toHaveLength(1)
  })
})

describe('阶段 0 · styleId / styleJson 分支行为（运行时层）', () => {
  it('styleId 为空 → 下发 styleJson 且**就是内置模板**（关注记纪律真的生效）', async () => {
    mapConfig.mapStyleId = ''
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(styleCalls.length).toBeGreaterThan(0))
    const arg = styleCalls.at(-1) as { styleId?: string; styleJson?: unknown[] }
    expect(arg.styleId).toBeUndefined() // 不得同时下发（官方：二选一）
    expect(arg.styleJson).toBe(LC_MAP_STYLE_LIGHT) // 同一引用，不能是别处的副本
    const off = (arg.styleJson ?? []).find(
      (x) => (x as Rule).featureType === 'all' && (x as Rule).elementType === 'labels.icon',
    ) as Rule | undefined
    expect(off?.stylers?.visibility).toBe('off') // 下发的 JSON 里确实带图钉关闭
    assertBasemapStylesSound() // 替身层眼睛已装上：确实收到下发且结构自洽
  })

  it('styleId 非空 → 下发 styleId（显式 opt-in 时仍可用控制台样式）', async () => {
    mapConfig.mapStyleId = 'console-style-id'
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(styleCalls.length).toBeGreaterThan(0))
    const arg = styleCalls.at(-1) as { styleId?: string; styleJson?: unknown[] }
    expect(arg.styleId).toBe('console-style-id')
    expect(arg.styleJson).toBeUndefined()
  })
})

describe('阶段 0 · 后端下发的 styleId 默认被抑制（契约层）', () => {
  it('map_style_id 为空时 getMapConfig 返回空串（不回填旧值、不报错）', async () => {
    // 真实抑制在后端 `main.life_circle_map_config()`（`BAIDU_ALLOW_CONSOLE_STYLE` 未置位时恒返回空），
    // 由 backend/tests/test_living_circle_api.py 覆盖；此处只钉住前端解析不引入偏差。
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, browser_ak: 'ak', map_style_id: '' })))
    const cfg = await realBmap.getMapConfig()
    expect(cfg.mapStyleId).toBe('')
    expect(cfg.browserAk).toBe('ak')
    fetchSpy.mockRestore()
  })

  it('后端返回非空 styleId 时如实透传（前端不擅自改写后端决定）', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify({ ok: true, browser_ak: 'ak', map_style_id: 'sid-1' })),
      )
    const cfg = await realBmap.getMapConfig()
    expect(cfg.mapStyleId).toBe('sid-1')
    fetchSpy.mockRestore()
  })
})

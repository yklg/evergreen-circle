// @vitest-environment jsdom
/**
 * 片 5 · 取证上屏三件的契约（计划 v7.1 · 用户拍板档乙「常驻 + 实时」+ 图层重量甲「只描边」）。
 *
 * 守护的四条不变量：
 *  1. **缺席即未发生**：`caliber.forensic` / `evidence_anchors` 是后端"不传不发"的键 ⇒
 *     前端取值出口必须回 `null` / `[]`，**不许**回落成 `rounds: 0`（那等于替一次没发生的
 *     取证举证），报告页那节也必须整块不出现。
 *  2. **partial 与 degraded 分家**：`partialBanner()` 不得借用降级那句「已降级为离线估算」，
 *     且两族成因（额度不足 / 取证阶段被熔断）各说一句**为真**的话。
 *  3. **证据域图层默认关**，打开后「一盘一环、虚线数 = 未查全的盘数」；正向对照用手工
 *     两盘（一查全一未查全）钉死，不靠"和源数据比一下"那种同源空转断言。
 *  4. **`round` 事件只喂回合回调**：不改 stage/percent（后端那条分支明确不发 progress），
 *     载荷缺 `round` 时静默不调用而不是抛。
 *
 * BMapGL 走 `helpers/bmapGLFake` 同一份替身；`browserAk=''` 逼出降级画布分支（SVG），
 * 因为图层的两条分支里只有这条能在 jsdom 里被 DOM 观察到（BMap 分支的 Circle 由
 * `notesToggle` 那套实例记录覆盖，本文件不重复搭第二套替身）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type {
  EvidenceDisc,
  ForensicAccount,
  ForensicRoundRow,
  LivingCircleReport,
  Report,
} from '../types'
import {
  evidenceDiscs,
  evidenceDiscTitle,
  forensicAccount,
  isSyntheticDisc,
  lcEvidenceDiscColor,
  lcRing,
  lcToPx,
  LC_CANVAS,
  LC_CAT_COLOR,
  LC_ISO_COLORS,
  partialBanner,
  roundAnchorCell,
} from '../lib/livingCircle'
import { instances, mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule()
})
vi.mock('../components/VChart', () => ({
  VChart: ({ spec }: { spec: { title?: string } }) => <div data-testid="mock-chart">{spec?.title ?? 'chart'}</div>,
}))

const LcMapModule = await import('../components/lifecircle/LcMap')
const LcMap = LcMapModule.default
const LifeCircleReportViewModule = await import('../components/lifecircle/LifeCircleReportView')
const LifeCircleReportView = LifeCircleReportViewModule.default
const { __test: flowTest } = await import('../lib/lifeCircleFlow')

const BASE = kaili as unknown as LivingCircleReport

function disc(
  category: string,
  complete: boolean,
  exhausted: number,
  over: Partial<EvidenceDisc> = {},
): EvidenceDisc {
  return {
    category,
    anchor: [BASE.scene.center[0], BASE.scene.center[1]],
    request_radius_m: 2300,
    exhausted_radius_m: exhausted,
    complete,
    cap_hit: false,
    stop_reason: complete ? null : 'page_cap',
    ...over,
  }
}

/** 逐趟账目夹具。
 *
 * ⚠️ 两趟的数字**抄自真夹具** `src/dev/fixtures/lcP5Scenarios.json · one_round.caliber.forensic
 * .rounds_detail`（由 `skip/tmp/lc_p5_dump.py` 从生产编排落盘），不是随手编的形状：
 * 第 0 趟派发（42 需求 / 25 发 / 17 砍 / 124→95 未决格），第 1 趟**未派发**
 * （17 需求 / 额度只容 3 / 14 砍 / 95→95）。评审 P0-2 的教训正是"自制形状恰好让假话为真"——
 * 未派发行若填 `sent:0`，「只判了一次」那种文案就能蒙过整张表。 */
function round(passNo: number, dispatched: boolean, over: Partial<ForensicRoundRow> = {}): ForensicRoundRow {
  return dispatched
    ? {
        pass_no: passNo,
        dispatched,
        calls: 31,
        pool_remaining: 3,
        anchors_planned: 42,
        anchors_sent: 25,
        anchors_used: 25,
        anchors_merged: 0,
        anchors_not_run: 0,
        anchors_dropped: 17,
        starved_terms: 0,
        points_added: 75,
        cells_undecided_before: 124,
        cells_blind_before: 0,
        cells_undecided_after: 95,
        cells_blind_after: 0,
        asking: ['market', 'pharmacy', 'primary'],
        stopped_by: 'forensic_pool_short',
        per_category: {},
        ...over,
      }
    : {
        pass_no: passNo,
        dispatched,
        calls: 0,
        pool_remaining: 3,
        anchors_planned: 17,
        anchors_sent: 3,
        anchors_used: 0,
        anchors_merged: 0,
        anchors_not_run: 0,
        anchors_dropped: 14,
        starved_terms: 0,
        points_added: 0,
        cells_undecided_before: 95,
        cells_blind_before: 0,
        cells_undecided_after: 95,
        cells_blind_after: 0,
        asking: ['market', 'pharmacy', 'primary'],
        stopped_by: 'rounds_exhausted',
        per_category: {},
        ...over,
      }
}

function account(over: Partial<ForensicAccount> = {}): ForensicAccount {
  return {
    rounds: 1,
    judging_passes: 2,
    max_rounds: 1,
    stop_reason: 'rounds_exhausted',
    pool_total: 34,
    pool_used: 31,
    pool_remaining: 3,
    anchors_planned: 42,
    anchors_sent: 25,
    anchors_used: 25,
    anchors_merged: 0,
    anchors_not_run: 0,
    anchors_dropped: 17,
    calls: 31,
    points_added_judging_only: 75,
    points_policy: '盲区按「首轮 + 各取证回合」并集的点位判；8 类计数与评分仍按首轮点位',
    per_category: {},
    rounds_detail: [round(0, true), round(1, false)],
    ...over,
  }
}

beforeEach(() => {
  resetStyleCalls()
  resetInstances()
  mapConfig.browserAk = '' // 逼出降级画布（SVG）分支
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('片 5-1 · 取值出口：缺席即未发生，不造 0 轮', () => {
  it('夹具（判盲口径升级前的快照）确实没有 forensic / evidence_anchors 两键', () => {
    // 前提守卫：下面那条断言若没有这条，就是空转
    expect(BASE.caliber?.forensic).toBeUndefined()
    expect(BASE.caliber?.evidence_anchors).toBeUndefined()
  })

  it('缺键报告 → forensicAccount=null、evidenceDiscs=[]（不是 rounds:0、不是空盘伪装）', () => {
    expect(forensicAccount(BASE)).toBeNull()
    expect(evidenceDiscs(BASE)).toEqual([])
  })

  it('有账目时原样交出，且逐盘 title 带得出「实测/请求/完整性」三件事', () => {
    const lc: LivingCircleReport = {
      ...BASE,
      caliber: { ...BASE.caliber!, forensic: account(), evidence_anchors: [disc('market', false, 1398)] },
    }
    expect(forensicAccount(lc)?.rounds).toBe(1)
    const t = evidenceDiscTitle(evidenceDiscs(lc)[0])
    expect(t).toContain('1398')
    expect(t).toContain('2300')
    expect(t).toContain('未查全')
    expect(t).toContain('page_cap')
    // 「查全」不能只用 `toContain` —— 它是「未查全」的子串，那样写恒真（评审 P2 弱断言）。
    const done = evidenceDiscTitle(disc('pharmacy', true, 2297))
    expect(done).toMatch(/· 查全$/)
    expect(done).not.toContain('未查全')
    expect(done).toContain('药店') // 三要素键不落英文：pharmacy 不是 8 个展示类之一
    expect(evidenceDiscTitle(disc('market', false, 1398, { cap_hit: true }))).toContain('被接口上限截断')
  })
})

describe('片 5-2 · partial 与 degraded 分家，两族成因各说各的话', () => {
  it('额度不足 ⇒ 说"不是接口故障"；取证阶段被熔断 ⇒ 说"被熔断"；两者都不借用降级那句', () => {
    const short = partialBanner({ partial: { stage: 'forensic', detail: 'forensic_pool_short', note: '取证额度不足（扩容回合的计划份额不够铺完可达区）' } })
    const melt = partialBanner({ partial: { stage: 'forensic', detail: 'total_meltdown', note: '百度调用在取证阶段被熔断' } })
    expect(short?.title).toContain('不是接口故障')
    expect(short?.title).not.toContain('熔断')
    expect(melt?.title).toContain('被熔断')
    expect(melt?.title).not.toContain('不是接口故障')
    for (const b of [short, melt]) {
      expect(b?.title).not.toContain('已降级为离线估算') // 借 degradeBanner 那句就是说假话
      expect(b?.tone).toBe('warn') // 部分完成不是事故 ⇒ 不占 risk 色阶
    }
    expect(short?.body).toContain('扩容回合')
  })

  it('没有 partial 的报告 → null（横幅整块不出现）', () => {
    expect(partialBanner({})).toBeNull()
    expect(partialBanner(BASE)).toBeNull()
  })
})

describe('片 5-3 · 证据域图层：默认关，打开后一盘一环、虚线=未查全', () => {
  const discPolys = (root: HTMLElement) =>
    Array.from(root.querySelectorAll('svg polygon')).filter((p) =>
      p.querySelector('title')?.textContent?.includes('证据盘'),
    )

  it('默认（不传 showEvidenceDiscs）→ 一个盘都不画', async () => {
    const lc: LivingCircleReport = {
      ...BASE,
      caliber: { ...BASE.caliber!, evidence_anchors: [disc('market', true, 1500), disc('pharmacy', false, 1200)] },
    }
    const { container } = render(<LcMap report={lc} />)
    await waitFor(() => expect(container.querySelector('svg[aria-label^="生活圈等时圈画布"]')).toBeTruthy())
    expect(discPolys(container)).toHaveLength(0)
  })

  it('打开 → 手工两盘（一查全一未查全）画出两环，且只有未查全那环是虚线', async () => {
    const lc: LivingCircleReport = {
      ...BASE,
      caliber: { ...BASE.caliber!, evidence_anchors: [disc('market', true, 1500), disc('pharmacy', false, 1200)] },
    }
    const { container } = render(<LcMap report={lc} showEvidenceDiscs />)
    await waitFor(() => expect(discPolys(container).length).toBe(2))
    const dashed = discPolys(container).filter((p) => p.getAttribute('stroke-dasharray') === '6 4')
    expect(dashed).toHaveLength(1)
    expect(dashed[0].querySelector('title')?.textContent).toContain('未查全')
    // 只描边（重量甲）：任何一环都不带填充色，否则等时圈色阶会被叠糊
    for (const p of discPolys(container)) expect(p.getAttribute('fill')).toBe('none')
  })

  it('环的像素直径 = 米 × 该轴比例（各向异性）—— 既不是正圆，也不是放大 57 倍的巨环（评审 P0-1）', () => {
    // 这一条是 P0-1 的回归锁。原缺陷：`lcRing` 把米→度写成 `111320 × π/180`，半径涨 180/π≈57.3 倍
    // ⇒ 真夹具 34 盘 × 48 顶点**没有一个**落在 860×620 画布内（描边档整层不可见、填充档整幅染色）。
    // 上面那条"一盘一环"的用例数的是 DOM 里有没有 polygon，**看不见几何错**，所以才补这一条。
    const c = BASE.scene.center
    const r = 1000
    const pts = lcRing(c, r).map(([lng, lat]) => lcToPx(c, lng, lat))
    const xs = pts.map((p) => p[0])
    const ys = pts.map((p) => p[1])
    const { R, W, H } = LC_CANVAS
    const dx = Math.max(...xs) - Math.min(...xs)
    const dy = Math.max(...ys) - Math.min(...ys)
    expect(dx).toBeCloseTo((2 * r * (W / 2)) / R, 1) // 横轴 344px
    expect(dy).toBeCloseTo((2 * r * (H / 2)) / R, 1) // 纵轴 248px —— 两轴本就不同 ⇒ 正圆必错
    expect(dx / dy).not.toBeCloseTo(1, 1)
    expect(pts.every(([x, y]) => x >= -1 && x <= W + 1 && y >= -1 && y <= H + 1)).toBe(true)
  })

  it('三要素盘的配色不落进等时圈描边色（评审 P1：24/34 盘曾与五级色阶同色）', () => {
    const isoStroke = LC_ISO_COLORS[0].stroke
    for (const k of ['market', 'pharmacy', 'primary']) expect(lcEvidenceDiscColor(k)).not.toBe(isoStroke)
    // 配色借用展示类：药店∈医疗、小学∈教育 ⇒ 与图例里那些点是同一枚色，不新造色卡
    expect(lcEvidenceDiscColor('pharmacy')).toBe(LC_CAT_COLOR.medical)
    expect(lcEvidenceDiscColor('primary')).toBe(LC_CAT_COLOR.education)
    expect(lcEvidenceDiscColor('market')).toBe(LC_CAT_COLOR.market)
  })

  it('live 分支：勾开才建 Circle（只描边 / 不参与命中 / 虚线=未查全），且勾一次不复位相机', async () => {
    mapConfig.browserAk = 'test-ak' // 走 BMapGL 分支（此前替身没有 `Circle` ⇒ 这条分支整块不可达）
    const lc: LivingCircleReport = {
      ...BASE,
      caliber: {
        ...BASE.caliber!,
        evidence_anchors: [disc('market', true, 1500), disc('pharmacy', false, 1200)],
      },
    }
    const { rerender } = render(<LcMap report={lc} />)
    await waitFor(() => expect(instances.maps.length).toBe(1))
    const map = instances.maps[0] as { calls: [string, unknown[]][] }
    const camResets = () => map.calls.filter(([m]) => m === 'centerAndZoom').length
    expect(instances.circles).toHaveLength(0) // 默认关：一个都不建
    const before = camResets()
    expect(before).toBeGreaterThan(0) // 前提守卫：挂载时确实复位过一次，否则下面那条恒真

    rerender(<LcMap report={lc} showEvidenceDiscs />)
    await waitFor(() => expect(instances.circles.length).toBe(2))
    const circles = [...instances.circles] as { opts: Record<string, unknown>; radius: number }[]
    for (const c of circles) {
      expect(c.opts.fillOpacity).toBe(0)
      expect(c.opts.enableClicking).toBe(false)
    }
    expect(circles.map((c) => c.radius)).toEqual([1500, 1200])
    expect(circles.map((c) => c.opts.strokeStyle)).toEqual(['solid', 'dashed'])
    expect(camResets()).toBe(before) // 视图开关不该触发整幅重建 ⇒ 相机不动

    rerender(<LcMap report={lc} />)
    await waitFor(() => expect(instances.circles.length).toBe(2)) // 不新建
    const removed = instances.removed as unknown[]
    for (const c of circles) expect(removed).toContain(c) // 关掉要自己摘干净
    expect(camResets()).toBe(before)
  })
})

describe('片 5-4 · 报告页取证小节与 chip：有账才出现，数字同源', () => {
  function reportWith(mutate: (lc: LivingCircleReport) => LivingCircleReport): Report {
    const rep = structuredClone(getLivingCircleReportMock('lc-kaili')) as unknown as Report & {
      living_circle: LivingCircleReport
    }
    rep.living_circle = mutate(rep.living_circle)
    return rep
  }

  it('有 forensic → 小节出现，chip 与表格行数都读同一份账目', () => {
    const acct = account()
    const rep = reportWith((lc) => ({
      ...lc,
      caliber: { ...lc.caliber!, forensic: acct, evidence_anchors: [disc('market', false, 1398)] },
      partial: { stage: 'forensic', detail: 'forensic_pool_short', note: '取证额度不足' },
    }))
    render(
      <MemoryRouter>
        <LifeCircleReportView report={rep} />
      </MemoryRouter>,
    )
    expect(screen.getByText('取证回合')).toBeTruthy()
    expect(screen.getByText(`取证 ${acct.rounds} 轮 · ${acct.calls} 次调用`)).toBeTruthy()
    expect(screen.getByText('证据域 1 盘')).toBeTruthy()
    // 表头 1 行 + 逐趟 2 行；「未派发」那趟要把**真账**念出来（评审 P0-2）
    expect(screen.getAllByRole('row')).toHaveLength(acct.rounds_detail.length + 1)
    expect(screen.getByText('未派发')).toBeTruthy()
    expect(screen.getByText('需求 17 · 额度容 3 · 一个没打')).toBeTruthy()
    expect(screen.getByText('— / 14')).toBeTruthy()
    expect(screen.getByText(/判盲共\s*2\s*趟/)).toBeTruthy()
    // 反向锁：旧那句「只判了一次」与同屏的 `judging_passes=2` 自相矛盾，不许再回来
    expect(screen.queryByText(/只判了一次/)).toBeNull()
    expect(screen.getByText(/扩容回合没把可达区铺完/)).toBeTruthy()
  })

  it('旧快照（无 forensic、无 partial）→ 小节、chip、横幅三样都不出现，也不出现「0 轮」', () => {
    const rep = reportWith((lc) => lc)
    render(
      <MemoryRouter>
        <LifeCircleReportView report={rep} />
      </MemoryRouter>,
    )
    expect(screen.queryByText('取证回合')).toBeNull()
    expect(screen.queryByText(/取证 0 轮/)).toBeNull()
    expect(screen.queryByText(/证据域 \d+ 盘/)).toBeNull()
    expect(screen.queryByText(/扩容回合没把可达区铺完/)).toBeNull()
  })
})

describe('片 5-5 · round 事件只喂回合回调，不动进度', () => {
  const row = round(0, true)

  it('round → onRound(row, text)，且 onProgress 一次都不被叫（stage/percent 不变）', () => {
    const onRound = vi.fn()
    const onProgress = vi.fn()
    flowTest.onFlowEvent('round', { stage: 'collect', text: '取证回合：在 25 个补算锚点上重查三要素', round: row }, { onRound, onProgress })
    expect(onRound).toHaveBeenCalledTimes(1)
    expect(onRound.mock.calls[0][0]).toBe(row)
    expect(onRound.mock.calls[0][1]).toContain('取证回合')
    expect(onProgress).not.toHaveBeenCalled()
  })

  it('载荷缺 round → 不调用也不抛（后端只在真派发时发这一条）', () => {
    const onRound = vi.fn()
    expect(() => flowTest.onFlowEvent('round', { stage: 'collect', text: 'x' }, { onRound })).not.toThrow()
    expect(onRound).not.toHaveBeenCalled()
  })
})

/* ── 批 B 真打接口读数带出的两档句子 ───────────────────────────────────── */

/** 两城实测产物里**照抄**的形状（`skip/tmp/out/lc_p5_live_*.json`，走生产 pipeline 落库后回读）。
 *  桩夹具给不出这些：它的 34 盘全是 `exhausted < request`，所以"合成盘"那一档在桩数据上不存在 ——
 *  我上一轮正是拿"夹具里这种盘数=0"去驳回评审，驳回错了（夹具≠生产）。 */
const KAILI_SYNTH_DISC: EvidenceDisc = {
  category: 'market', anchor: [107.9758, 26.5734], request_radius_m: 2367.2,
  exhausted_radius_m: 2367.2, complete: false, cap_hit: false, stop_reason: null,
}
const KAILI_SHORT_DISC: EvidenceDisc = {
  ...KAILI_SYNTH_DISC, category: 'pharmacy', exhausted_radius_m: 1745.6,
}
const BEIJING_CAPPED_DISC: EvidenceDisc = {
  ...KAILI_SYNTH_DISC, category: 'pharmacy', anchor: [107.965991, 26.5734], exhausted_radius_m: 1594.6,
  stop_reason: 'page_cap',
}

describe('批 B 真读数 · 盘句子分三档：查全 / 未查全（有原因）/ 合成盘未逐锚点记录', () => {
  it('合成盘（实测==请求、无原因、complete=false）不再被说成「未查全」', () => {
    expect(isSyntheticDisc(KAILI_SYNTH_DISC)).toBe(true)
    const t = evidenceDiscTitle(KAILI_SYNTH_DISC)
    expect(t).toContain('未逐锚点记录')
    expect(t).not.toContain('未查全') // 同屏「实测 2367 / 请求 2367」+「未查全」= 自相矛盾
    expect(t).not.toContain('查全（') // 也不许滑到"自称查全"那一侧
  })

  it('正向对照：同一锚点上实测半径更短的盘照旧说「未查全」，带原因的照旧带原因', () => {
    expect(isSyntheticDisc(KAILI_SHORT_DISC)).toBe(false)
    expect(evidenceDiscTitle(KAILI_SHORT_DISC)).toContain('未查全')
    expect(isSyntheticDisc(BEIJING_CAPPED_DISC)).toBe(false)
    expect(evidenceDiscTitle(BEIJING_CAPPED_DISC)).toContain('page_cap')
  })
})

describe('批 B 真读数 · 未派发行按真原因分档，不把"没点可打"演成"钱不够"', () => {
  it('北京那行（计划 0 / 发 0 / 砍 0，收手 nothing_to_ask）念「没排出新锚点」', () => {
    expect(roundAnchorCell(round(1, false, { anchors_planned: 0, anchors_sent: 0 }))).toBe('没排出新锚点')
  })

  it('凯里那行（计划 17 / 发 3 / 砍 14，收手 rounds_exhausted）照念三个数', () => {
    expect(roundAnchorCell(round(1, false))).toBe('需求 17 · 额度容 3 · 一个没打')
  })

  it('派发趟仍走「计划→发→用」，两档不互相串', () => {
    expect(roundAnchorCell(round(0, true))).toBe('42→25→25')
  })
})

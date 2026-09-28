/**
 * F1 · 契约完整性校验：fixture 数据必须满足 F0 冻结的 LivingCircleReport 契约。
 * 守护规则：字段齐全 / 等时圈族分钟集 = {5,10,15,20} / 多边形闭合 / 盲区三要素口径 / 评分范围。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import eventFlow from '../mocks/livingCircle/eventFlow.json'
import type { LivingCircleReport, LngLat, SSEEventType } from '../types'
import {
  getLivingCircleReportMock,
  getLifeCircleRecords,
  LC_REPORT_ID,
} from '../mocks/livingCircleReports'
import { replayLivingCircleStream, LC_STAGES } from '../mocks/livingCircleStream'
import { dataOriginBadge, heatSamplePoints, isInReachPoint, isTimedPoint, LC_CANVAS, LC_ISO_COLORS, lcCoLocated, lcLocPrefix, lcMeters, lcPolyPts, lcSceneDistanceM, lcSnapshotPoiLayer, lcToPx, LC_CO_LOCATED_M, LC_REACH_FULL_MIN_FALLBACK, planComparisonOverlay, poiConservation, poiConservationNote, poiMetricLabel, poiRenderSet, POI_THIN_THRESHOLD, policyVersionOf, samplingReach, samplingReachLabel, SCOPE_POLICY_VERSION, staleCaliberNotice } from '../lib/livingCircle'
import { BD_LAT_ABS_MAX, BD_LNG_ABS_MAX, parseBdLngLat } from '../lib/geo'

const reports = [kaili as unknown as LivingCircleReport, jinsong as unknown as LivingCircleReport]

/** 经度增量（dLng °）折算为地面距离的米数（取其近似，仅用于测试判定）。 */
const lngM = (dLng: number, lat = 26.25) => Math.abs(dLng) * 111320 * Math.cos((lat * Math.PI) / 180)

/** 经度偏移辅助（自定基准点向东推进 dLng°）。 */
const east = (lng: number, d: number) => [lng + d, 26.25] as LngLat

const CLOSED_PAIR_OK = (ring: [number, number][]) =>
  Array.isArray(ring) && ring.length >= 5 && ring[0]?.[0] === ring[ring.length - 1]?.[0] && ring[0]?.[1] === ring[ring.length - 1]?.[1]

/** 可达区环（按 caliber.reach_full_min 取，不是按位置取末位）。 */
function reachRing(r: LivingCircleReport): [number, number][] {
  const target = r.caliber?.reach_full_min ?? 20
  const zone = r.isochrones.find((z) => z.minutes === target)
  expect(zone, `等时圈族里找不到 minutes==${target} 的可达区环`).toBeTruthy()
  return zone!.geojson.coordinates[0] as [number, number][]
}

/** 某点距报告中心的地面距离（米）。 */
function distM(r: LivingCircleReport, p: [number, number]): number {
  const [mx, my] = lcMeters(r.scene.center, p[0], p[1])
  return Math.hypot(mx, my)
}

describe('LivingCircleReport fixture 契约', () => {
  it('顶层字段齐全且 data_origin/interpolation 正确', () => {
    for (const r of reports) {
      // M5：fixture 为真实百度实跑快照（live / IDW 插值）
      expect(r.data_origin).toBe('live')
      expect(r.sampling.interpolation).toBe('idw')
      for (const k of ['scene', 'generated_at', 'isochrones', 'sampling', 'poi', 'blindspots', 'scores'] as const) {
        expect(r).toHaveProperty(k)
      }
    }
  })

  it('scene 中心点/研究半径合法，且坐标满足 BD-09 值域', () => {
    for (const r of reports) {
      expect(r.scene.center).toHaveLength(2)
      expect(r.scene.center.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true)
      // 旧防线是「长度 2 + isFinite」——它**逐条放行**墨卡托米坐标（11440230.81 也是有限数）。
      // 值域才是唯一能区分坐标系的判据：拖拽事件把墨卡托米当经纬度写进报告时，只有这里会红。
      const [lng, lat] = r.scene.center
      expect(Math.abs(lng)).toBeLessThanOrEqual(BD_LNG_ABS_MAX)
      expect(Math.abs(lat)).toBeLessThanOrEqual(BD_LAT_ABS_MAX)
      expect(parseBdLngLat(r.scene.center)).not.toBeNull()
      expect(r.scene.study_radius_m).toBeGreaterThan(1000)
    }
  })

  it('空间口径举证：采集区 ⊇ 可达区，且判盲覆盖度可复核（Q1/Q2 的可判据化）', () => {
    for (const r of reports) {
      const cal = r.caliber
      expect(cal, '报告缺少 caliber 举证对象').toBeTruthy()
      for (const k of [
        'reach_full_min',
        'reach_radius_bound_m',
        'reach_circumradius_m',
        'collect_radius_m',
        'collect_margin_m',
        'cells_inside',
        'cells_judged',
        'cells_unknown',
      ] as const) {
        expect(typeof cal![k], `caliber.${k} 缺失（无可观测性出口 ⇒ 采集半径算错也看不出来）`).toBe('number')
      }
      // 可达区 ⊆ 采集区（否则可达区内必然存在无数据格，「没查到」会被当成「没有」）
      expect(cal!.collect_radius_m!).toBeGreaterThanOrEqual(cal!.reach_circumradius_m! * 0.999)
      // 采集半径 = 外接圆 + 余量
      expect(cal!.collect_radius_m!).toBeCloseTo(cal!.reach_circumradius_m! + cal!.collect_margin_m!, 3)
      // 判盲格数分账必须闭合（可判定 + 不可判定 = 可达区内总格数）
      expect(cal!.cells_judged! + cal!.cells_unknown!).toBe(cal!.cells_inside!)
      // 实测外接圆不应小于理论下界（更小 ⇒ 测时或圈层提取出了问题）
      expect(cal!.reach_circumradius_m!).toBeGreaterThanOrEqual(cal!.reach_radius_bound_m! * 0.9)
    }
  })

  // rev2 · 证据相（「实际查到哪儿」）—— 与后端 `report_contract` 的 B5/B10 同一套关系，
  // 两端各锁一次。判据写成**条件式**而不是「夹具必须有这六个键」：内置快照冻结在口径升级
  // 之前，硬要求 Presence 会让整组用例在重刷夹具（要花配额）之前恒红，等于没有护栏。
  it('证据相键：缺键只允许是「升级前的旧快照」，且必须被陈旧提示覆盖', () => {
    for (const r of reports) {
      const cal = r.caliber!
      const v = policyVersionOf(r)
      if (v === null) {
        // 旧口径快照 ⇒ 后端不会拿它冒充新答案（reuse_policy 拦复用），
        // 而前端必须**说出来** —— 不说就是继续按「没有盲区」卖一遍。
        expect(staleCaliberNotice(r), `${r.scene.name}：旧口径快照必须给陈旧提示`).toBeTruthy()
        // 旧快照的 D2 形状（余量 0）正是本次缺陷的制度化载体：采集半径 == 外接圆
        expect(cal.collect_margin_m).toBe(0)
        expect(cal.cells_unknown!).toBeGreaterThan(0)
        continue
      }
      // 声明了版本 ⇒ 整套证据键必须齐（版本号与键集是同一次发布的两半）
      expect(v).toBe(SCOPE_POLICY_VERSION)
      expect(staleCaliberNotice(r)).toBeNull()
      for (const k of [
        'evidence_margin_m',
        'evidence_frontier_m',
        'evidence_complete',
        'evidence_bound_source',
        'judge_radius_m',
      ] as const) {
        expect(cal![k], `caliber.${k} 缺失（声明了版本却不举证）`).toBeDefined()
      }
      // B5 的关系必须在客户端也复算得动（否则 UI 无法回答「这次实际查到哪儿」）
      expect(cal.collect_radius_m).toBeCloseTo(cal.reach_circumradius_m! + cal.evidence_margin_m!, 1)
      expect(cal.evidence_margin_m).toBeGreaterThan(0)
      const bound = cal.evidence_bound_source === 'measured' ? cal.evidence_radius_m! : cal.collect_radius_m!
      expect(cal.judge_radius_m).toBeCloseTo(Math.max(0, bound - 1000), 1)
      // B10 的分账：一格未判 ⇒ 全部都得记未定
      if (cal.cells_judged === 0) expect(cal.cells_unknown).toBe(cal.cells_inside)
    }

    // ⚠️ 上面那支在两份内置快照上都只走 `v === null` 分支 ⇒ 新口径那半今天是**空转**的。
    // 这里用「夹具 + 人工升格」把新分支真跑一遍，等将来重刷夹具后它自动变成真实路径。
    const K = kaili as unknown as LivingCircleReport
    // 夹具前提：即便是旧口径快照也必须带 caliber（举证对象本身不缺）。缺了说明夹具被
    // 改动过 —— 当场说清楚，别让下面整支在 undefined 上算出个看起来合理的数。
    if (!K.caliber) throw new Error('夹具前提不成立：kaili.json 没有 caliber')
    const OLD_CAL = K.caliber
    const OLD_COLLECT = OLD_CAL.collect_radius_m! // 旧口径：余量 0 ⇒ 就等于外接圆
    const upgraded = (over: Record<string, unknown> = {}) =>
      ({
        ...kaili,
        caliber: {
          ...OLD_CAL,
          scope_policy_version: SCOPE_POLICY_VERSION,
          collect_radius_m: OLD_COLLECT + 1000, // = 外接圆 + 证据余量
          evidence_margin_m: 1000,
          evidence_radius_m: OLD_COLLECT + 1000,
          evidence_frontier_m: { market: 2367, pharmacy: 1800, primary: 2367 },
          evidence_complete: false,
          evidence_bound_source: 'measured',
          judge_radius_m: OLD_COLLECT, // = 实测边界 2367 − 判定半径 1000
          ...over,
        },
      }) as unknown as LivingCircleReport

    const up = upgraded()
    expect(policyVersionOf(up)).toBe(SCOPE_POLICY_VERSION)
    expect(staleCaliberNotice(up)).toBeNull()
    // 复算必须真算得动（不是「键在就行」）：collect = 外接圆 + 余量、judge = 实测边界 − 1km
    expect(up.caliber!.collect_radius_m).toBeCloseTo(up.caliber!.reach_circumradius_m! + 1000, 1)
    expect(up.caliber!.judge_radius_m).toBeCloseTo(Math.max(0, up.caliber!.evidence_radius_m! - 1000), 1)
    // 反证：把余量改回 0（D2 回退）⇒ 上面那条关系必断，本用例的判据有牙
    const regressed = upgraded({ collect_radius_m: up.caliber!.reach_circumradius_m })
    expect(regressed.caliber!.collect_radius_m).not.toBeCloseTo(
      regressed.caliber!.reach_circumradius_m! + regressed.caliber!.evidence_margin_m!,
      1,
    )
    // 版本号写错（如后端升到 ev-2 而前端常量没跟着改）⇒ 陈旧提示必须说话
    expect(staleCaliberNotice(upgraded({ scope_policy_version: 'ev-2' }))).toContain('ev-2')
  })

  it('等时圈族必须覆盖 5/10/15/20 分钟且多边形闭合、面积为正', () => {
    for (const r of reports) {
      const mins = r.isochrones.map((z) => z.minutes).sort((a, b) => a - b)
      expect(mins).toEqual([5, 10, 15, 20])
      for (const z of r.isochrones) {
        expect(z.geojson.type).toBe('Polygon')
        expect(CLOSED_PAIR_OK(z.geojson.coordinates[0])).toBe(true)
        expect(z.area_km2).toBeGreaterThan(0)
        // 时间越长圈越大（单调性）
      }
      for (let i = 1; i < r.isochrones.length; i++) {
        expect(r.isochrones[i].area_km2).toBeGreaterThan(r.isochrones[i - 1].area_km2)
      }
    }
  })

  // ── 阶段 −1（T-FE-02）：本用例原为「reachable ⇔ minutes 非空」──────────────
  // 那条断言**把错误语义固化成了契约**：`reachable` 的语义其实是「测时返回了值」，
  // 却被 UI 读成「可达」，于是「采样点 1049 个（可达 1049）」上了屏，而真正
  // ≤reach_full_min 的只有 126 个。字段已拆为 `timed`（测时返回了值）+ `in_reach`
  //（且不超过阈值），因此这里改为断言**两个字段各自的语义与二者关系**，
  // 并显式禁止旧名回流（旧名若被 `.get()` 读走会静默变 0，比报错更危险）。
  it('采样点分档自洽（timed ⇔ minutes 非空；in_reach ⇒ timed 且 ≤reach_full_min）', () => {
    for (const r of reports) {
      const threshold = r.caliber?.reach_full_min ?? 20
      expect(r.sampling.points.length).toBeGreaterThan(0)
      for (const p of r.sampling.points) {
        expect(typeof p.lng).toBe('number')
        expect(typeof p.lat).toBe('number')
        expect(p.timed).toBe(p.minutes !== null)
        expect(typeof p.in_reach).toBe('boolean')
        if (p.timed) {
          expect(typeof p.minutes).toBe('number')
          expect(p.minutes!).toBeGreaterThanOrEqual(0)
        }
        // 可达 ⇒ 必然已测时，且不超过可达区口径（分钟本身无 ≤20 上限，2.5km 研究域可到 75min）
        if (p.in_reach) {
          expect(p.timed).toBe(true)
          expect(p.minutes!).toBeLessThanOrEqual(threshold)
        }
        expect('reachable' in p).toBe(false)
      }
    }
  })

  it('采样分档汇总数与逐点一致，且 timed ≠ in_reach（T-FE-02 配偶断言）', () => {
    for (const r of reports) {
      const s = r.sampling
      const timed = s.points.filter((p) => p.timed).length
      const inReach = s.points.filter((p) => p.in_reach).length
      expect(s.timed_count).toBe(timed)
      expect(s.in_reach_count).toBe(inReach)
      // 两者相等意味着 in_reach 退化成了「测时返回了值」——正是本阶段修掉的旧 bug
      expect(s.in_reach_count!).toBeLessThan(s.timed_count!)
    }
  })

/**
 * T-FE-02b · **历史快照读侧兼容**（阶段 −1 迁移的另一半）。
 *
 * 库里 25 份报告的采样点全部只有旧名 `reachable`（实测 1049/1049），没有 `timed`/`in_reach`，
 * 也没有汇总数。若读侧只认新字段，历史报告的热力层会被**静默清空**、可达数会显示 0 ——
 * 又一个「看着是 0，其实是字段没读到」。因此本组用例同时钉住两件事：
 *   ① 回退判定必须生效（守住真实用户可见的历史报告）；
 *   ② **朴素读法确实会归零**（负对照：证明这条守卫不是装饰，一旦有人「简化」回
 *      `p.timed` 就必须红）。
 */
describe('T-FE-02b · 历史快照（无 timed / 无汇总数）读侧兼容', () => {
  /** 造一份阶段 −1 之前形态的报告：点只有 `reachable`，sampling 无汇总数。 */
  function legacyReport(): LivingCircleReport {
    const mk = (idx: number, minutes: number | null) => ({
      idx,
      lng: 107.95 + idx * 0.001,
      lat: 26.57,
      minutes,
      reachable: minutes != null, // 旧名：语义 =「测时返回了值」
    })
    return {
      scene: { name: '凯里老街', city: '凯里市', address: '老街', center: [107.95, 26.57], study_radius_m: 2500 },
      generated_at: '2026-09-19T00:00:00.000Z',
      data_origin: 'live',
      caliber: { reach_full_min: 20 },
      isochrones: [
        { minutes: 5, area_km2: 0.1, geojson: { type: 'Polygon', coordinates: [[[107.94, 26.56], [107.96, 26.56], [107.96, 26.58], [107.94, 26.58], [107.94, 26.56]]] } },
        { minutes: 10, area_km2: 0.4, geojson: { type: 'Polygon', coordinates: [[[107.93, 26.55], [107.97, 26.55], [107.97, 26.59], [107.93, 26.59], [107.93, 26.55]]] } },
        { minutes: 15, area_km2: 0.9, geojson: { type: 'Polygon', coordinates: [[[107.92, 26.54], [107.98, 26.54], [107.98, 26.6], [107.92, 26.6], [107.92, 26.54]]] } },
        { minutes: 20, area_km2: 1.5, geojson: { type: 'Polygon', coordinates: [[[107.91, 26.53], [107.99, 26.53], [107.99, 26.61], [107.91, 26.61], [107.91, 26.53]]] } },
      ],
      // ⚠️ 故意不写 timed_count / in_reach_count，也不写 timed / in_reach
      sampling: {
        points: [mk(0, 3.2), mk(1, 12.5), mk(2, 20), mk(3, 20.1), mk(4, 45.7), mk(5, null)],
        interpolation: 'idw',
        is_scattered: true,
      },
      poi: { categories: [], total: 0, in_circle: 0, points: [] },
      blindspots: [],
      scores: { total: 60, radar: [], bars: [], triads: [], note: '' },
    } as unknown as LivingCircleReport
  }

  it('汇总数缺失时按点回算：timed=5 / inReach=3（不是 0）', () => {
    const r = legacyReport()
    const reach = samplingReach(r)
    expect(reach.total).toBe(6)
    expect(reach.timed).toBe(5) // 5 个 minutes 非空
    expect(reach.inReach).toBe(3) // 3.2 / 12.5 / 20.0 ≤ 20
    expect(reach.reachFullMin).toBe(20)
    // 文案层同源：不能出现「可达 0」
    const label = samplingReachLabel(r)
    expect(label).toContain('可达 3')
    expect(label).not.toContain('可达 0')
  })

  it('负对照：朴素读 `p.timed` 对历史快照必然归零（守卫不是装饰）', () => {
    const r = legacyReport()
    const naive = r.sampling.points.filter((p) => (p as { timed?: boolean }).timed).length
    expect(naive).toBe(0) // ← 直接读新字段 = 全丢
    expect(heatSamplePoints(r).length).toBe(5) // ← 走单一入口 = 保住
  })

  it('heatSamplePoints：取「已测时」而非「仅可达」，且 cap 截断不改顺序', () => {
    const r = legacyReport()
    const all = heatSamplePoints(r)
    expect(all.map((p) => p.idx)).toEqual([0, 1, 2, 3, 4]) // idx=5 的 minutes=null 被剔除
    expect(all.every((p) => typeof p.minutes === 'number')).toBe(true)
    expect(heatSamplePoints(r, 2).map((p) => p.idx)).toEqual([0, 1])
    // 只画可达点会让高耗时区凭空消失（正片 45.7min 是最该被看见的地方）
    expect(all.some((p) => p.minutes > 20)).toBe(true)
  })

  it('isTimedPoint / isInReachPoint：显式 false 优先于 minutes，阈值含边界且带一位舍入', () => {
    // 显式 false 必须压过 minutes 非空（`??` 而非 `||`，否则「已测时但明确排除」的点会被翻回来）
    expect(isTimedPoint({ minutes: 5, timed: false })).toBe(false)
    expect(isTimedPoint({ minutes: 5 })).toBe(true)
    expect(isTimedPoint({ minutes: null })).toBe(false)
    expect(isTimedPoint({ minutes: null, timed: true })).toBe(true)

    expect(isInReachPoint({ minutes: 20 }, 20)).toBe(true) // 边界含
    expect(isInReachPoint({ minutes: 20.1 }, 20)).toBe(false) // 边界外
    expect(isInReachPoint({ minutes: 20.0000001 }, 20)).toBe(true) // 浮点噪声：与后端 round(_,1) 同口径
    expect(isInReachPoint({ minutes: null }, 20)).toBe(false)
    // 阈值缺省取兜底 20（老快照没有 caliber.reach_full_min 时）
    expect(LC_REACH_FULL_MIN_FALLBACK).toBe(20)
    expect(isInReachPoint({ minutes: 20 })).toBe(true)
    // 后端已下发的 in_reach 具备权威性（不再本地重算，避免两处判据漂移）
    expect(isInReachPoint({ minutes: 25, in_reach: true }, 20)).toBe(true)
  })

  it('夹具（新口径）与历史快照（旧口径）走同一入口，结果口径一致', () => {
    for (const r of reports) {
      const reach = samplingReach(r)
      expect(reach.timed).toBe(r.sampling.timed_count) // 汇总数权威
      expect(heatSamplePoints(r).length).toBe(reach.timed) // 热力点数 = 已测时数
      expect(reach.inReach).toBeLessThan(reach.timed)
    }
  })
})

  it('poi.points 点位契约（M5.1 增量字段）', () => {
    // points 允许为空（权威快照未采集/配额受限时优雅降级），非空时逐字段校验
    for (const r of reports) {
      expect(Array.isArray(r.poi.points)).toBe(true)
      for (const p of r.poi.points) {
        expect(p.id.startsWith('poi-')).toBe(true)
        expect(typeof p.name).toBe('string')
        expect(typeof p.category).toBe('string')
        expect(p.lnglat).toHaveLength(2)
        expect(p.lnglat.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true)
        expect(p.minutes === null || typeof p.minutes === 'number').toBe(true)
        expect(typeof p.in_circle).toBe('boolean')
      }
    }
  })

  it('poi.points 全部落在可达区内（Q2：圈外点不进报告、不给前端）', () => {
    for (const r of reports) {
      const cr = Math.max(...reachRing(r).map((p) => distM(r, p)))
      for (const p of r.poi.points) {
        expect(p.in_circle).toBe(true)
        expect(distM(r, p.lnglat as [number, number])).toBeLessThanOrEqual(cr * 1.02)
      }
    }
  })

  it('POI 类别统计自洽（in_circle ≤ total，coverage ∈ [0,1]）', () => {
    for (const r of reports) {
      expect(r.poi.categories.length).toBeGreaterThanOrEqual(7)
      for (const c of r.poi.categories) {
        expect(c.in_circle).toBeLessThanOrEqual(c.total)
        expect(c.coverage).toBeGreaterThanOrEqual(0)
        expect(c.coverage).toBeLessThanOrEqual(1)
      }
      expect(r.poi.total).toBeGreaterThanOrEqual(r.poi.in_circle)
    }
  })

  // ── 阶段 1 · 点数守恒（本计划的核心不变量）────────────────────────
  // 旧防线只断言 `total >= in_circle`，**不约束 points** ⇒ fixture 里
  // 「面板写圈内 104 处 / 图上只有 98 个点」照样全绿（实测 6 条差额无人发现）。

  it('POI 点数守恒：sum(categories[].in_circle) === points.length', () => {
    for (const r of reports) {
      const c = poiConservation(r)
      expect(c.declared).toBe(c.actual)
      expect(c.delta).toBe(0)
      expect(c.ok).toBe(true)
      // 新口径夹具必须自带后端下发的自检结论（缺它 ⇒ 本条退化成「按点回算」的弱判据）
      expect(r.poi.conservation?.ok).toBe(true)
      expect(r.poi.conservation?.declared_in_circle).toBe(r.poi.points.length)
      expect(r.poi.truncated?.dropped).toBe(0)
      expect(r.poi.truncated?.cap_per_cat).toBe(200)
    }
  })

  it('负对照：shopping.in_circle 改回 31（旧截断前的数）→ 守恒判据必须变红', () => {
    // 这正是 fixture 当初的形态（104 vs 98）；护栏不会响 = 没有护栏。
    const r = kaili as unknown as LivingCircleReport
    const broken = {
      ...r,
      poi: {
        ...r.poi,
        categories: r.poi.categories.map((c) =>
          c.category === 'shopping' ? { ...c, in_circle: 31 } : c,
        ),
      },
    } as LivingCircleReport
    const c = poiConservation(broken)
    expect(c.ok).toBe(false)
    expect(c.declared).toBe(104)
    expect(c.actual).toBe(98)
    expect(c.delta).toBe(-6)
  })

  it('历史报告（无 poi.conservation）按点集回算 —— 两个方向都必须判为不守恒', () => {
    // 实测库里 25 份报告有 15 份不守恒，且**方向相反**：
    //   ① 截断方向（旧 cap=25）：in_circle 104 / points 98；
    //   ② 旧版「圈外点全送」方向：in_circle 18 / points 151。
    // 方向相反 ⇒ **不可统一反算修正**，只能如实披露（`poiConservationNote`）。
    const truncated = {
      poi: {
        categories: [{ category: 'shopping', in_circle: 31 }],
        total: 76,
        in_circle: 104,
        points: Array.from({ length: 25 }, () => ({ category: 'shopping' })),
      },
    } as unknown as LivingCircleReport
    const a = poiConservation(truncated)
    expect(a.source).toBe('derived')
    expect(a).toMatchObject({ declared: 31, actual: 25, delta: -6, ok: false })
    expect(poiConservationNote(truncated)).toContain('少 6 处')

    const oversent = {
      poi: {
        categories: [{ category: 'medical', in_circle: 18 }],
        total: 258,
        in_circle: 18,
        points: Array.from({ length: 151 }, () => ({ category: 'medical' })),
      },
    } as unknown as LivingCircleReport
    const b = poiConservation(oversent)
    expect(b).toMatchObject({ declared: 18, actual: 151, delta: 133, ok: false })
    expect(poiConservationNote(oversent)).toContain('旧版口径')
  })

  it('离线报告（categories 为空）不误报不守恒', () => {
    const offline = {
      poi: { categories: [], total: 0, in_circle: 0, points: [] },
    } as unknown as LivingCircleReport
    expect(poiConservation(offline)).toMatchObject({ declared: 0, actual: 0, ok: true })
    expect(poiConservationNote(offline)).toBeNull()
  })

  it('盲区口径：1km 半径、缺失∈三要素、多边形闭合；且盲区必须落在可达区内', () => {
    for (const r of reports) {
      for (const b of r.blindspots) {
        expect(b.radius_m).toBe(1000)
        expect(b.missing_facilities.length).toBeGreaterThan(0)
        for (const m of b.missing_facilities) {
          expect(['菜市场', '药店', '小学']).toContain(m)
        }
        expect(b.center).toHaveLength(2)
        expect(CLOSED_PAIR_OK(b.polygon.coordinates[0])).toBe(true)

        // 盲区中心与每个顶点都必须落在**可达区外接圆**内（Q1 判据）。
        // 旧断言是「凯里盲区数 > 劲松盲区数」——那只是旧实现把整张判定网格连成一片灰框
        // （29km²）后的产物，不是契约；修好判盲范围后凯里 0 处、劲松 1 处，该断言自然失效。
        const cr = Math.max(...reachRing(r).map((p) => distM(r, p)))
        const ring = b.polygon.coordinates[0] as [number, number][]
        for (const p of ring) expect(distM(r, p)).toBeLessThanOrEqual(cr * 1.02)
        expect(distM(r, b.center as [number, number])).toBeLessThanOrEqual(cr * 1.02)
      }
    }
  })

  it('评分自洽：0-100、三要素 3 条、雷达 ≥5 维', () => {
    for (const r of reports) {
      expect(r.scores.total).toBeGreaterThanOrEqual(0)
      expect(r.scores.total).toBeLessThanOrEqual(100)
      expect(r.scores.triads).toHaveLength(3)
      expect(r.scores.radar.length).toBeGreaterThanOrEqual(5)
      for (const t of r.scores.triads) {
        if (t.covered) {
          expect(t.nearest_minutes).not.toBeNull()
          expect(typeof t.nearest_name).toBe('string')
        }
      }
    }
  })
})

const FLOW_TYPES: SSEEventType[] = ['node_update', 'progress', 'message', 'evidence', 'report_ready', 'done']

describe('A4 · eventFlow.json SSE 事件契约', () => {
  it('事件类型全部合法（对齐 SSEEventType 白名单）', () => {
    const flow = eventFlow as unknown as { events: { type: SSEEventType }[] }
    expect(flow.events.length).toBeGreaterThan(20)
    for (const ev of flow.events) {
      expect(FLOW_TYPES).toContain(ev.type)
    }
  })

  it('stage 序列 = intake→plan→measure→collect→diagnose→report→audit 且进度单调', () => {
    const flow = eventFlow as unknown as { stages: string[]; events: { type: string; data: { stage?: string; percent?: number; stage_seq?: number } }[] }
    expect(flow.stages).toEqual(LC_STAGES)
    const progress = flow.events.filter((e) => e.type === 'progress' && e.data.stage)
    const seen: string[] = []
    let prevPercent = -1
    for (const p of progress) {
      seen.push(p.data.stage!)
      expect(p.data.percent!).toBeGreaterThanOrEqual(prevPercent)
      prevPercent = p.data.percent!
    }
    // 出现顺序与 stage 定义一致（允许同一 stage 多条，不允许乱序/缺段）
    const stageIdx = flow.stages
    expect(seen.every((s, i) => i === 0 || stageIdx.indexOf(s) >= stageIdx.indexOf(seen[i - 1]))).toBe(true)
    for (const s of flow.stages) {
      expect(seen).toContain(s)
    }
    // 收尾：最后一条 progress ≈100
    expect(progress.at(-1)?.data.percent).toBeGreaterThanOrEqual(90)
  })

  it('事件载荷必填字段齐全', () => {
    const flow = eventFlow as unknown as {
      events: {
        type: string
        data: {
          stage?: string
          percent?: number
          stage_seq?: number
          node?: { id: string; label: string; status: string }
          text?: string
          evidence?: { evidence_id: string; title: string; credibility: number; collected_by: string }
          report_id?: string
        }
      }[]
    }
    for (const ev of flow.events) {
      const d = ev.data
      switch (ev.type) {
        case 'node_update':
          expect(d.node?.id).toBeTruthy()
          expect(d.node?.label).toBeTruthy()
          expect(['idle', 'working', 'done', 'rework']).toContain(d.node?.status)
          break
        case 'progress':
          expect(typeof d.percent).toBe('number')
          expect(d.stage).toBeTruthy()
          expect(typeof d.stage_seq).toBe('number')
          break
        case 'message':
          expect(d.text).toBeTruthy()
          break
        case 'evidence':
          expect(d.evidence?.evidence_id).toBeTruthy()
          expect(d.evidence?.title).toBeTruthy()
          expect(d.evidence!.credibility).toBeGreaterThan(0)
          expect(d.evidence!.credibility).toBeLessThanOrEqual(1)
          expect(d.evidence?.collected_by).toBeTruthy()
          break
        case 'report_ready':
        case 'done':
          expect(typeof d.report_id).toBe('string')
          break
      }
    }
  })

  it('report_ready 产出的报告可被 mock 加载（防 M3 联调断链）', () => {
    const flow = eventFlow as unknown as { events: { type: string; data: { report_id?: string } }[] }
    const ready = flow.events.find((e) => e.type === 'report_ready')
    expect(ready?.data.report_id).toBeTruthy()
    expect(getLivingCircleReportMock(ready!.data.report_id!)).not.toBeNull()
  })

  it('回放器按序派发全部事件，并可用 reportId 覆写报告目标', () => {
    vi.useFakeTimers()
    const flow = eventFlow as unknown as { events: { type: string }[] }
    const received: string[] = []
    let doneId = ''
    const close = replayLivingCircleStream(
      'lc-demo',
      { onEvent: (type) => received.push(type) },
      { reportId: 'lc-beijing-jinsong', speed: 10, onDone: (rid) => (doneId = rid) },
    )
    vi.advanceTimersByTime(flow.events.length * 10 + 20)
    expect(received).toEqual(flow.events.map((e) => e.type))
    expect(doneId).toBe('lc-beijing-jinsong')
    // close 后再 advance 不再派发（防泄漏）
    close()
    const len = received.length
    vi.advanceTimersByTime(1000)
    expect(received.length).toBe(len)
  })
})

afterEach(() => {
  vi.useRealTimers()
})

/* ── F1/F2 · data_origin 四态徽标 + 离线报告契约（P0-1 迁移守护） ── */

/** 镜像 OfflineDataSource 产出的离线报告结构（契约测试用，不落 fixture） */
function offlineReport(): LivingCircleReport {
  return {
    scene: { name: '上海市浦东新区陆家嘴', city: '上海市', address: '离线估算（区县中心近似）', center: [121.505252, 31.23333], study_radius_m: 2500 },
    generated_at: '2026-09-19T00:00:00.000Z',
    data_origin: 'offline',
    isochrones: [
      { minutes: 5, area_km2: 0.12, geojson: { type: 'Polygon', coordinates: [[[121.5, 31.23], [121.52, 31.23], [121.52, 31.25], [121.5, 31.25], [121.5, 31.23]]] } },
      { minutes: 10, area_km2: 0.48, geojson: { type: 'Polygon', coordinates: [[[121.48, 31.21], [121.56, 31.21], [121.56, 31.27], [121.48, 31.27], [121.48, 31.21]]] } },
      { minutes: 15, area_km2: 1.08, geojson: { type: 'Polygon', coordinates: [[[121.45, 31.18], [121.6, 31.18], [121.6, 31.29], [121.45, 31.29], [121.45, 31.18]]] } },
      { minutes: 20, area_km2: 1.92, geojson: { type: 'Polygon', coordinates: [[[121.4, 31.15], [121.66, 31.15], [121.66, 31.32], [121.4, 31.32], [121.4, 31.15]]] } },
    ],
    sampling: { points: [], interpolation: 'circular_approx', is_scattered: false },
    poi: { categories: [], total: 0, in_circle: 0, points: [] },
    blindspots: [],
    scores: { total: 0, radar: [], bars: [], triads: [], note: '离线估算：步行速度 80 m/min × 绕行系数 1.3 的距离模型，未联网采集 POI——综合评分与服务盲区需实时体检后给出，且离线分不可与实时分比较' },
  }
}

describe('F1 · data_origin 四态徽标映射（P0-1 单一真相源）', () => {
  it('live → 真实数据（绿）', () => {
    const b = dataOriginBadge({ data_origin: 'live' })
    expect(b.label).toBe('真实数据')
    expect(b.tone).toBe('live')
  })

  it('served_from=cache（data_origin 保持 live）→ 历史实时 · 离线可查（蓝）', () => {
    const b = dataOriginBadge({ data_origin: 'live', served_from: 'cache' })
    expect(b.label).toBe('历史实时 · 离线可查')
    expect(b.tone).toBe('info')
  })

  it('U26：served_from=nearby_cache（邻近命中）→ 邻近历史实时（蓝，非"真实数据"）', () => {
    // 邻近缓存（原中心 ≤500m）同样是缓存复用、未消耗额度 —— 徽标必须为 info 基调
    // 而非默认 live 分支的「真实数据」，否则与横幅「未消耗百度额度」自相矛盾
    const b = dataOriginBadge({ data_origin: 'live', served_from: 'nearby_cache' })
    expect(b.label).toBe('邻近历史实时')
    expect(b.tone).toBe('info')
    expect(b.detail).toMatch(/未消耗百度额度/)
  })

  it('offline → 离线估算（黄），且与 cache 态不冲突', () => {
    const b = dataOriginBadge({ data_origin: 'offline' })
    expect(b.label).toBe('离线估算')
    expect(b.tone).toBe('warn')
    expect(b.detail).toMatch(/待实时体检/)
  })

  it('fixture_sample → 演示数据（黄）', () => {
    const b = dataOriginBadge({ data_origin: 'fixture_sample' })
    expect(b.label).toBe('演示数据')
    expect(b.tone).toBe('warn')
  })
})

describe('F2 · 离线报告契约（offline 结构 + served_from/cached_at 可选）', () => {
  it('offline 报告结构：data_origin=offline + 等时圈单调 + POI/盲区空 + 评分 note 说明不可比', () => {
    const r = offlineReport()
    expect(r.data_origin).toBe('offline')
    expect(r.sampling.interpolation).toBe('circular_approx')
    expect(r.isochrones.map((z) => z.minutes)).toEqual([5, 10, 15, 20])
    for (let i = 1; i < r.isochrones.length; i++) {
      expect(r.isochrones[i].area_km2).toBeGreaterThan(r.isochrones[i - 1].area_km2)
    }
    expect(r.poi.total).toBe(0)
    expect(r.poi.categories).toEqual([])
    expect(r.poi.points).toEqual([])
    expect(r.blindspots).toEqual([])
    expect(r.scores.total).toBe(0) // 保留结构但不渲染可比数字
    expect(r.scores.note).toMatch(/需实时体检/)
    expect(r.scores.note).toMatch(/不可与实时分比较/)
  })

  it('served_from/cached_at 为可选字段（旧 live 报告零影响）', () => {
    expect('served_from' in kaili).toBe(false)
    expect('cached_at' in kaili).toBe(false)
    const cached: LivingCircleReport = { ...offlineReport(), data_origin: 'live', served_from: 'cache', cached_at: '2026-09-18T00:00:00.000Z' }
    expect(cached.served_from).toBe('cache')
    expect(typeof cached.cached_at).toBe('string')
    // 缓存命中保持 data_origin=live（契约：缓存不改变数据口径）
    expect(cached.data_origin).toBe('live')
  })
})

describe('F3 · 完整体检 Report（living_circle 挂载 + 双层章节）', () => {
  it('id 与样区往返一致（lc-kaili / lc-beijing-jinsong）', () => {
    expect(LC_REPORT_ID('kaili')).toBe('lc-kaili')
    expect(LC_REPORT_ID('beijing-jinsong')).toBe('lc-beijing-jinsong')
    expect(getLivingCircleReportMock('lc-kaili')?.id).toBe('lc-kaili')
    expect(getLivingCircleReportMock('lc-beijing-jinsong')?.living_circle?.scene.name).toBe('北京劲松')
  })

  it('report_type=living_circle + living_circle 挂载（渲染适配器判据）', () => {
    const report = getLivingCircleReportMock('lc-kaili')
    expect(report?.report_type).toBe('living_circle')
    expect(report?.living_circle).toBeTruthy()
    expect(report?.living_circle?.scene.name).toBe('凯里老街')
  })

  it('章节齐全：概览/医疗/教育/菜市/养老/可达性/盲区/结论 ≥6 章，toc 与章节一致', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)
      expect(r!.sections.length).toBeGreaterThanOrEqual(6)
      for (const need of ['overview', 'medical', 'education', 'market', 'elderly', 'isochrone', 'blindspot', 'conclusion']) {
        expect(r!.sections.some((s) => s.id === need)).toBe(true)
      }
      expect(r!.toc.map((t) => t.id)).toEqual(r!.sections.map((s) => s.id))
      for (const sec of r!.sections) {
        expect(sec.title).toBeTruthy()
      }
    }
  })

  it('结论/证据/图表全链路闭环：claims.evidence_ids 均可解析', () => {
    const r = getLivingCircleReportMock('lc-kaili')!
    expect(r.claims.length).toBeGreaterThan(5)
    expect(r.evidence.length).toBeGreaterThan(5)
    expect(r.charts.length).toBeGreaterThanOrEqual(2)
    const evIds = new Set(r.evidence.map((e) => e.evidence_id))
    for (const c of r.claims) {
      for (const eid of c.evidence_ids) {
        expect(evIds.has(eid)).toBe(true)
      }
    }
    for (const sec of r.sections) {
      for (const c of sec.charts ?? []) {
        expect(c.option).toBeTruthy()
      }
    }
  })

  it('盲区章节 data_grid 与盲区数据一致（表格行数=盲区数）', () => {
    const r = getLivingCircleReportMock('lc-kaili')!
    const bs = r.sections.find((s) => s.id === 'blindspot')
    expect(bs?.data_grid?.rows.length).toBe(r.living_circle!.blindspots.length)
  })

  it('getLifeCircleRecordMock：未知 id / 非 lc 前缀 → null；历史别名可解析', () => {
    expect(getLivingCircleReportMock('lc-not-exist')).toBeNull()
    expect(getLivingCircleReportMock('r1')).toBeNull()
    expect(getLivingCircleReportMock('lc-kaili-r1')?.title).toContain('凯里老街')
  })

  it('getLifeCircleRecords：≥4 条、id 唯一、按时间倒序、评分 0-100 盲区 ≥0', () => {
    const records = getLifeCircleRecords()
    expect(records.length).toBeGreaterThanOrEqual(4)
    expect(new Set(records.map((r) => r.id)).size).toBe(records.length)
    for (let i = 1; i < records.length; i++) {
      expect(records[i - 1].checked_at >= records[i].checked_at).toBe(true)
    }
    for (const rec of records) {
      expect(rec.total_score).toBeGreaterThanOrEqual(0)
      expect(rec.total_score).toBeLessThanOrEqual(100)
      expect(rec.blindspot_count).toBeGreaterThanOrEqual(0)
      expect(rec.title).toBeTruthy()
    }
  })
})

/* ── F4 · 副标题口径与分隔符（与后端 assemble_report 同口径） ── */

describe('F4 · 报告副标题：设施数口径 + 地点前缀分隔符', () => {
  it('「共 N 处设施」数可达区内（poi.in_circle），不是采集总数（poi.total）', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)!
      const lc = r.living_circle!
      // 两个数必须不同，否则断言没有判别力（夹具退化时会静默通过）
      expect(lc.poi.in_circle).not.toBe(lc.poi.total)
      expect(r.subtitle).toContain(`共 ${lc.poi.in_circle} 处设施`)
      expect(r.subtitle).not.toContain(`共 ${lc.poi.total} 处设施`)
    }
  })

  it('lcLocPrefix：空片段不参与拼接，全空时整个前缀（含 ｜）省略', () => {
    expect(lcLocPrefix({ city: '昆明市', address: '西门街道' })).toBe('昆明市 · 西门街道｜')
    expect(lcLocPrefix({ city: '昆明市', address: '' })).toBe('昆明市｜')
    expect(lcLocPrefix({ city: '昆明市', address: null })).toBe('昆明市｜')
    expect(lcLocPrefix({ city: '', address: '西门街道' })).toBe('西门街道｜')
    expect(lcLocPrefix({ city: '', address: '' })).toBe('')
    expect(lcLocPrefix({})).toBe('')
    // 两侧都是空白字符也应视作空（防止「 · ｜」这类纯空白悬空分隔符）
    expect(lcLocPrefix({ city: '  ', address: '\t' })).toBe('')
  })

  it('mock 副标题不留悬空分隔符，且以地点前缀开头', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)!
      const lc = r.living_circle!
      expect(r.subtitle).not.toContain(' · ｜')
      expect(r.subtitle?.startsWith('｜')).toBe(false)
      expect(r.subtitle?.startsWith(`${lcLocPrefix(lc.scene)}综合 `)).toBe(true)
      // 整段版式（含分隔符前后的空格）必须与后端逐字同口径
      expect(r.subtitle).toMatch(
        /综合 [\d.]+ 分（[优中良差]）· \d+ 处服务盲区 · 共 \d+ 处设施（可达区内）$/,
      )
    }
  })
})

/* ── T5 · 画布口径与降级呈现护栏（I14/I5，多方式分档前置） ── */

describe('T5 · 降级画布 (LC_CANVAS) 与报告半径同源', () => {
  it('LC_CANVAS.R 必须等于报告 study_radius_m（半径一变，米→像素投影即失准）', () => {
    for (const r of reports) {
      expect(r.scene.study_radius_m).toBe(LC_CANVAS.R)
    }
    expect(offlineReport().scene.study_radius_m).toBe(LC_CANVAS.R)
  })

  it('等时圈配色表恰 4 档，且覆盖全部圈层（不足会渲染出 undefined 色）', () => {
    // 精确锁 4 档：原 `>=` 无法发现档数漂移 ⇒ `zi % length` 错档静默（档数与消费方必须同步改）
    expect(LC_ISO_COLORS.length, '色表档数变了 —— 检查 LcMap/报告快照的 `zi % length` 取色').toBe(4)
    for (const r of reports) {
      expect(r.isochrones.length).toBeGreaterThan(0)
      expect(LC_ISO_COLORS.length).toBeGreaterThanOrEqual(r.isochrones.length)
    }
  })

  it('中心点投影落在画布正中（投影语义单一源）', () => {
    const c = reports[0].scene.center as LngLat
    const [x, y] = lcToPx(c, c[0], c[1])
    expect(x).toBeCloseTo(LC_CANVAS.W / 2, 6)
    expect(y).toBeCloseTo(LC_CANVAS.H / 2, 6)
  })

  it('**当前行为**：R 为常量 → 9000m 半径的圈投影溢出画布（B2 前置证据）', () => {
    // TODO（B2）：R 改由 report.scene.study_radius_m 派生后，此用例应断言 x <= W。
    const c: LngLat = [121.505252, 31.23333]
    const lngAt = (meters: number) => c[0] + meters / (111320 * Math.cos((c[1] * Math.PI) / 180))
    const [x2500] = lcToPx(c, lngAt(2500), c[1])
    const [x9000] = lcToPx(c, lngAt(9000), c[1])
    expect(x2500).toBeCloseTo(LC_CANVAS.W, 6) // 研究域右边界恰为画布右沿
    expect(x9000).toBeGreaterThan(LC_CANVAS.W * 2) // 骑行/驾车分档后溢出 → SVG 裁切
    expect(lcMeters(c, lngAt(9000), c[1])[0]).toBeCloseTo(9000, 0)
  })

  it.todo('B2：R 派生自 study_radius_m 后，9000m 圈必须完整落在画布内（对比模式取 max(R_A,R_B)）')

  it('poi.points 为空数组时等时圈几何渲染路径不受影响（点位与圈层解耦）', () => {
    const r = offlineReport()
    expect(r.poi.points).toEqual([])
    for (const z of r.isochrones) {
      const pts = lcPolyPts(r.scene.center as LngLat, z.geojson.coordinates[0] as LngLat[])
      expect(pts.split(' ').length).toBe(z.geojson.coordinates[0].length)
      expect(pts).not.toContain('NaN')
    }
  })
})
describe('L10 · 对比呈现决策原语（选谁 → 怎么呈现一体决策）', () => {
  const c = [107.98, 26.25] as LngLat

  it('lcSceneDistanceM 距离度量守恒（经度每差 ~0.01° ≈ 1000m）', () => {
    const d = lcSceneDistanceM(c, east(c[0], 0.01))
    expect(d).toBeCloseTo(1000, -1) // 量级正确（±100m 内）
    expect(lcSceneDistanceM(c, c)).toBe(0)
    // 对称性
    expect(lcSceneDistanceM(c, east(c[0], 0.02))).toBeCloseTo(lcSceneDistanceM(east(c[0], 0.02), c), 0)
  })

  it('lcCoLocated 在 4km 阈值内外正确翻转', () => {
    const near = lngM(0.02) // ≈2km
    const far = lngM(0.06) // ≈6km
    expect(near).toBeLessThan(LC_CO_LOCATED_M)
    expect(far).toBeGreaterThan(LC_CO_LOCATED_M)
    expect(lcCoLocated(c, east(c[0], 0.02))).toBe(true)
    expect(lcCoLocated(c, east(c[0], 0.06))).toBe(false)
  })

  it('planComparisonOverlay：同片 → shareMap 单图叠加；跨城 → 双图 + 归一示意', () => {
    expect(planComparisonOverlay(c, east(c[0], 0.02))).toEqual({
      shareMap: true,
      normalize: false,
      reason: 'co-located',
    })
    expect(planComparisonOverlay(c, east(c[0], 0.06))).toEqual({
      shareMap: false,
      normalize: true,
      reason: 'cross-location',
    })
  })
})

/* ── 阶段 3 · 机制层护栏（让「图上点数 == 面板数字」不再靠人工核对） ──────────────
 *
 * 为什么必须再加一层：阶段 1 已经有守恒判据（`poiConservation`），但它只校验
 * **报告数据自洽**（`sum(categories[].in_circle) === len(points)`），
 * 不校验**渲染层是否照数画完**。阶段 2 之前，渲染层各自还有 120/60 的静态上限，
 * 于是「数据守恒但图上少画」照样能全绿 —— 护栏只守住了半程。
 *
 * 本组把后半程也钉住：面板的「已展示 K」必须 == 下发给渲染层的点数，
 * 且未聚合时 == 图上标记数。三条一起成立，「点位能追到数字」才是**机器可校验**的。
 * ------------------------------------------------------------------------- */

describe('阶段 3 · 图上点数与面板数字的可对账契约', () => {
  /** 从指标文案里取出三段数字（断言用它，而不是在测试里重算 —— 重算就变成"自己等于自己"）。 */
  function segments(label: string): { total: number; declared: number; actual: number } {
    const m = label.match(/采集 (\d+) · 圈内 (\d+) · 已展示 (\d+)/)
    expect(m, `指标文案不符合三段式口径：${label}`).not.toBeNull()
    return { total: Number(m![1]), declared: Number(m![2]), actual: Number(m![3]) }
  }

  it('3.3 面板「已展示」== 下发给渲染层的点数（`poiRenderSet().handed`）', () => {
    for (const r of reports) {
      const set = poiRenderSet(r.poi.points)
      expect(segments(poiMetricLabel(r)).actual).toBe(set.handed)
      expect(set.handed).toBe(r.poi.points.length)
    }
  })

  it('3.3 未聚合时「图上标记数 == 面板已展示」（用户最初的诉求，机器可校验）', () => {
    for (const r of reports) {
      const set = poiRenderSet(r.poi.points)
      expect(set.thinned).toBe(false) // 当前量级不触发聚合
      expect(set.shown).toBe(segments(poiMetricLabel(r)).actual)
    }
  })

  it('3.4 三处渲染入口取用同一份点集（同一 fixture → 同一 reps，逐点一致）', () => {
    // live 是 BMapGL DOM、另两处是 SVG，产出形态不同、无法断言"同构节点"；
    // 可断言的是**取数同源**：三处都经 `poiRenderSet()`，故对同一份报告必须得到同一份 reps。
    for (const r of reports) {
      const a = poiRenderSet(r.poi.points).reps
      const b = poiRenderSet(r.poi.points).reps
      expect(a.map((p) => p.id)).toEqual(b.map((p) => p.id))
      // 三处画的是同一批点 ⇒ 点数 = 面板已展示（无聚合时）
      expect(a).toHaveLength(segments(poiMetricLabel(r)).actual)
    }
  })

  it('3.4 渲染层不再有静态数量上限（阈值是安全阀，不是新口径）', () => {
    // 旧实现：`lcSnapshotPoiLayer` 默认 cap=120、降级画布 60、live POI_MARKER_CAP=120。
    // 这三处都是"报告说有 98 处、图上只画 N 个"的第二权威。用行为断言它们不可复发：
    const many = Array.from({ length: POI_THIN_THRESHOLD - 1 }, (_, i) => ({
      id: `x-${i}`,
      name: `点${i}`,
      category: 'market',
      lnglat: [107.95 + i * 1e-5, 26.57] as LngLat,
      minutes: 5,
      in_circle: true,
    }))
    expect(POI_THIN_THRESHOLD).toBeGreaterThan(300)
    // ① 投影层默认不截断（旧默认 120 会砍掉 279 个）
    expect(lcSnapshotPoiLayer(kaili.scene.center as LngLat, many)).toHaveLength(many.length)
    // ② 点集入口在阈值内原样放行
    const set = poiRenderSet(many)
    expect(set.thinned).toBe(false)
    expect(set.shown).toBe(many.length)
  })

  it('3.2 `poi.truncated` 恒存在，且未截断时 dropped=0 / cap 有值', () => {
    for (const r of reports) {
      expect(r.poi.truncated, '新口径报告的 poi.truncated 必须存在（无截断也要留痕）').toBeDefined()
      expect(r.poi.truncated!.dropped).toBe(0)
      expect(r.poi.truncated!.categories).toEqual([])
      expect(r.poi.truncated!.cap_per_cat).toBe(200)
    }
  })

  it('3.2 截断披露必须能与实际点集对账（kept == 实到；dropped == 逐类之和）', () => {
    const src = kaili as unknown as LivingCircleReport
    // 造一份"真的截断过"的报告：shopping 采集到 30、留下 25、砍掉 5
    const truncated = {
      ...src,
      poi: {
        ...src.poi,
        categories: [{ category: 'shopping', in_circle: 25 }],
        total: 60,
        in_circle: 25,
        points: src.poi.points.filter((p) => p.category === 'shopping').slice(0, 25),
        truncated: {
          cap_per_cat: 200,
          dropped: 5,
          categories: [{ category: 'shopping', kept: 25, dropped: 5 }],
        },
      },
    } as LivingCircleReport
    const tr = truncated.poi.truncated!
    const actualCat = truncated.poi.points.filter((p) => p.category === 'shopping').length
    // ⭐ 关键：披露里的 `kept` 必须等于**真的画出去的点数**，否则披露本身又是一套算法
    expect(tr.categories[0].kept).toBe(actualCat)
    expect(tr.categories[0].kept).toBe(truncated.poi.categories[0].in_circle) // 守恒
    // `dropped` 总量必须等于逐类之和（否则「另有 N 处未展示」会与明细打架）
    expect(tr.dropped).toBe(tr.categories.reduce((s, x) => s + x.dropped, 0))
    expect(tr.categories[0].dropped).toBe(5)
    expect(tr.dropped).toBe(5)
    // 被砍掉的 5 处确实**不在**点集里（截断 = 少给点，不是少计数）
    expect(truncated.poi.points).toHaveLength(25)
    // 且必然被披露（不许静默）
    expect(poiMetricLabel(truncated)).toContain('另有 5 处未展示')
  })

  it('3.6 负对照：in_circle=8 / points=6 的违规样本 → 守恒判据必须红', () => {
    // 8 vs 6 是审查给的最小样本：差额小到"肉眼看着差不多"，守卫若靠阈值就会漏掉。
    const bad = {
      poi: {
        categories: [{ category: 'medical', in_circle: 8 }],
        total: 40,
        in_circle: 8,
        points: kaili.poi.points.slice(0, 6),
        truncated: { cap_per_cat: 200, dropped: 0, categories: [] },
      },
    } as unknown as LivingCircleReport
    const c = poiConservation(bad)
    expect(c.declared).toBe(8)
    expect(c.actual).toBe(6)
    expect(c.delta).toBe(-2)
    expect(c.ok).toBe(false)
    expect(poiConservationNote(bad)).toContain('少 2 处')
    // 同一份违规样本，指标文案必须**把差额摆在明面上**（而不是显示成自洽的样子）
    expect(poiMetricLabel(bad)).toBe('采集 40 · 圈内 8 · 已展示 6')
  })

  it('3.6 负对照的另一半：数字自洽时**不得**误报（避免把合法报告判红/刷屏）', () => {
    // 与上条互为对照 —— 判据既要在违规时红，也要在合法时绿。只测前者会得到
    // 一个"永远返回 red"的假护栏（例如把判据写成恒 false），它同样毫无价值。
    const okReport = {
      poi: {
        categories: [{ category: 'medical', in_circle: 6 }],
        total: 40,
        in_circle: 6,
        points: kaili.poi.points.slice(0, 6),
        truncated: { cap_per_cat: 200, dropped: 0, categories: [] },
      },
    } as unknown as LivingCircleReport
    expect(poiConservation(okReport).ok).toBe(true)
    expect(poiConservationNote(okReport)).toBeNull()
    expect(poiMetricLabel(okReport)).toBe('采集 40 · 圈内 6 · 已展示 6')
    expect(poiMetricLabel(okReport)).not.toContain('另有')
  })

  it('3.7 软上限告警：单类 > 200 ⇒ dropped>0 且被**显式披露**（不许静默）', () => {
    const src = kaili as unknown as LivingCircleReport
    // 真正造 200 个点（夹具只有 98 个，直接 slice 会得到 98 ⇒ 断言退化成"已展示 98"，测不到上限）
    const pts200 = Array.from({ length: 200 }, (_, i) => ({
      id: `poi-shopping-${i}`,
      name: `购物点${i}`,
      category: 'shopping',
      lnglat: [107.95 + i * 1e-5, 26.57] as LngLat,
      minutes: 6,
      in_circle: true,
    }))
    const capped = {
      ...src,
      poi: {
        ...src.poi,
        categories: [{ category: 'shopping', in_circle: 200 }],
        total: 431,
        in_circle: 200,
        points: pts200,
        truncated: {
          cap_per_cat: 200,
          dropped: 31,
          categories: [{ category: 'shopping', kept: 200, dropped: 31 }],
        },
      },
    } as LivingCircleReport
    expect(capped.poi.points).toHaveLength(200)
    expect(capped.poi.truncated!.dropped).toBeGreaterThan(0)
    const label = poiMetricLabel(capped)
    expect(label).toContain('已展示 200')
    expect(label).toContain('另有 31 处未展示')
    expect(label).toContain('shopping 31')
    expect(label).toContain('每类上限 200')
    // 反例护栏：没截断时**不得**出现第四段（否则披露会退化成噪声、进而被忽略）
    expect(poiMetricLabel(kaili as unknown as LivingCircleReport)).not.toContain('另有')
  })
})

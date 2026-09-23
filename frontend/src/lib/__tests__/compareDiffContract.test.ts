// 阶段 5 · R6 · 对比页差异表契约（前端侧）
//
// 与后端 `backend/tests/test_living_circle_api.py` 读**同一份**夹具
// `src/__tests__/fixtures/compareDiffContract.json`，各自断言**同一串期望字面量** ——
// 范式同 `poi_metric_label` / `poiMetricLabel`（Py/TS 各一份实现，靠同源夹具对齐）。
// ⇒ 任何一侧改了行名、行序或句式而不改夹具，两侧测试必红；改了夹具而只改一侧，另一侧必红。
//
// 本文件钉住五件事：
//  ① 行名集合 + 行序与夹具逐项相同（「加/删/改名一行」必红且报差集）；
//  ② 每行的 `better` 方向与 `template` 句式与夹具一致；
//  ③ 18 条 desc 用例（6 行 × A>B / A<B / 相等）逐项相符；
//  ④ 相等词统一为 `COMPARE_EQUAL_WORD`，不再「相当 / 持平」混用；
//  ⑤ ⭐ **取值出口纪律**：`num()` 走 `poiConservation()` / `samplingReach()`，
//     用**注入违规样本**反向验证（喂「顶层冗余字段说谎」「汇总数与自算不一致」的样本 ⇒ 必红）。
//     —— 依据：`types.ts:551`「消费方请走 poiConservation()，不要自己求和下结论」·
//     `types.ts:742`「缺失时请用 samplingReach() 回算，不要自行 filter」。
import { describe, it, expect } from 'vitest'

import {
  COMPARE_EQUAL_WORD,
  COMPARE_ROWS,
  compareDesc,
  poiConservation,
  samplingReach,
} from '../livingCircle'
import type { LivingCircleReport } from '../../types'
import contractJson from '../../__tests__/fixtures/compareDiffContract.json'
import kailiJson from '../../mocks/fixtures/livingCircle/kaili.json'
import jinsongJson from '../../mocks/fixtures/livingCircle/beijing-jinsong.json'

/** 夹具的显式形状（JSON 推断出的字面量类型太窄，比对本就要按契约形状来）。 */
interface Contract {
  _equal_word: string
  names: string[]
  rows: { key: string; better: string; template: string }[]
  desc_cases: { row: string; a: number; b: number; desc: string }[]
  offline_backend_only: {
    not_collected_desc: string
    not_comparable_value: string
    not_comparable_desc: string
    _applies_to: Record<string, string[]>
  }
}

const C = contractJson as unknown as Contract
const KAILI = kailiJson as unknown as LivingCircleReport
const JINSONG = jinsongJson as unknown as LivingCircleReport

const DEF_OF = (key: string) => COMPARE_ROWS.find((d) => d.key === key)

describe('R6 · 对比页行定义表 ←→ 契约夹具', () => {
  it('行名集合与行序与夹具逐项相同（6 行）', () => {
    const got = COMPARE_ROWS.map((d) => d.key)
    const want = C.rows.map((r) => r.key)
    expect(
      got,
      `行名/行序与契约夹具不符：\n  期望 ${JSON.stringify(want)}\n  实际 ${JSON.stringify(got)}\n` +
        `  差集(缺) ${JSON.stringify(want.filter((k) => !got.includes(k)))}` +
        ` 差集(多) ${JSON.stringify(got.filter((k) => !want.includes(k)))}`,
    ).toEqual(want)
  })

  it('每行的 better 方向与 template 句式与夹具一致', () => {
    const bad: string[] = []
    for (const r of C.rows) {
      const def = DEF_OF(r.key)
      if (!def) {
        bad.push(`${r.key}: COMPARE_ROWS 中不存在`)
        continue
      }
      if (def.better !== r.better) bad.push(`${r.key}: better 期望 ${r.better} 实得 ${def.better}`)
      if (def.template !== r.template) bad.push(`${r.key}: template 期望 ${JSON.stringify(r.template)} 实得 ${JSON.stringify(def.template)}`)
    }
    expect(bad, `方向/句式与夹具不符 ${bad.length} 处:\n${bad.join('\n')}`).toEqual([])
  })

  it('desc 用例表逐项相符（6 行 × A>B / A<B / 相等 = 18 条）', () => {
    const [nameA, nameB] = C.names
    const bad: string[] = []
    for (const c of C.desc_cases) {
      const def = DEF_OF(c.row)
      if (!def) {
        bad.push(`${c.row}: 行不存在`)
        continue
      }
      const got = compareDesc(def, c.a, c.b, nameA, nameB)
      if (got !== c.desc) {
        bad.push(`${c.row} a=${c.a} b=${c.b}: 期望 ${JSON.stringify(c.desc)} 实得 ${JSON.stringify(got)}`)
      }
    }
    expect(C.desc_cases.length, '用例表至少要有 6 行 × 3 方向').toBeGreaterThanOrEqual(18)
    expect(bad, `desc 用例不符 ${bad.length} 条:\n${bad.join('\n')}`).toEqual([])
  })

  it('相等词统一为夹具里那一个词（不再「相当 / 持平」混用）', () => {
    expect(COMPARE_EQUAL_WORD).toBe(C._equal_word)
    const equalCases = C.desc_cases.filter((c) => c.a === c.b)
    expect(equalCases.length, '用例表里必须有相等用例').toBeGreaterThan(0)
    const words = [...new Set(equalCases.map((c) => c.desc))]
    expect(words, `相等用例出现了 ${words.length} 个不同词：${JSON.stringify(words)}`).toEqual([C._equal_word])
  })

  it('⭐ 服务盲区方向必须是 lower：样本 a=0 / b=1 ⇒「A盲区更少」（旧实现输出事实相反的 B）', () => {
    // 这条是**独立的**判别点，不依赖夹具（夹具被改也能发现方向写错）：
    // 盲区越少越好。误用「大者胜」⇒ 0 > 1 为 false ⇒ 输出「B盲区更少」= 事实相反。
    const def = DEF_OF('服务盲区')!
    expect(compareDesc(def, 0, 1, 'A', 'B')).toBe('A盲区更少')
    expect(compareDesc(def, 1, 0, 'A', 'B')).toBe('B盲区更少')
    // 真实夹具实测值：凯里 0 处 / 劲松 1 处 —— 与契约夹具同形，可互换复用。
    expect([KAILI.blindspots.length, JINSONG.blindspots.length]).toEqual([0, 1])
  })
})

describe('R6 · num() 在真实夹具上的取值与展示', () => {
  it('六行取值（A=凯里 / B=劲松）与实测一致', () => {
    const got = Object.fromEntries(COMPARE_ROWS.map((d) => [d.key, [d.num(KAILI), d.num(JINSONG)]]))
    expect(got).toEqual({
      '15min 等时圈面积 (km²)': [1.56, 1.76],
      可达采样点数: [126, 162],
      'POI 采集': [217, 175],
      '圈内 POI': [98, 104],
      服务盲区: [0, 1],
      综合评分: [68.7, 65.3],
    })
  })

  it('面积行：比较值与展示值是同一个数（两侧都两位小数，否则同报告两模式显示不同数字）', () => {
    const def = DEF_OF('15min 等时圈面积 (km²)')!
    // 夹具原始值是 1.562 / 1.764 —— 展示与比较都必须落在两位小数后的那个数上。
    expect(def.num(KAILI)).toBe(1.56)
    expect(def.cell(KAILI)).toBe('1.56 km²')
    expect(def.cell(JINSONG)).toBe('1.76 km²')
  })

  it('cell() 是展示形态且与 num() 同源（单位/上下文只出现在 cell，不出现在表里的 num）', () => {
    expect(DEF_OF('可达采样点数')!.cell(KAILI)).toBe('126 个（共采样 1049）')
    expect(DEF_OF('可达采样点数')!.num(KAILI)).toBe(126)
    expect(DEF_OF('POI 采集')!.cell(KAILI)).toBe('217 处')
    expect(DEF_OF('圈内 POI')!.cell(KAILI)).toBe('98 处')
    expect(DEF_OF('服务盲区')!.cell(KAILI)).toBe('0 处')
    expect(DEF_OF('综合评分')!.cell(KAILI)).toBe('68.7')
  })
})

describe('R6 · ⭐ 取值出口纪律（注入违规样本反向验证，不盲信实现）', () => {
  it('「圈内 POI」num() 不读顶层冗余字段 poi.in_circle（喂谎言样本必红）', () => {
    const def = DEF_OF('圈内 POI')!
    // 原样本：顶层 in_circle=98 且 Σcategories=98，两者同值 ⇒ **无判别力**。
    // 必须把顶层字段改成谎言，才能区分「走出口」与「直读顶层字段」。
    const liar = { ...KAILI, poi: { ...KAILI.poi, in_circle: 999 } } as LivingCircleReport
    expect(def.num(liar), '顶层字段说谎时仍须给出 Σcategories 的值').toBe(98)
    expect(def.num(liar), '与 poiConservation() 出口同值').toBe(poiConservation(liar).declared)
    expect(def.num(liar), '若直读 poi.in_circle 会得 999').not.toBe(999)
  })

  it('「圈内 POI」num() 不自己求和（喂「categories 与 points 不一致」样本时仍与出口同值）', () => {
    const def = DEF_OF('圈内 POI')!
    // 注入：把某一类的 in_circle 改掉 ⇒ Σcategories=104，而 points 仍有 98 个。
    const cats = (KAILI.poi.categories ?? []).map((c, i) => (i === 0 ? { ...c, in_circle: (c.in_circle ?? 0) + 6 } : c))
    const skewed = { ...KAILI, poi: { ...KAILI.poi, categories: cats } } as LivingCircleReport
    expect(def.num(skewed)).toBe(104)
    expect(def.num(skewed)).toBe(poiConservation(skewed).declared)
    expect(poiConservation(skewed).actual, '图上点数不变').toBe(98)
    expect(poiConservation(skewed).ok, '该样本本身不守恒 ⇒ 会触发 R6.9 披露').toBe(false)
  })

  it('「可达采样点数」num() 取出口值：汇总数与按点自算不一致时，以出口为准', () => {
    const def = DEF_OF('可达采样点数')!
    // 原样本：in_reach_count=126 且按点统计恰好也是 126 ⇒ **无判别力**。
    // 注入：把汇总数改成 7，自算仍是 126 —— 只有这样才分得开「走出口」与「自行 filter」。
    const skewed = { ...KAILI, sampling: { ...KAILI.sampling, in_reach_count: 7 } } as LivingCircleReport
    expect(def.num(skewed)).toBe(samplingReach(skewed).inReach)
    expect(def.num(skewed)).toBe(7)
    // 自算口径（自行 filter）会得 126 —— 断言它确实不同，证明这条用例有判别力。
    const selfCounted = (skewed.sampling?.points ?? []).filter((p) => p.in_reach === true).length
    expect(selfCounted, '样本必须能区分「走出口」与「自行 filter」，否则这条是假护栏').toBe(126)
  })

  it('「POI 采集」num() 直读 poi.total 是**合法**的：它是采集口径的唯一字段，无第二读法', () => {
    const def = DEF_OF('POI 采集')!
    expect(def.num(KAILI)).toBe(217)
    expect(def.num(JINSONG)).toBe(175)
    // 与「圈内 POI」不同：把顶层冗余字段改掉**不影响**本行（本行本就不读它）。
    const liar = { ...KAILI, poi: { ...KAILI.poi, in_circle: 999 } } as LivingCircleReport
    expect(def.num(liar)).toBe(217)
  })
})

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
  CALIBER_GAP_DESC,
  CALIBER_GAP_ROW_KEYS,
  COMPARE_EQUAL_WORD,
  COMPARE_ROWS,
  caliberPolicyGap,
  compareCaliberNotice,
  compareDesc,
  compareRows,
  confidenceBadgeLabel,
  confidenceOf,
  poiConservation,
  policyVersionOf,
  samplingReach,
  staleCaliberNotice,
  SCOPE_POLICY_VERSION,
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
  caliber_incomparable: {
    policy_version_current: string
    desc: string
    stale_notice: string
    applies_to: string[]
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
    // ⚠️ 这里**不再**用出厂快照的盲区数当"同形证据"：ev-1 重刷后两城实测盲区都是 0 处，
    //    真实对上根本没有方向样本（旧断言 `toEqual([0, 1])` 会随快照翻面）。方向判据由上面
    //    两行纯函数断言 + `comparePage.test.tsx`「盲区行方向：自带载体」的注入样本共同守。
  })
})

describe('R6 · num() 在真实夹具上的取值与展示', () => {
  it('六行取值（A=凯里 / B=劲松）与实测一致', () => {
    const got = Object.fromEntries(COMPARE_ROWS.map((d) => [d.key, [d.num(KAILI), d.num(JINSONG)]]))
    // 每行两列：[凯里, 劲松]。劲松列 = `ev-1` 重刷代际（采集 206 / 圈内 150 / 实测盲区 0 /
    // 65.8 分）；凯里列仍是升级前快照。与后端 `test_residential_category_baseline.py` 同源。
    expect(got).toEqual({
      '15min 等时圈面积 (km²)': [1.56, 1.76],
      可达采样点数: [126, 162],
      'POI 采集': [217, 206],
      '圈内 POI': [98, 150],
      服务盲区: [0, 0],
      综合评分: [68.7, 65.8],
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
    expect(def.num(JINSONG)).toBe(206) // ev-1 重刷代际：采集域逐类外扩（175→206）
    // 与「圈内 POI」不同：把顶层冗余字段改掉**不影响**本行（本行本就不读它）。
    const liar = { ...KAILI, poi: { ...KAILI.poi, in_circle: 999 } } as LivingCircleReport
    expect(def.num(liar)).toBe(217)
  })
})

/* ── P0-3 · 判盲口径版本守卫（前端侧，与后端 test_caliber_gap_* 读同一份夹具）────
   钉的是「演示态与真实态同判据」：真实态由 `main.py:_lc_diff` 拦，演示态由
   `compareRows()` 拦。两态各写一份正是本仓反复出事的形态，所以这里既比字面量、
   也比**行为**（同一对报告在两态下应得到同样的结论句）。 */
describe('P0-3 · 判盲口径版本守卫', () => {
  const GAP = C.caliber_incomparable

  /** 给快照盖版本戳（`null` = 抹掉，模拟升级前的旧报告）。
   *  ⚠️ 为什么判据一律走戳而不走出厂快照的现值：kaili 是旧快照（未声明）、jinsong 已是
   *  `ev-1`（2026-09-27 重刷），两份快照的代际关系是**过渡态**，重刷凯里就会翻面。挂在
   *  现值上的断言到那天会集体假红（或更糟：假绿）。真正该守的是**规则**，规则用戳来构造。 */
  const stamp = (lc: LivingCircleReport, v: string | null) => {
    const caliber = { ...(lc.caliber ?? {}) } as Record<string, unknown>
    if (v === null) delete caliber.scope_policy_version
    else caliber.scope_policy_version = v
    return { ...lc, caliber } as LivingCircleReport
  }
  const OLD = null
  const NEW = SCOPE_POLICY_VERSION

  it('前端常量与契约夹具逐字相同（版本 / 结论句 / 受影响的行）', () => {
    expect(SCOPE_POLICY_VERSION).toBe(GAP.policy_version_current)
    expect(CALIBER_GAP_DESC).toBe(GAP.desc)
    expect([...CALIBER_GAP_ROW_KEYS]).toEqual(GAP.applies_to)
    // 受影响的行必须真存在于行定义表里（改名而忘了这里 ⇒ 守卫静默失灵）
    for (const key of CALIBER_GAP_ROW_KEYS) {
      expect(DEF_OF(key), `CALIBER_GAP_ROW_KEYS 里的 ${key} 不在 COMPARE_ROWS 中`).toBeTruthy()
    }
  })

  it('两侧同版本 ⇒ 可比，不得谎报不可比（都旧 / 都新两种同版本都要过）', () => {
    for (const v of [OLD, NEW]) {
      const a = stamp(KAILI, v)
      const b = stamp(JINSONG, v)
      expect(caliberPolicyGap(a, b), `同版本 ${v ?? '未声明'} 被判成不可比`).toBe(false)
      const rows = compareRows(a, b, 'A', 'B')
      expect(rows.map((r) => r.metric)).toEqual(C.rows.map((r) => r.key))
      for (const key of GAP.applies_to) {
        const def = DEF_OF(key)!
        const row = rows.find((r) => r.metric === key)!
        expect(row.desc, `${key} 不该被标为不可比`).not.toBe(GAP.desc)
        // 且必须仍是「谁更…」那句，与 `compareDesc` 直出结果逐字相同 ⇒ 守卫没有顺手吞掉结论
        expect(row.desc).toBe(compareDesc(def, def.num(a), def.num(b), 'A', 'B'))
      }
    }
  })

  it('版本错配 ⇒ 只拦那两行的结论，数值原样保留（一侧旧一侧新 / 一侧新一侧未声明）', () => {
    for (const legacy of ['ev-0-legacy', OLD]) {
      const a = stamp(KAILI, NEW)
      const b = stamp(JINSONG, legacy)
      expect(caliberPolicyGap(a, b)).toBe(true)

      const rows = compareRows(a, b, 'A', 'B')
      const plain = compareRows(stamp(KAILI, NEW), stamp(JINSONG, NEW), 'A', 'B')
      const byMetric = Object.fromEntries(rows.map((r) => [r.metric, r]))
      for (const key of GAP.applies_to) {
        expect(byMetric[key].desc, `${key} 必须标注不可比`).toBe(GAP.desc)
      }
      for (const key of ['15min 等时圈面积 (km²)', '可达采样点数', 'POI 采集', '圈内 POI']) {
        expect(byMetric[key].desc).not.toBe(GAP.desc)
      }
      // ⭐ 拦的是**结论句**，不是数据：每行的 a_value/b_value 必须与「不拦」时逐字节相同
      //（数值是各自口径下真实算出来的事实，改成「—」就是把事实也一起藏了）。
      expect(rows.map((r) => [r.metric, r.a_value, r.b_value])).toEqual(
        plain.map((r) => [r.metric, r.a_value, r.b_value]),
      )
      expect(rows.map((r) => r.metric)).toEqual(C.rows.map((r) => r.key))
    }
  })

  it('compareCaliberNotice：版本不同 / 两份都旧 / 两份都新，三种情形各得其所', () => {
    expect(compareCaliberNotice(stamp(KAILI, NEW), stamp(JINSONG, OLD))).toContain('两侧判盲口径不同')
    // ⭐ 存量报告两两对比（都出自升级前）：它们彼此可比，但两个分数**都**偏乐观 ——
    //    只报「不同」不报「都旧」，观众看到的仍是两个被高估的分数并排。
    expect(compareCaliberNotice(stamp(KAILI, OLD), stamp(JINSONG, OLD))).toContain('都出自判盲口径升级前')
    expect(compareCaliberNotice(stamp(KAILI, NEW), stamp(JINSONG, NEW))).toBeNull()
  })

  it('陈旧提示：未声明 ⇒ 必出提示，已声明当前版本 ⇒ 必不出（文案与夹具同源）', () => {
    expect(policyVersionOf(stamp(KAILI, OLD))).toBeNull()
    expect(staleCaliberNotice(stamp(KAILI, OLD))).toBe(GAP.stale_notice)
    expect(policyVersionOf(stamp(KAILI, NEW))).toBe(NEW)
    expect(staleCaliberNotice(stamp(KAILI, NEW))).toBeNull()
    // 声明了**别的**版本（将来 ev-2 上线、或历史遗留串）⇒ 同样算陈旧，且必须点名差在哪：
    // 契约夹具只收录「未声明」那一句，带版本号的句子由实现现拼（不另立字面量真源）。
    const foreign = staleCaliberNotice(stamp(KAILI, 'ev-0-legacy'))
    expect(foreign).not.toBeNull()
    expect(foreign).toContain('ev-0-legacy')
    expect(foreign).toContain(NEW)
    expect(foreign).not.toBe(GAP.stale_notice)
  })

  it('出厂演示对（凯里 vs 劲松）当前代际关系 ⇒ 守卫在真数据上的表现与规则一致', () => {
    // 不写死「现在谁新谁旧」，只写死「无论谁新谁旧，结论都必须由同一条规则推出」：
    // 重刷凯里后这一对转为可比，本用例自动换断言，不会假绿也不会假红。
    const gap = caliberPolicyGap(KAILI, JINSONG)
    const notice = compareCaliberNotice(KAILI, JINSONG)
    const rows = Object.fromEntries(compareRows(KAILI, JINSONG, 'A', 'B').map((r) => [r.metric, r]))
    for (const key of GAP.applies_to) {
      if (gap) expect(rows[key].desc, `${key} 两版本不同却仍给了结论句`).toBe(GAP.desc)
      else expect(rows[key].desc, `${key} 两版本相同却谎报不可比`).not.toBe(GAP.desc)
    }
    if (gap) expect(notice).toContain('两侧判盲口径不同')
    else if (policyVersionOf(KAILI) === null) expect(notice).toContain('都出自判盲口径升级前')
    else expect(notice).toBeNull()
    // 无论哪条分支：数值行永远照常给结论（拦结论不拦数值）
    expect(rows['POI 采集'].desc).not.toBe(GAP.desc)
    expect(rows['圈内 POI'].desc).not.toBe(GAP.desc)
  })

  it('confidence 安全取值：旧快照缺键 ⇒ null（不猜 full），limited ⇒ 降档徽标带覆盖率', () => {
    // ① 演示链（内嵌夹具）没有 scores.confidence —— 渲染层必须拿 null，不能崩也不能自称 full
    expect(confidenceOf(KAILI)).toBeNull()
    expect(confidenceBadgeLabel(KAILI)).toBeNull()

    // ② 新口径 + 证据不足 ⇒ 徽标出现，文案里的覆盖率来自 caliber 分账（唯一真源）
    const discounted = {
      ...KAILI,
      scores: { ...KAILI.scores, confidence: 'limited' },
    } as unknown as LivingCircleReport
    const pct = Math.round((KAILI.caliber!.cells_judged! / KAILI.caliber!.cells_inside!) * 100)
    expect(confidenceOf(discounted)).toBe('limited')
    expect(confidenceBadgeLabel(discounted)).toBe(`证据面不足 · 覆盖率 ${pct}%`)

    // ③ 反例：判满且证据齐 ⇒ 不挂徽标（否则「降档」变成常驻噪声，等于没有信号）
    const full = {
      ...KAILI,
      scores: { ...KAILI.scores, confidence: 'full' },
    } as unknown as LivingCircleReport
    expect(confidenceBadgeLabel(full)).toBeNull()
  })
})

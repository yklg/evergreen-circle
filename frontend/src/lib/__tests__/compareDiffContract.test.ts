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
  BOTH_GAP_DESC,
  CALIBER_AXES,
  CALIBER_GAP_DESC,
  CALIBER_GAP_ROW_KEYS,
  COMPARE_EQUAL_WORD,
  COMPARE_ROWS,
  COVERAGE_CALIBER_VERSION,
  COVERAGE_GAP_DESC,
  COVERAGE_GAP_ROW_KEYS,
  caliberGapDesc,
  caliberPolicyGap,
  compareCaliberNotice,
  compareCaliberNotices,
  compareDesc,
  compareRows,
  confidenceBadgeLabel,
  confidenceOf,
  coverageCaliberGap,
  coverageCaliberVersionOf,
  gapDescFor,
  poiConservation,
  policyVersionOf,
  samplingReach,
  staleCaliberNotice,
  staleCaliberNotices,
  staleCoverageCaliberNotice,
  SCOPE_POLICY_VERSION,
} from '../livingCircle'
import type { LivingCircleReport } from '../../types'
import type { CaliberAxis } from '../livingCircle'
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
    // 第二根轴（片 1c-β C3）：评分口径 `cov-*` 的对照值与三句结论句
    coverage_version_current: string
    coverage_desc: string
    both_desc: string
    coverage_stale_notice: string
    // #83：评分轴的**行级**作用面（`applies_to` 是并集，不是"每行都吃满两根轴"）
    coverage_applies_to: string[]
    // 措辞改为按轴子句组合后新增的两格：**有序**轴清单 + 轴→复用门版本字段映射。
    // 后端 `test_caliber_axes_are_registered_everywhere_they_must_be` 与这里各比对一次，
    // 钉的是"加一根轴必须同时登记三处"（措辞表 / 复用门 / 夹具）。
    axes: CaliberAxis[]
    axis_fields: Record<CaliberAxis, string>
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
    // 65.8 分）；凯里列 = 10-01 `cov-1` 回填代际（教育 coverage 1.0 → 0.3333 ⇒ 总分 68.7 → 65.4）。
    // ⚠️ 这一格换数之后，**两城总分反了**：凯里 65.4 < 劲松 65.8 ⇒ 拿这两份演示数据对比时
    //    "A更成熟"不再成立（旧注释里那句"68.7>65.8"是回填前的事实）。与后端
    //    `test_residential_category_baseline.py` 同源。
    expect(got).toEqual({
      '15min 等时圈面积 (km²)': [1.56, 1.76],
      可达采样点数: [126, 162],
      'POI 采集': [217, 206],
      '圈内 POI': [98, 150],
      服务盲区: [0, 0],
      综合评分: [65.4, 65.8],
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
    // 10-01 `cov-1` 回填后的真读数（回填前是 '68.7'；这一格与上面六行表同一件事）
    expect(DEF_OF('综合评分')!.cell(KAILI)).toBe('65.4')
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
    // #83：`applies_to` 是「受**某根**轴影响的行**并集**」，评分轴的作用面单独一颗钉。
    // 少了这条，「只评分轴不同」那一档会重新拦掉判盲轴才管得着的「服务盲区」行。
    expect([...COVERAGE_GAP_ROW_KEYS]).toEqual(GAP.coverage_applies_to)
    expect(COVERAGE_GAP_ROW_KEYS, '盲区数只由判盲那把尺决定，评分轴拦不到它').not.toContain(
      '服务盲区',
    )
    for (const key of COVERAGE_GAP_ROW_KEYS) {
      expect(CALIBER_GAP_ROW_KEYS, `${key} 不在并集里 ⇒ 并集在说谎`).toContain(key)
    }
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
})

/* ── 第二根轴 · 评分口径（`cov-1`）守卫（片 1c-β C2/C3 = 第 21 轮 P1-3）──────────────
   判盲那把尺与评分那把尺**互相独立**（换分子不改证据域，扩证据域也不改分子），所以要拦
   "两把键互相顶替"的**两个方向**：只有评分轴不同 ⇒ 那句里不许出现"判盲"；只有判盲轴不同
   ⇒ 不许出现"评分口径"。版本一律由测试自己拼装（不读出厂快照现值），理由同上面那个 describe。 */
describe('第二根轴 · 评分口径版本守卫', () => {
  const GAP = C.caliber_incomparable
  const EV = SCOPE_POLICY_VERSION
  const COV = COVERAGE_CALIBER_VERSION

  /** 同时盖两根轴的版本戳；`null` = 抹掉那把键（模拟换代前冻结的存量报告）。 */
  const stamp = (lc: LivingCircleReport, ev: string | null, cov: string | null) => {
    const cal = { ...(lc.caliber ?? {}) } as Record<string, unknown>
    if (ev === null) delete cal.scope_policy_version
    else cal.scope_policy_version = ev
    if (cov === null) delete cal.coverage_caliber_version
    else cal.coverage_caliber_version = cov
    return { ...lc, caliber: cal } as LivingCircleReport
  }
  const rowsOf = (a: LivingCircleReport, b: LivingCircleReport) =>
    Object.fromEntries(compareRows(a, b, 'A', 'B').map((r) => [r.metric, r]))

  it('前端常量与契约夹具逐字相同（第二根轴：版本 / 两句结论 / 陈旧句），且三句互不相同', () => {
    expect(COVERAGE_CALIBER_VERSION).toBe(GAP.coverage_version_current)
    expect(COVERAGE_GAP_DESC).toBe(GAP.coverage_desc)
    expect(BOTH_GAP_DESC).toBe(GAP.both_desc)
    expect(staleCoverageCaliberNotice(stamp(KAILI, EV, null))).toBe(GAP.coverage_stale_notice)
    // 三句若写成同一句，就等于只有一根轴在守 ⇒ 当场红
    expect(new Set([GAP.desc, GAP.coverage_desc, GAP.both_desc]).size).toBe(3)
    expect(GAP.coverage_desc).not.toContain('判盲')
    expect(GAP.desc).not.toContain('评分口径')
    // 出厂两份演示件的评分轴现值：两边都是当前版本 ⇒ 第二句在这对上**永不**出现
    // （所以上面那些用例必须自己造差值，不能指望演示对）
    expect(coverageCaliberVersionOf(KAILI)).toBe(COV)
    expect(coverageCaliberVersionOf(JINSONG)).toBe(COV)
  })

  it('措辞由轴子句按表组合而成：加一根轴只加一行，不新增子集常量', () => {
    // ① 轴清单与顺序必须与契约夹具一致（顺序是用户可见的词序）
    expect(CALIBER_AXES.map((s) => s.axis)).toEqual(GAP.axes)
    expect(Object.keys(GAP.axis_fields).sort()).toEqual([...GAP.axes].sort())

    // ② 单轴结论句 ＝ 前缀 + 该轴子句，逐字；多轴句必须含全部子句
    for (const { axis, clause } of CALIBER_AXES) {
      expect(gapDescFor([axis])).toBe(`不可比 · ${clause}`)
      expect(GAP.both_desc).toContain(clause)
    }
    // ③ 零根轴不同 ⇒ null，不许拼出一句「不可比 · 」的空话
    expect(gapDescFor([])).toBeNull()
    // ④ 词序由表归一：调用方传反序也必须得同一句（否则两个页面会拼出两种词）
    expect(gapDescFor(['cov', 'ev'])).toBe(gapDescFor(['ev', 'cov']))
    expect(gapDescFor(['cov', 'ev'])).toBe(BOTH_GAP_DESC)
  })

  it('只有评分轴不同（判盲轴两边相同）⇒ 只拦评分轴管得着的行，盲区行照常', () => {
    for (const covB of [null, 'cov-0']) {
      const a = stamp(KAILI, EV, COV)
      const b = stamp(JINSONG, EV, covB)
      expect(caliberPolicyGap(a, b), '前提不成立：判盲轴本该相同').toBe(false)
      expect(coverageCaliberGap(a, b), `cov=${covB ?? '未声明'} 被判成同口径`).toBe(true)
      expect(caliberGapDesc(a, b)).toBe(COVERAGE_GAP_DESC)
      const rows = rowsOf(a, b)
      // 参照：同一对样本、评分轴抹平 ⇒ 盲区行的结论必须**一字不变**（#83）。
      // 不写死期望串，是因为它该等于 `compareDesc` 直出的那句 —— 而那句由行定义决定。
      const plain = rowsOf(a, stamp(JINSONG, EV, COV))
      for (const key of GAP.coverage_applies_to) {
        expect(rows[key].desc, `${key} 必须标注评分口径不可比`).toBe(COVERAGE_GAP_DESC)
      }
      for (const key of GAP.applies_to) {
        if (GAP.coverage_applies_to.includes(key)) continue
        expect(plain[key].desc, '参照本身就被拦了 ⇒ 下面那条相等断言会恒真').not.toBe(
          COVERAGE_GAP_DESC,
        )
        expect(plain[key].desc).not.toBe(CALIBER_GAP_DESC)
        expect(rows[key].desc, `${key}：评分轴不同，却改写了判盲轴才管得着的行`).toBe(
          plain[key].desc,
        )
      }
      for (const key of ['15min 等时圈面积 (km²)', '可达采样点数', 'POI 采集', '圈内 POI']) {
        expect(rows[key].desc).not.toBe(COVERAGE_GAP_DESC)
      }
      // 拦的是结论句不是数值：与"不拦"时逐字节相同
      for (const key of GAP.applies_to) {
        expect([rows[key].a_value, rows[key].b_value]).toEqual([plain[key].a_value, plain[key].b_value])
      }
      // 横幅也要说话（页面调的是清单那颗），且不许借用判盲那三个字
      const notices = compareCaliberNotices(a, b)
      expect(notices.map((n) => n.replace(/\s/g, '')).join('')).toContain('评分口径')
      for (const n of notices) expect(n).not.toContain('判盲')
    }
  })

  it('两根轴同时不同 ⇒ 评分行拿第三句、盲区行仍拿判盲句（不许两行共用一句）', () => {
    const a = stamp(KAILI, EV, COV)
    const b = stamp(JINSONG, 'ev-0-legacy', null)
    expect(caliberGapDesc(a, b)).toBe(BOTH_GAP_DESC)
    const rows = rowsOf(a, b)
    for (const key of GAP.coverage_applies_to) {
      expect(rows[key].desc).toBe(BOTH_GAP_DESC)
    }
    for (const key of GAP.applies_to) {
      if (GAP.coverage_applies_to.includes(key)) continue
      expect(rows[key].desc, `${key} 被第三句拦下 = 把评分账记到了判盲头上`).toBe(CALIBER_GAP_DESC)
    }
    expect(rows['服务盲区'].desc).not.toBe(rows['综合评分'].desc)
    // 单轴那两支必须各自仍可达到（否则第三句是吞掉前两句而不是并列）
    expect(caliberGapDesc(stamp(KAILI, EV, COV), stamp(JINSONG, 'ev-0-legacy', COV))).toBe(CALIBER_GAP_DESC)
    expect(caliberGapDesc(stamp(KAILI, EV, COV), stamp(JINSONG, EV, null))).toBe(COVERAGE_GAP_DESC)
    expect(caliberGapDesc(stamp(KAILI, EV, COV), stamp(JINSONG, EV, COV))).toBeNull()
  })

  it('两份都缺 cov 键 ⇒ 彼此可比（不得谎报不可比），但陈旧提示各要报出来', () => {
    const a = stamp(KAILI, EV, null)
    const b = stamp(JINSONG, EV, null)
    expect(coverageCaliberGap(a, b)).toBe(false)
    expect(caliberGapDesc(a, b)).toBeNull()
    const rows = rowsOf(a, b)
    for (const key of GAP.applies_to) {
      expect(rows[key].desc).not.toBe(COVERAGE_GAP_DESC)
    }
    // 都出自换代前 ⇒ 横幅也要报"都旧"（只拦不同不报都旧 = 两个被高估的分数并排）
    expect(compareCaliberNotices(a, b).join('')).toContain('都出自评分口径换代前')
    // 两轴都旧 ⇒ 横幅必须**两句都在**（只报一句 = 同屏两处披露各说一半，表格那格会写着两句）
    const bothAxesOld = [stamp(KAILI, null, null), stamp(JINSONG, null, null)] as const
    const banner = compareCaliberNotices(bothAxesOld[0], bothAxesOld[1])
    expect(banner).toHaveLength(2)
    expect(banner[0]).toContain('判盲')
    expect(banner[1]).toContain('评分口径')
    // 读侧同理：两份单份看都要各说一句，且两轴都旧 ⇒ 清单里两句都在
    const bothOld = stamp(KAILI, null, null)
    const notices = staleCaliberNotices(bothOld)
    expect(notices).toHaveLength(2)
    expect(notices[0]).toContain('判盲口径已升级')
    expect(notices[1]).toContain('评分口径已升级')
    expect(staleCaliberNotices(stamp(KAILI, EV, COV))).toHaveLength(0)
  })
})

describe('降档徽标与置信度安全取值', () => {
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

import { describe, it, expect } from 'vitest'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

/* 证据域图层 v7.2 · 子类口径的前端侧判据（计划 §14.3 的 T11 / T12 / T13）。

 * 三件事各拦一种漂移：
 *  T11（今日即绿）8 类键集合**不许被这次改造带偏**，且词表闸本身必须在"活着"的状态
 *      —— 它带 `existsSync` + `it.skip` 兜底（`lcCatLabel.contract.test.ts:18-21`），
 *      目标模块一旦缺失就整组静默变绿。判据失去活入口 = 没有判据，所以要单独钉一条。
 *  T12（it.fails）旧快照缺"评分口径版本"新键 ⇒ 既不崩、也不得挂新口径文案。
 *  T13（it.fails）维度旁那句门槛说明里的数字必须来自 payload，不是字面量。
 *
 * 为什么用 `it.fails` 而不是 `it.skip`：skip 在实现落地时**不发信号**（悄悄开始跑），
 * `it.fails` 在实现落地时会"意外通过"⇒ 当场报错 ⇒ 强制摘标。
 * 与后端 `test_subkind_caliber.py` 的 `xfail(strict=True)` 同一套纪律。
 *
 * ⚠️ 已知局限（不许拿它当"已覆盖"）：T12/T13 今天失败的原因是**符号还不存在**，
 *    不是"实现有 bug"。落地时必须逐条复核它失败的理由换没换对。
 */

const LBL = fileURLToPath(new URL('./lcCatLabel.ts', import.meta.url))
const LIB = fileURLToPath(new URL('./livingCircle.ts', import.meta.url))

const EIGHT_KEYS = ['market', 'medical', 'education', 'shopping',
  'elderly', 'finance', 'recreation', 'service']

describe('v7.2 · 8 类键集合与词表闸的活性', () => {
  it('T11a · 词表闸此刻**不处于** skip 兜底分支（判据要有活入口）', () => {
    expect(existsSync(LBL), 'lcCatLabel.ts 不在 ⇒ 词表闸走 it.skip 分支，8 键无人守').toBe(true)
    expect(existsSync(LIB)).toBe(true)
  })

  it('T11b · 本批不动 8 类键集合（拆第 9 类的 v6 方案已作废）', async () => {
    const { LC_CAT_LABEL } = await import('./lcCatLabel')
    expect(Object.keys(LC_CAT_LABEL)).toHaveLength(8)
    expect(Object.keys(LC_CAT_LABEL).sort()).toEqual([...EIGHT_KEYS].sort())
  })
})

describe('v7.2 · 评分口径版本键的前端回退臂', () => {
  it.fails('T12 · 缺新键的旧快照：不崩、且不挂"新口径"文案', async () => {
    const lib = await import('./livingCircle')
    // 旧产物：只有判盲版本，没有评分口径版本
    const legacy = {
      data_origin: 'live',
      caliber: { scope_policy_version: 'ev-2' },
      scores: { total: 68.8, confidence: 'limited' },
    } as any
    const notice = lib.staleCaliberNotice(legacy)
    expect(typeof notice).toBe('string')
    // 新键缺席 ⇒ 必须按"旧评分口径"解释，不得声称本报告已是门槛项口径
    expect(String(notice)).not.toMatch(/门槛项|按小学/)
    // 同时必须**认得出**这是旧评分口径（否则新旧报告读起来一模一样）
    expect(String(notice)).toMatch(/评分口径/)
  })

  it.fails('T13 · 维度旁说明里的数字必须来自 payload，不是写死的字面量', async () => {
    const lib = await import('./livingCircle')
    const fn = (lib as any).lcCategoryCaliberNote
    expect(typeof fn).toBe('function')
    const cat = { category: 'education', label: '教育', in_circle: 18, coverage: 0.6667,
      required_in_circle: 2, ideal_circle: 3 }
    const a = fn(cat)
    // 换一个 payload 数字 ⇒ 文案必须跟着变（钉字面量的文案过不了这条）
    const b = fn({ ...cat, required_in_circle: 1 })
    expect(a).not.toBe(b)
    expect(String(a)).toContain('2')
    expect(String(b)).toContain('1')
  })
})

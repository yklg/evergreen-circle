import { describe, it, expect } from 'vitest'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { FacilityCategoryStat, LivingCircleReport, PoiPoint } from '../types'

/* 证据域图层 v7.2 · 子类口径的前端侧判据（计划 §14.3 的 T11 / T12 / T13 + §5.1 第 9 行）。

 * 四件事各拦一种漂移：
 *  T11a（今日即绿）词表闸**不处于 skip 兜底分支** —— 它带 `existsSync` + `it.skip`
 *       （`lcCatLabel.contract.test.ts:18-21`），目标模块一缺就整组静默变绿 ⇒ 判据失去活入口。
 *  T11b（今日即绿）8 类键集合**不许被这次改造带偏**（拆第 9 类的 v6 方案已作废）。
 *  T11c（今日即绿）`cov-1` 的新键**真的在演示数据里**，且**退役桩值不得回流** —— 这是中-12 的
 *       机器形态：`total: 68.8`、`coverage: 0.6667`、`required_in_circle: 2` 是 §一 已判作废的数，
 *       此前以"预期读数"的形状留在本文件的桩里。现在本文件的输入**全部从真夹具现取**，
 *       那几个字面量只出现在"它不得再出现"的断言里。
 *  T12 （it.fails）旧快照缺"评分口径版本"新键 ⇒ 既不崩、也不得挂新口径文案。
 *  T13 （it.fails）维度旁那句门槛说明里的数字必须来自 payload，不是字面量。
 *
 * 为什么用 `it.fails` 而不是 `it.skip`：skip 在实现落地时**不发信号**（悄悄开始跑），
 * `it.fails` 在实现落地时会"意外通过"⇒ 当场报错 ⇒ 强制摘标。
 * 与后端 `test_subkind_caliber.py` 的 `xfail(strict=True)` 同一套纪律。
 *
 * ⚠️ 摘标记录（10-01 片 1c-β，用户确认预览后落地）：T12/T13 两条 `it.fails` 已转正常用例。
 *    换因**逐条核过**——它们当初红的理由是"读侧文案没接第二根轴"（`staleCaliberNotice` 只比
 *    `scope_policy_version` 一把 = 第十八轮 高-11；`lcCategoryCaliberNote` 未实现、页面零消费点），
 *    今天这两件事都不成立：`livingCircle.ts` 有 `COVERAGE_CALIBER_VERSION`/`staleCoverageCaliberNotice`/
 *    `staleCaliberNotices`，`lcCategoryCaliberNote` 由真组件 `CategoryCaliberNotes` 挂在报告页与体检台
 *    的雷达正下方，名单走后端新发的 `poi.categories[].scored_as`（甲档，用户 10-01 拍）。
 *    ⚠️ 摘标时改写过 T12 的一条断言（`not.toMatch(/门槛项|按小学/)` ⇒ 换成两条真测得住的），
 *    理由与两条新断言都写在那条用例里，不是放宽。
 */

const LBL = fileURLToPath(new URL('./lcCatLabel.ts', import.meta.url))
const LIB = fileURLToPath(new URL('./livingCircle.ts', import.meta.url))

const EIGHT_KEYS = ['market', 'medical', 'education', 'shopping',
  'elderly', 'finance', 'recreation', 'service']

// 输入全部现取，不再手拼载荷（中-12 的根因就是"我替实现预填了三个数"）
const LC = kaili as unknown as LivingCircleReport
const CATS: FacilityCategoryStat[] = LC.poi.categories
const POINTS: PoiPoint[] = LC.poi.points
const TOTAL: number = LC.scores.total
const EDU = CATS.find((c) => c.category === 'education') as FacilityCategoryStat
const FIN = CATS.find((c) => c.category === 'finance') as FacilityCategoryStat

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

  it('T11c · cov-1 的键在演示数据里为真，且退役桩值不得回流', () => {
    // 点位**无条件带键**（没建子类表的类别值为 null）⇒ 有缺席的就说明这份夹具不是新链路产物
    const missing = POINTS.filter((p) => !('sub_kind' in p))
    expect(missing, `${missing.length} 颗点位没有 sub_kind 键 ⇒ 夹具不是 cov-1 产物`).toHaveLength(0)
    // 三档语义各有真值（后端 T20 钉同一件事的生产侧；两侧不同源就会在这里分叉）
    expect('required_in_circle' in EDU).toBe(true)
    expect(EDU.required_in_circle).toBeTypeOf('number')
    expect(EDU.required_in_circle as number).toBeGreaterThan(0)
    expect(EDU.required_in_circle as number).toBeLessThanOrEqual(EDU.in_circle)
    // 没建子类表的类别**必须**是 null，不得印成 0（"0 个门槛项"是一句假话）
    expect(FIN.required_in_circle ?? null).toBeNull()
    // 中-12 的机器账：这三个字面量从未被任何一次实算产出过 ⇒ 它们不得是演示数据的样子
    expect(EDU.coverage, '教育 coverage 回到 0.6667 ⇒ 桩值那套数又活了').not.toBeCloseTo(0.6667, 3)
    expect(EDU.required_in_circle ?? -1).not.toBe(2)
    expect(TOTAL, '总分回到 68.8 ⇒ 那个数从来没被任何一次实算产出过').not.toBeCloseTo(68.8, 5)
    // 现取读数（10-01 回填后的真值；写在这里是为了"到底改动了什么"能被一眼读出）
    expect(EDU.coverage).toBeCloseTo(0.3333, 4)
    expect(TOTAL).toBeCloseTo(65.4, 1)
  })
})

describe('v7.2 · 评分口径版本键的前端回退臂', () => {
  it('T12 · 缺新键的旧快照：不崩、且不挂"新口径"文案（第二根轴已接上，10-01 片 1c-β）', async () => {
    const lib = await import('./livingCircle')
    // 载荷从**真夹具**现取。夹具已带这把键（§六 已拍板：进载荷 + 进复用门 + 进口径名册，
    // **不进**契约门禁 B 系列），所以这里要**故意删掉**它才构造得出旧快照形状。
    const legacy = structuredClone(LC) as unknown as Record<string, unknown>
    const caliber = (legacy.caliber ?? {}) as Record<string, unknown>
    delete caliber.coverage_caliber_version
    legacy.caliber = caliber
    legacy.data_origin = 'live'
    const lc = legacy as unknown as Parameters<typeof lib.staleCaliberNotices>[0]
    const notices = lib.staleCaliberNotices(lc)
    expect(notices.length, '旧快照必须至少有一句陈旧提示').toBeGreaterThan(0)
    const cov = lib.staleCoverageCaliberNotice(lc)
    expect(typeof cov).toBe('string')
    // R22-3（第 22 轮）：这条才是"清单真的接上了第二根轴"的钉子。原先只断 `notices.length > 0`，
    // 而前端这份 kaili 夹具**本来就没有** `scope_policy_version`（实测 grep 命中 0）⇒ 判盲那一句
    // 独立就满足 length>0，评分句没被收进清单也照样绿。`compareDiffContract.test.ts` 里那一条
    // 吃的是自造载荷，替不了这份"从真夹具删键"的判定。
    expect(notices, '评分轴那句没被收进清单 ⇒ 报告页只报判盲那半，两把键互相顶替又回来了').toContain(cov)
    // 缺键 ⇒ 说的是"这份按点数"，且**不猜**版本号（载荷里从来没有过任何 cov 串）
    expect(String(cov)).toContain('本报告按圈内点数计分')
    expect(String(cov)).not.toMatch(/cov-\d/)
    // ⚠️ 摘标时改过的一条断言（记录在此，免得下轮以为我放宽了）：原写法是
    // `not.toMatch(/门槛项|按小学/)`，意图"不得声称这份已是门槛项口径"。落地那句里
    // "门槛项"三个字**必然**出现（它说的是"当前按门槛项数计分"，主语是当下不是这份），
    // 所以那条正则测的是词而不是事 ⇒ 换成两条真测得住的：上面那两条 + 下面这条带号分支。
    expect(cov).not.toBe(lib.staleCoverageCaliberNotice(
      { caliber: { coverage_caliber_version: 'cov-0' } } as never,
    ))
    // 值不同的那一支：必须报出报告自己那个号（否则新旧读起来一模一样）
    const foreign = lib.staleCoverageCaliberNotice(
      { caliber: { coverage_caliber_version: 'cov-0' } } as never,
    )
    expect(String(foreign)).toContain('cov-0')
    expect(String(foreign)).toContain(lib.COVERAGE_CALIBER_VERSION)
    // 判盲那句**逐字不动**：删掉 cov 键不得改变 ev 那句（两轴各管各的），而评分句里不许出现
    // "判盲"三字（§六 禁止两把键互相顶替）。
    expect(lib.staleCaliberNotice(lc)).toBe(lib.staleCaliberNotice(LC))
    expect(String(cov)).not.toContain('判盲')
    expect(String(lib.staleCaliberNotice(lc))).not.toContain('评分口径')
  })

  it('T13 · 类别旁那句里的数字与名单都必须来自 payload，不是写死的字面量', async () => {
    const lib = await import('./livingCircle')
    const fn = lib.lcCategoryCaliberNote
    expect(typeof fn).toBe('function')
    const required = EDU.required_in_circle as number
    const a = fn(EDU)
    expect(typeof a).toBe('string')
    // 反向对照①：只改分子一个数 ⇒ 文案必须跟着变（钉字面量的文案过不了这一条）
    const b = fn({ ...EDU, required_in_circle: required + 1 })
    expect(a).not.toBe(b)
    expect(String(a)).toContain(String(required))
    expect(String(b)).toContain(String(required + 1))
    // 反向对照②：只改名单 ⇒ 也必须跟着变（钉"小学"这两个字的文案过不了这一条）
    const c = fn({ ...EDU, scored_as: ['完全不像小学的假名字'] })
    expect(c).not.toBe(a)
    expect(String(c)).toContain('完全不像小学的假名字')
    expect(String(a)).toContain((EDU.scored_as as string[])[0])
    // 三档语义：没建表的类别 ⇒ null（不得印成"0 处计入"），名单缺键 ⇒ null（不得前端凑）
    expect(fn(FIN)).toBeNull()
    expect(fn({ ...EDU, scored_as: undefined })).toBeNull()
    expect(fn({ ...EDU, scored_as: null })).toBeNull()
    expect(fn({ ...EDU, required_in_circle: null })).toBeNull()
  })
})

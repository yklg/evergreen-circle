// @vitest-environment jsdom
/**
 * 「未评」不能变成 0 分（附录 G-07，D9 / U1，TC-08 前端半 + TC-09）。
 *
 * 为什么这是渲染层问题而不是类型问题：`scores` / `blindspots` 在 `types.ts` 里是
 * **必填非空**，所以「本档未评」今天**没有合法表示**。项目里唯一贴近的先例走的是
 * 另一条路 —— 列表层 `total_score: number | null`（`types.ts` 注释自陈「离线报告存 null，
 * 不伪造 0 分」），而**正文层**的离线报告 `scores.total` 被既有契约钉成 `0`
 * （`livingCircleContract.test.ts` F2：`expect(r.scores.total).toBe(0)`）。
 * ⇒ 同一个「未评」在两层是两种值。游客档若沿用正文层这套，任何一个新消费点
 *    读 `scores.total` 都会拿到 0，UI 上就是一份「这个景点 0 分」的报告。
 *
 * 本文件三件事：
 *  ① 把**消费点全集**扫出来钉成基线（D9 说"五处消费点是本计划最大回归面"，
 *     先把"五处"变成机器可数的清单，而不是口头数）；
 *     ⚠️ 10-01 片 1c-β 起，扫描面**按文件名形状排除 `*.test.ts(x)`**：测试文件读分数只是钉夹具
 *     读数，没有「未评」分支可处理；豁免的自证见新加的那条用例（负半=真命中过、正半=6 个生产点没少）。
 *  ② 记录 `types.ts` 现状（必填非空 ⇒ 缺口），落地后转红并提示重指；
 *  ③ 用 `it.fails` 登记「scores=null 渲染未评」——转绿时不摘标记会主动报失败，
 *     等价于后端的 `xfail(strict=True)`。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ReportPage from '../pages/ReportPage'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'

const SRC = join(process.cwd(), 'src')

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({
    current: (globalThis as Record<string, any>).__HOLDER__.report,
    loading: false,
    error: null,
    load: vi.fn(),
  }),
}))

vi.mock('../lib/api', () => ({
  refineSection: vi.fn(),
  submitFeedback: vi.fn(),
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
}))

vi.mock('../components/VChart', () => ({
  VChart: ({ spec }: { spec: { title?: string } }) => <div data-testid="mock-chart">{spec?.title ?? 'chart'}</div>,
}))

function walk(dir: string, includeTests = false): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__tests__') continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p, includeTests))
    else if (/\.(ts|tsx)$/.test(name) && (includeTests || !isTestFile(name))) out.push(p)
  }
  return out
}

/**
 * 测试文件不是**发布面上的**消费点：它读 `scores.total` 只是钉夹具读数，没有「未评」分支要处理。
 * 10-01 片 1c-β 由棘轮当场拦出（`src/lib/lcSubKindCaliber.contract.test.ts` 被算成新增消费点），
 * 用户拍板改守卫边界而不是往 BASELINE 加条目、也不是把文件搬进 `__tests__`（那条等于用摆放位置收窄）。
 * 只按**文件名形状**豁免：`src/dev/` 探针照旧计入（09-30 那次它就是真消费点，走的是委托 `lib/livingCircle`）。
 */
function isTestFile(name: string): boolean {
  return /\.test\.tsx?$/.test(name)
}

/** 读 `scores.total` 的消费点（`scores.total` / `scores?.total` / `scores!.total`）。 */
function scoresConsumers(): string[] {
  const hits: string[] = []
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf-8')
    if (/scores\??!?\.(radar|bars|triads|total)/.test(text)) {
      hits.push(file.slice(SRC.length + 1))
    }
  }
  return hits.sort()
}

/* ── ① 消费点全集：D9 的"五处消费点"必须是机器可数的 ── */
describe('未评状态的消费点清单（回归面棘轮）', () => {
  /**
   * 基线 = 本次实测扫描结果（2026-09-26），**与计划 D9 列举的"五处消费点"不一致**：
   * `LcMap` 与 `ReportPage` 其实**不读 `scores`**（LcMap 只吃 report 的几何段，
   * ReportPage 分发给了视图），真正读分数的是这 6 个文件。
   * ⇒ D9 的回归面清单必须按本表重数（已写回计划附录 C-8）。
   */
  const BASELINE = [
    'components/lifecircle/LifeCircleReportView.tsx',
    'components/lifecircle/MiniRadar.tsx',
    'lib/livingCircle.ts',
    'mocks/livingCircleReports.ts',
    'pages/ComparePage.tsx',
    'pages/LifeCirclePage.tsx',
  ]

  it('消费点集合与基线一致（多一处少一处都要显式处理）', () => {
    const found = scoresConsumers()
    const extra = found.filter((f) => !BASELINE.includes(f))
    const gone = BASELINE.filter((f) => !found.includes(f))
    expect(
      { extra, gone },
      `分数消费点变了：新增 ${extra.join(', ') || '无'}；消失 ${gone.join(', ') || '无'}。` +
        '新增 ⇒ 该处必须一并处理"未评"分支；消失 ⇒ 基线须收紧（不得放宽成"随它去"）。',
    ).toEqual({ extra: [], gone: [] })
  })

  /**
   * 豁免**必须自证**（记忆「自写守卫脚本要先自证」/「改判据本身要补两条证据」）：
   * 光看上面那条转绿分不清"边界修对了"和"我把那条断言顺手放宽了"。
   * 所以这里同时钉两面 —— 负半（测试文件真被挡，且它原本确实命中）+ 正半（6 个生产消费点一个没少）。
   * ⚠️ 不做写盘变异：造临时文件落进 `src/` 万一崩在半路会留残留被提交，改拿真夹具文件做正半对照。
   */
  it('测试文件豁免是按文件名形状生效的，不是那批文件本来就没读分数', () => {
    const OUTLIER = 'lib/lcSubKindCaliber.contract.test.ts'
    const SCORES_RE = /scores\??!?\.(radar|bars|triads|total)/

    // 负半之第一行：这个测试文件**真的**在读分数 ⇒ 下面的"不在清单里"不是恒真
    const raw = readFileSync(join(SRC, OUTLIER), 'utf-8')
    expect(SCORES_RE.test(raw), `${OUTLIER} 已不读 scores ⇒ 豁免是否还生效无人验`).toBe(true)
    expect(isTestFile(OUTLIER)).toBe(true)
    expect(scoresConsumers(), '测试文件仍被算进消费点 ⇒ 豁免没落地').not.toContain(OUTLIER)

    // 负半之规模自报：扫描面外那批测试文件里，本次豁免的净作用面到底有几个
    const testFiles = walk(SRC, true).filter((f) => isTestFile(f.slice(SRC.length + 1)))
    const testHits = testFiles
      .filter((f) => SCORES_RE.test(readFileSync(f, 'utf-8')))
      .map((f) => f.slice(SRC.length + 1))
      .sort()
    expect(testHits, `豁免挡掉的不止一个已知文件（${testHits.join(', ')}）⇒ 作用面变了，须重数`).toEqual([OUTLIER])

    // R22-6：`tsx` 那一支**没有见证文件** —— `src/` 下 `__tests__` 外的 10 个测试文件全是 `.ts`，
    // 所以上面三条端到端判据钉不住它：把正则写成 `\.test\.ts$`，三条全绿而豁免面静默少一档。
    // 这里按**形状**各钉一次，并顺带钉住那个不对称（R22 的 P2）：`walk` 传 basename、
    // 自证传相对路径，今天靠 `$` 锚定才等价 —— 去掉锚定两边就会分叉，这条会当场红。
    for (const base of ['Cell.test.tsx', 'Cell.test.ts']) {
      expect(isTestFile(base), `${base} 那一支没被武装 ⇒ 取样面窄了一档`).toBe(true)
      expect(isTestFile(`components/lifecircle/${base}`), `带目录前缀的 ${base} 判不出 ⇒ 两种调用形状分叉`).toBe(true)
    }
    for (const base of ['ComparePage.tsx', 'livingCircle.ts', 'testHelpers.ts']) {
      expect(isTestFile(base)).toBe(false)
      expect(isTestFile(`lib/${base}`)).toBe(false)
    }

    // 正半：6 个生产消费点**不得**被 isTestFile 挡掉，且它们仍在扫描面上、仍命中
    const found = scoresConsumers()
    for (const f of BASELINE) {
      expect(isTestFile(f), `${f} 被当成测试文件豁免 ⇒ 生产面漏防`).toBe(false)
      expect(found, `${f} 不再被扫到 ⇒ 边界一收窄把真消费点也吞了`).toContain(f)
    }
  })
})

/* ── ② types.ts 现状：未评没有合法表示 ── */
describe('报告契约的「未评」表示（TC-08 前端半）', () => {
  const types = readFileSync(join(SRC, 'types.ts'), 'utf-8')

  it('现状记录：scores / blindspots 仍是必填非空 ⇒ 落地后本用例转红', () => {
    const nullable = /scores\??:\s*LifeCircleScores\s*\|\s*null/
    const stillRequired = /scores:\s*LifeCircleScores/
    expect(stillRequired.test(types) && !nullable.test(types)).toBe(true)
    // 一旦 D9 把类型升为 `… | null`，上面这行会变 false ⇒ 本用例转红，
    // 提示把它改成正向断言（nullable 必须成立），并删除下面的 it.fails。
  })
})

/* ── ③ 渲染：未评不得出 0 分（D9 的诚实条款，登记缺口） ── */
describe('未评报告的渲染（it.fails = 后端 xfail(strict) 的前端对应物）', () => {
  it.fails('scores=null 的体检页显示「未评」而不是 0 分', () => {
    const report = getLivingCircleReportMock('lc-kaili')!
    const unrated = {
      ...report,
      living_circle: { ...report.living_circle!, scores: null, blindspots: null },
    }
    ;(globalThis as Record<string, any>).__HOLDER__ = { report: unrated }
    render(
      <MemoryRouter initialEntries={['/report/lc-kaili']}>
        <Routes>
          <Route path="/report/:reportId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getAllByText(/未评/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/^0(\.\d)?\s*分$/)).toBeNull()
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

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

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__tests__') continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (/\.(ts|tsx)$/.test(name)) out.push(p)
  }
  return out
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

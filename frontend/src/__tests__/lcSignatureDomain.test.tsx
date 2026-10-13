// @vitest-environment jsdom
/**
 * 报告页署名的**域解析**判据（批 0′ 前端半）。
 *
 * 钉的是三件事，都对应本轮实测踩过的形状：
 * 1. 生活圈报告必须用**生活圈名册**解析 author（医疗章＝谷穗安·基层医疗配置顾问）；
 * 2. 同 id 在两域是不同人 ⇒ 交叉重名「温叙白」必须解析成生活圈 L3-001（社区体检总检），
 *    而不是旅游 L2-005（花费与性价比分析师）；
 * 3. 历史报告里烤死的旅游人名（本轮之前落库的 5 份）解析不到时，要**原样显示 + 通用职位**，
 *    绝不退回另一本人设去凑一个像样的职位 —— 宁可难看，不可错人。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const TRAVEL = [
  { id: 'L2-005', name: '温叙白', nickname: 'T5', level: 'L2', role_title: '花费与性价比分析师 / Cost Analyst', group: 'strategy' },
  { id: 'L2-001', name: '苏明哲', nickname: 'T6', level: 'L2', role_title: '行程策略专家 / Itinerary Strategist', group: 'strategy' },
]
const LIVING = [
  { id: 'L3-001', name: '温叙白', nickname: 'L1', level: 'L3', role_title: '社区体检总检 / Community Inspector', group: 'decision' },
  { id: 'L2-001', name: '谷穗安', nickname: 'L2', level: 'L2', role_title: '基层医疗配置顾问 / Primary-care Advisor', group: 'facility' },
]

vi.mock('../lib/api', () => ({
  fetchExperts: vi.fn(async (domain: string) => (domain === 'living_circle' ? LIVING : TRAVEL)),
  fetchLifeCircleUsage: vi.fn(async () => null),
}))

import { useExpertStore } from '../store/expertStore'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  useExpertStore.setState({ expertsByDomain: {}, loadedDomains: {}, loadingDomains: {} })
})

/** 造一份"章节已署名"的报告：只改 author，其余沿用样区 mock（避免为测试复制整份契约）。 */
function reportAuthored(sectionId: string, author: string) {
  const rep = structuredClone(getLivingCircleReportMock('lc-kaili')) as never as {
    sections: { id: string; claims: { author: string }[] }[]
  }
  const sec = rep.sections.find((s) => s.id === sectionId)
  if (!sec || !sec.claims?.length) throw new Error(`mock 报告缺章节 ${sectionId}（夹具变了，判据要跟着改）`)
  sec.claims.forEach((c) => (c.author = author))
  return rep as never
}

async function renderWith(author: string, sectionId = 'medical') {
  render(
    <MemoryRouter>
      <LifeCircleReportView report={reportAuthored(sectionId, author)} />
    </MemoryRouter>,
  )
  // 视图是挂载时异步 load('living_circle') 的，等名册到位再断言，否则测的是"未加载"态
  await waitFor(() => expect(useExpertStore.getState().loadedDomains.living_circle).toBe(true))
}

describe('生活圈报告署名解析域', () => {
  it('生活圈人名 → 生活圈职位（不是"规划专家"兜底）', async () => {
    await renderWith('谷穗安')
    expect(screen.getAllByText(/谷穗安 · 基层医疗配置顾问/).length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/谷穗安 · 规划专家/)).toHaveLength(0)
  })

  it('交叉重名「温叙白」按生活圈域解析为社区体检总检', async () => {
    await renderWith('温叙白', 'isochrone')
    expect(screen.getAllByText(/温叙白 · 社区体检总检/).length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/温叙白 · 花费与性价比分析师/)).toHaveLength(0)
  })

  it('历史报告里的旅游人名：原样显示 + 通用职位，不借另一本名册凑职位', async () => {
    await renderWith('苏明哲')
    expect(screen.getAllByText(/苏明哲 · 规划专家/).length).toBeGreaterThan(0)
  })

  it('本域名册没加载时不静默改用 travel 名册（顶层已无镜像槽）', async () => {
    useExpertStore.setState({
      expertsByDomain: { travel: TRAVEL as never },
      loadedDomains: { travel: true },
    })
    const rep = reportAuthored('medical', '谷穗安')
    render(
      <MemoryRouter>
        <LifeCircleReportView report={rep} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(useExpertStore.getState().loadedDomains.living_circle).toBe(true))
    const chips = screen.getAllByText(/谷穗安/)
    expect(chips.length).toBeGreaterThan(0)
    // 只有 travel 册在场时，绝不允许把「谷穗安」解析成旅游人设里的某个人
    expect(screen.queryAllByText(/谷穗安 · 行程策略专家/)).toHaveLength(0)
  })
})

/* ══ F5 · 生活圈视图不得伸手去要 travel 人设 ══
 *
 * 上面几条测的是"解析对不对"，这条测的是"有没有人把域写错"：两本名册共用同一套 48 个 id，
 * `resolve(id, 'travel')` 不会报错、不会 404，只会把「谷穗安·基层医疗配置顾问」静默换成
 * 「苏明哲·行程策略专家」—— 本批所有署名缺陷的成因就是这个形状。
 * 那 5 个 travel 渲染器（VAgentStream / VFlowDag / VTracePanel / VClaimCard / VDecisionReplay）
 * 内部硬写 `'travel'` 是它们的本职，所以扫描面**只圈生活圈侧文件**，不扫全仓。
 */
describe('F5 · 生活圈源码里不得出现取 travel 名册的调用', () => {
  const SRC = join(process.cwd(), 'src')
  const LC_DIR = join(SRC, 'components', 'lifecircle')
  const LC_FILES = new Set<string>([
    join(SRC, 'pages', 'LifeCirclePage.tsx'),
    join(SRC, 'lib', 'lifeCircleFlow.ts'),
    join(SRC, 'store', 'taskRegistry.ts'),
    ...readdirSync(LC_DIR).filter((f) => /\.tsx?$/.test(f)).map((f) => join(LC_DIR, f)),
  ])
  const TRAVEL_ARG = /,\s*'travel'\s*\)/

  it('扫描面真的覆盖到了生活圈侧（探针不空转）', () => {
    expect(LC_FILES.size, `生活圈侧只扫到 ${LC_FILES.size} 个文件`).toBeGreaterThanOrEqual(5)
    for (const f of LC_FILES) expect(existsSync(f), `扫描面里有文件不存在：${f}`).toBe(true)
    // 正则本身要有落点：travel 侧那 5 个渲染器里必须还能找到这种调用，
    // 否则"零命中"可能只是正则写错了。
    const hits = readdirSync(join(SRC, 'components'))
      .filter((f) => /^V.+\.tsx$/.test(f))
      .some((f) => TRAVEL_ARG.test(readFileSync(join(SRC, 'components', f), 'utf-8')))
    expect(hits, "`, 'travel')` 形状在 travel 渲染器里也扫不到 ⇒ 这条正则已失效").toBe(true)
  })

  it('生活圈侧没有任何一处按 travel 域取名册', () => {
    const offenders: string[] = []
    for (const f of LC_FILES) {
      const lines = readFileSync(f, 'utf-8').split('\n')
      lines.forEach((line, i) => {
        if (TRAVEL_ARG.test(line)) offenders.push(`${f.split('/src/')[1]}:${i + 1}  ${line.trim()}`)
      })
    }
    expect(offenders, `生活圈侧出现 travel 域取数（同 id 不同人，不会报错只会换人）：\n${offenders.join('\n')}`).toEqual([])
  })
})

/* ══ C5 · 章页脚「本章署名：」不得悬空，也不得留空边框条 ══
 *
 * 后端按"无证据不立论"产 claims ⇒ 没有可签名结论的章就是空数组。五份演示件逐章实读：
 * 每份都有 2–3 章 claims 为空（含概览章与盲区章），而旧代码把标签**无条件**渲染，
 * 于是屏上出现一行后面什么都没有的「本章署名：」。这里钉三层，缺一层就是半成品：
 * ① 标签与 claims 同现；② chip 在标签之后；③ claims 与证据**皆空**时整个页脚容器不渲染
 * —— 只门控标签会留下一条 `border-t pt-3` 的空横条（同一处页脚里还装着"证据 N 条"芯片）。
 * 三分支刻意**改夹具现造**而不是赌演示件里的真实值：数据面一变，判据不该跟着变红。
 */
describe('章页脚署名与证据的同现门控（C5）', () => {
  type Claim = { claim_id: string; author: string; text?: string; cross_validated?: boolean }
  type Sec = { id: string; claims?: Claim[]; source_evidence_ids?: string[] }

  function withFooter(claims: Claim[], evidence: string[]) {
    const rep = structuredClone(getLivingCircleReportMock('lc-kaili')) as never as { sections: Sec[] }
    const sec = rep.sections.find((s) => s.id === 'medical')
    if (!sec) throw new Error('mock 报告缺 medical 章（夹具变了，判据要跟着改）')
    sec.claims = claims
    sec.source_evidence_ids = evidence
    return rep as never
  }

  async function renderRep(rep: never) {
    const { container } = render(
      <MemoryRouter>
        <LifeCircleReportView report={rep} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(useExpertStore.getState().loadedDomains.living_circle).toBe(true))
    return container
  }

  /** 只问 medical 那一处页脚：整页文本里有别的章的「本章署名：」，拿整页断言会因错误原因通过。 */
  const footerOf = (c: HTMLElement, id: string) => c.querySelector<HTMLElement>(`[data-lc-chapter-footer="${id}"]`)

  it('claims 空、有证据 ⇒ 页脚留（证据芯片在），但"本章署名："不许出现', async () => {
    const f = footerOf(await renderRep(withFooter([], ['ev-1'])), 'medical')
    expect(f, '有证据时页脚容器该在').not.toBeNull()
    expect(f!.textContent).toContain('证据 1 条')
    expect(f!.textContent, 'claims 为空却仍印标签 ⇒ 标签与结论脱钩').not.toContain('本章署名')
  })

  it('claims 与证据皆空 ⇒ 整个页脚容器不渲染（挡掉那条空边框横条）', async () => {
    const c = await renderRep(withFooter([], []))
    expect(footerOf(c, 'medical'), '两样都没有却留着容器 ⇒ border-t 会画成一条空横条').toBeNull()
  })

  it('有 claims ⇒ 标签与 chip 同时在场（前两半的对照，防"整块被误删"当成修好了）', async () => {
    const c = await renderRep(withFooter([{ claim_id: 'c-x', author: '谷穗安', text: '一句结论' }], ['ev-1']))
    const f = footerOf(c, 'medical')
    expect(f).not.toBeNull()
    expect(f!.textContent).toContain('本章署名：')
    expect(f!.querySelectorAll('span.rounded-chip').length, '标签后必须有那枚署名 chip').toBeGreaterThan(0)
  })

  /* 整页不变式：标签出现 ⟺ 该章有 claims。
   * 上面三条各钉一个分支，这条钉"没有漏网的章"—— 五份演示件里每份都有 2–3 章 claims 为空，
   * 逐章手挑会有漏的一章；这条按渲染出来的页脚总数对账，数据面扩大也照样成立。 */
  it('整页对账：带「本章署名：」的页脚数 == 有 claims 的章数，且不含 claims 的章一枚不剩', async () => {
    const rep = structuredClone(getLivingCircleReportMock('lc-kaili')) as never as { sections: Sec[] }
    const c = await renderRep(rep as never)
    const footers = [...c.querySelectorAll<HTMLElement>('[data-lc-chapter-footer]')]
    const claimsIds = new Set(rep.sections.filter((s) => (s.claims?.length ?? 0) > 0).map((s) => s.id))
    const labeled = footers.filter((f) => f.textContent?.includes('本章署名')).map((f) => f.dataset.lcChapterFooter!)
    expect(footers.length, '页脚容器数应等于「有 claims 或有证据」的章数').toBe(
      rep.sections.filter((s) => (s.claims?.length ?? 0) > 0 || (s.source_evidence_ids?.length ?? 0) > 0).length,
    )
    expect(labeled.sort(), '标签集合必须与有 claims 的章集合一处不多、一处不少').toEqual([...claimsIds].sort())
  })
})

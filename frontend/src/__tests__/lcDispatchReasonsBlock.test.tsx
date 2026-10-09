// @vitest-environment jsdom
/**
 * 报告页「报告署名席位（N）」块（计划 F3 / F4 / TC-D2）。
 *
 * 三条判据各自防一种"看着对、其实抄了一份"的回归：
 *  - **数据源只能是 `report.dispatch`**。后端 `assemble_report` 已经把 ids×reasons 拼好，
 *    并且兜底句子只有一个实现；前端若自己 zip `lc.team.expert_ids × reasons`，那唯一实现
 *    就成了第二份（`_team_payload` 的注释记的血案正是"三份手写迟早再漂"）。
 *    ⇒ 用"只给 `lc.team`、不给 `dispatch`"的夹具来证伪：块必须不出现。
 *  - **缺件即不印**：`dispatch` 缺或空 ⇒ 整块不渲染。印一个「报告署名席位（0）」
 *    就是替一份没署名的报告举证。
 *  - **标题写"署名席位"不写"本次派出的 N 位"**：`dispatch` 是装配期的署名集合，
 *    可能与横幅那支编排期保底队人数不同（实测 13 vs 10），"派出"会被当场问住。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/** 名册桩成两份人设（与 `lcSignatureDomain.test.tsx` 同一族）：vitest 环境下没有真 fetch，
 *  视图挂载时那次 `load('living_circle')` 必须落到桩上，否则名册永不到位。
 *  走 `vi.hoisted` 而不是模块级 const —— `vi.mock` 的工厂会被提升到 import 之前求值。 */
const { LIVING } = vi.hoisted(() => ({
  LIVING: [
    { id: 'L3-001', name: '温叙白', nickname: 'L1', level: 'L3', role_title: '社区体检总检 / Community Inspector', group: 'decision' },
    { id: 'L2-001', name: '谷穗安', nickname: 'L2', level: 'L2', role_title: '基层医疗配置顾问 / Primary-care Advisor', group: 'facility' },
  ],
}))
vi.mock('../lib/api', () => ({
  fetchExperts: vi.fn(async (domain: string) => (domain === 'living_circle' ? LIVING : [])),
}))

import { useExpertStore } from '../store/expertStore'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { Report } from '../types'

const base = () => structuredClone(getLivingCircleReportMock('lc-kaili')) as unknown as Report

async function renderReport(rep: Report) {
  render(
    <MemoryRouter>
      <LifeCircleReportView report={rep} />
    </MemoryRouter>,
  )
  // 视图挂载时异步 load('living_circle')：等名册到位，否则测的是"未加载"态
  await waitFor(() => expect(useExpertStore.getState().loadedDomains.living_circle).toBe(true))
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  useExpertStore.setState({ expertsByDomain: {}, loadedDomains: {}, loadingDomains: {} })
})

describe('F3 · 数据源是 report.dispatch', () => {
  it('只给 lc.team（ids×reasons 都在），不给 dispatch ⇒ 块不出现', async () => {
    const rep = base()
    const teamIds = (rep.dispatch ?? []).map((d) => d.id)
    rep.dispatch = []
    const lc = rep.living_circle as { team?: { expert_ids?: string[]; reasons?: string[] } }
    lc.team = { expert_ids: teamIds, reasons: teamIds.map(() => '这句只该出现在 lc.team 里') }
    await renderReport(rep)
    expect(screen.queryByText(/报告署名席位/)).toBeNull()
    expect(screen.queryByText(/这句只该出现在 lc\.team 里/)).toBeNull()
  })

  /** 上面那条只钉住"门控读 dispatch"；这一条钉"逐行内容也读 dispatch"。
   *  少了它，`rows={lc.team.expert_ids × reasons}` 这种改法可以整批溜过去 —— 实测变异 N10
   *  就是这么活的：门控仍看 dispatch.length，所以第一条照样绿。 */
  it('两处都给、内容不同 ⇒ 屏上必须是 dispatch 那一份（不自己 zip lc.team）', async () => {
    const rep = base()
    rep.dispatch = [{ id: 'L3-001', reason: '这一句来自 dispatch' }]
    const lc = rep.living_circle as { team?: { expert_ids?: string[]; reasons?: string[] } }
    lc.team = { expert_ids: ['L2-001', 'L3-002'], reasons: ['这一句来自 lc.team', '这句也是 lc.team'] }
    await renderReport(rep)
    expect(screen.getByText('这一句来自 dispatch')).toBeTruthy()
    expect(screen.queryByText(/这一句来自 lc\.team/)).toBeNull()
    expect(screen.queryByText(/这句也是 lc\.team/)).toBeNull()
    // 计数也只跟 dispatch 走：lc.team 有两位，标题必须是（1）
    expect(screen.getByText(/报告署名席位（1）/)).toBeTruthy()
  })

  it('dispatch 在 ⇒ 每行的理由**原样**上屏（前端不重排句子、不自己拼）', async () => {
    const rep = base()
    expect((rep.dispatch ?? []).length, '夹具变了：演示报告没有 dispatch，本判据会空转').toBeGreaterThan(0)
    await renderReport(rep)
    for (const d of rep.dispatch ?? []) {
      expect(screen.getAllByText(d.reason).length, `理由「${d.reason}」没上屏`).toBeGreaterThan(0)
    }
  })
})

describe('F4 · 计数、措辞与缺件门控', () => {
  it('标题是「报告署名席位（N）」，N ＝ dispatch 条数', async () => {
    const rep = base()
    await renderReport(rep)
    const n = (rep.dispatch ?? []).length
    expect(screen.getByText(new RegExp(`报告署名席位（${n}）`))).toBeTruthy()
  })

  it('措辞不得写成"本次派出"（装配期 13 人 vs 编排期 10 席，会被当场问住）', async () => {
    const rep = base()
    await renderReport(rep)
    expect(document.body.textContent).not.toMatch(/本次派出|派出的.*位专家/)
  })

  it('dispatch 为空数组 ⇒ 整块不渲染，也不出现「（0）」', async () => {
    const rep = base()
    rep.dispatch = []
    await renderReport(rep)
    // 判据只能限定在本块标题上：整页另有「服务盲区清单（0）」这类**合法的** 0，
    // 拿 /（0）/ 去数会把已存在的文案当成缺陷（第一版就是这么红的）。
    expect(screen.queryByText(/报告署名席位/)).toBeNull()
  })

  it('dispatch 整个缺席（旧报告）⇒ 同样不渲染且不抛', async () => {
    const rep = base()
    delete rep.dispatch
    await renderReport(rep)
    expect(screen.queryByText(/报告署名席位/)).toBeNull()
  })
})

describe('TC-D2 · 名册里没有这位席位', () => {
  it('印裸 id 且整页不崩（署名解析不许把缺陷遮成空白）', async () => {
    const rep = base()
    const rows = rep.dispatch ?? []
    expect(rows.length).toBeGreaterThan(0)
    rows[0] = { id: 'L9-999', reason: rows[0].reason }
    await renderReport(rep)
    expect(screen.getAllByText('L9-999').length, '查不到的席位必须以裸 id 可见').toBeGreaterThan(0)
    expect(screen.getByText(new RegExp(`报告署名席位（${rows.length}）`))).toBeTruthy()
  })
})

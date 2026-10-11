// @vitest-environment jsdom
/**
 * 演示态归档的删除 / 还原 —— 本机那个"所有者"真的接住了写操作。
 *
 * 这条专治用户报的原症状（实测复现过的形状）：演示态点删除 → 确认框关了 → 那一行又长回来。
 * 成因不是"少一个 `isFixtureMode()` 判断"，而是**演示归档状态这个概念在系统里没有归属处**：
 * 列表是每次重新派生的纯函数（`getLifeCircleRecords`），删除却打到真实 HTTP 端点，
 * 后端对 `lc-kaili` 这种合成 id 返回 200 + `deleted:false`，外壳又不看返回值 ⇒ 必然回弹。
 *
 * 所以这里钉的是四件事，缺一件都放行原症状：
 *  ① 演示态删除**不发**真实端点（发了就是打到不存在的地方）；
 *  ② 摘掉后**重挂/重进也不回来**（只在内存里减一次 = 刷新即复活）；
 *  ③ 一键还原真的把行放回去（否则删错只能去开控制台）；
 *  ④ 真实态 `deleted:false` 说成"本来就不在"，而不是当成功关掉确认框。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentType } from 'react'
import type { LifeCircleRecord } from '../types'

const mocks = vi.hoisted(() => ({
  fetchLifeCircleReports: vi.fn(),
  deleteLifeCircleReport: vi.fn(),
  deleteReport: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
  deleteLifeCircleReport: mocks.deleteLifeCircleReport,
  deleteReport: mocks.deleteReport,
  fetchIntel: vi.fn().mockResolvedValue(null),
  fetchEvidences: vi.fn().mockResolvedValue({ items: [], facets: {} }),
  fetchSubscriptions: vi.fn().mockResolvedValue([]),
  fetchWorkload: vi.fn().mockResolvedValue([]),
  createSubscription: vi.fn(),
}))

const LS_ARCHIVE = 'evergreen.demoArchive.v1'
const LS_MODE = 'evergreen.dataMode.v1'

/** 演示态内置列表里的真实行（id 取自 `getLifeCircleRecords`，不另造一套） */
const LC_TARGET = 'lc-kaili-ev2'

async function setMode(mode: 'fixture' | 'live') {
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode })
}

/** 只渲染这一屏的取数出口：列表口径归 hook 管，别把分组折叠的不确定性扯进判据 */
async function renderLedger(): Promise<void> {
  const { useLivingCircleRecords } = await import('../hooks/useLivingCircleRecords')
  const Probe = () => {
    const { data, loading } = useLivingCircleRecords(0)
    if (loading) return <div>loading</div>
    return (
      <ul>
        {(data ?? []).map((r) => (
          <li key={r.key} data-row={r.id}>
            {r.title}
          </li>
        ))}
      </ul>
    )
  }
  render(
    <MemoryRouter>
      <Probe />
    </MemoryRouter>,
  )
  await waitFor(() => expect(rowIds().length).toBeGreaterThan(0))
}

function rowIds(): string[] {
  return Array.from(document.querySelectorAll('[data-row]')).map((el) => el.getAttribute('data-row')!)
}

beforeEach(async () => {
  for (const fn of Object.values(mocks)) fn.mockReset?.()
  // 两处一起清：store 是模块级单例，只清 localStorage 的话上一个用例摘的行会渗进下一个用例，
  // 第一红会红在脚手架而不是红在产品逻辑
  const { resetDemoArchive } = await import('../store/demoArchiveStore')
  resetDemoArchive()
  localStorage.removeItem(LS_MODE)
  mocks.deleteLifeCircleReport.mockResolvedValue({ ok: true, deleted: true })
  mocks.deleteReport.mockResolvedValue({ ok: true })
  mocks.fetchLifeCircleReports.mockResolvedValue([])
})

afterEach(cleanup)

describe('演示态删除：本机归档是写操作的所有者', () => {
  it('摘掉一行 → 列表少一行，且一个真实删除请求都不发', async () => {
    await setMode('fixture')
    await renderLedger()
    const before = rowIds()
    expect(before).toContain(LC_TARGET)

    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const { getLifeCircleRecords } = await import('../mocks/livingCircleReports')
    const { livingCircleRows } = await import('../lib/recordIndex')
    const record = livingCircleRows(getLifeCircleRecords()).find((r) => r.id === LC_TARGET)!
    const outcome = await DOMAIN_VIEWS.living_circle.remove(record)

    expect(outcome.removed).toBe(true)
    expect(mocks.deleteLifeCircleReport, '演示态不该打真实端点（那上面没有这条 id）').not.toHaveBeenCalled()
    await waitFor(() => expect(rowIds()).not.toContain(LC_TARGET))
    expect(rowIds().length).toBe(before.length - 1)
  })

  it('重挂（卸载再进来）也不长回来 —— 只减一次内存等于刷新即复活', async () => {
    await setMode('fixture')
    await renderLedger()
    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const { getLifeCircleRecords } = await import('../mocks/livingCircleReports')
    const { livingCircleRows } = await import('../lib/recordIndex')
    const record = livingCircleRows(getLifeCircleRecords()).find((r) => r.id === LC_TARGET)!
    await DOMAIN_VIEWS.living_circle.remove(record)
    await waitFor(() => expect(rowIds()).not.toContain(LC_TARGET))
    cleanup()

    await renderLedger()
    expect(rowIds(), '重挂后那一行又回来了 ⇒ 摘除没落到持久介质').not.toContain(LC_TARGET)
    // 持久形状自证：不是只活在组件内存里
    const raw = JSON.parse(localStorage.getItem(LS_ARCHIVE) ?? '{}')
    expect(raw.schema).toBe('evergreen.demo-archive/v1')
    expect(Object.keys(raw.removed?.living_circle ?? {})).toEqual([LC_TARGET])
  })

  it('一键还原把行放回去，并清空这台机器上的摘除记录', async () => {
    await setMode('fixture')
    await renderLedger()
    const all = rowIds()
    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const { getLifeCircleRecords } = await import('../mocks/livingCircleReports')
    const { livingCircleRows } = await import('../lib/recordIndex')
    const record = livingCircleRows(getLifeCircleRecords()).find((r) => r.id === LC_TARGET)!
    await DOMAIN_VIEWS.living_circle.remove(record)
    await waitFor(() => expect(rowIds().length).toBe(all.length - 1))

    const { useDemoArchiveStore } = await import('../store/demoArchiveStore')
    const n = useDemoArchiveStore.getState().restoreAll('living_circle')
    expect(n).toBe(1)
    await waitFor(() => expect(rowIds()).toContain(LC_TARGET))
    const raw = JSON.parse(localStorage.getItem(LS_ARCHIVE) ?? '{}')
    expect(raw.removed?.living_circle, '还原后盘上还留着 tombstone ⇒ 下次进来又会少一行').toBeUndefined()
  })

  it('摘除记录按域隔离：动 travel 域不许让生活圈列表少一行', async () => {
    await setMode('fixture')
    await renderLedger()
    const before = rowIds()

    const { useDemoArchiveStore } = await import('../store/demoArchiveStore')
    useDemoArchiveStore.getState().drop({
      id: 'r-somewhere',
      domain: 'travel',
      title: '某次调研',
      checked_at: '2026-09-01T00:00:00Z',
    } as never)

    expect(rowIds()).toEqual(before)
    expect(Object.keys(useDemoArchiveStore.getState().doc.removed)).toEqual(['travel'])
  })

  it('重复摘同一行要说"已经摘过"，不许当第二次成功报（后端 deleted:false 同一族）', async () => {
    await setMode('fixture')
    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const { getLifeCircleRecords } = await import('../mocks/livingCircleReports')
    const { livingCircleRows } = await import('../lib/recordIndex')
    const record = livingCircleRows(getLifeCircleRecords()).find((r) => r.id === LC_TARGET)!
    expect((await DOMAIN_VIEWS.living_circle.remove(record)).removed).toBe(true)
    const again = await DOMAIN_VIEWS.living_circle.remove(record)
    expect(again.removed).toBe(false)
    expect(again.whyNot).toBeTruthy()
  })

  it('演示态的确认文案不许说"会再次消耗配额"，也不许说"不可撤销"', async () => {
    await setMode('fixture')
    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const { getLifeCircleRecords } = await import('../mocks/livingCircleReports')
    const { livingCircleRows } = await import('../lib/recordIndex')
    const record = livingCircleRows(getLifeCircleRecords()).find((r) => r.id === LC_TARGET)!
    const text = DOMAIN_VIEWS.living_circle.deleteWarning(record)
    // 真实态那句「该操作不可撤销，重新体检会再次消耗百度配额」对演示行是两处假话：
    // 演示行既不花配额，也能一键还原 ⇒ 钉的是"不许做出这两项声明"，不是钉字面不含某词
    expect(text).not.toMatch(/不可撤销/)
    expect(text).not.toMatch(/会再次消耗/)
    expect(text, '演示态文案要能被"可还原"这句话撑住').toContain('还原')
    expect(text).toContain('演示')
  })

  it('真实态文案逐字不变（新加的分支不许顺手改掉旧措辞）', async () => {
    await setMode('live')
    const { DOMAIN_VIEWS } = await import('../lib/domainViews')
    const record = {
      id: 'lc-kaili',
      domain: 'living_circle',
      title: '凯里老街 · 生活圈体检报告',
      checked_at: '2026-09-19T20:00:00',
    } as never
    expect(DOMAIN_VIEWS.living_circle.deleteWarning(record)).toBe(
      '确定要删除《凯里老街 · 生活圈体检报告》吗？该操作不可撤销，重新体检会再次消耗百度配额。',
    )
  })
})

describe('真实态：后端那句 deleted:false 第一次有消费方', () => {
  it('deleted:false ⇒ 说"本来就不在归档里"，确认框不关、也不假装重取', async () => {
    await setMode('live')
    mocks.deleteLifeCircleReport.mockResolvedValue({ ok: true, deleted: false })
    mocks.fetchLifeCircleReports.mockResolvedValue([
      {
        id: 'lc-kaili',
        title: '凯里老街 · 生活圈体检报告',
        scene_name: '凯里老街',
        city: '贵州·凯里',
        checked_at: '2026-09-19T20:00:00',
        total_score: 80,
        blindspot_count: 5,
        data_origin: 'live',
        interpolation: 'idw',
      } as LifeCircleRecord,
    ])
    const { default: Page } = await import('../pages/ReportsPage')
    const P = Page as ComponentType
    render(
      <MemoryRouter initialEntries={['/reports']}>
        <P />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '删除生活圈体检' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    const callsBefore = mocks.fetchLifeCircleReports.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(screen.getByText(/本来就不在归档里/)).toBeTruthy())
    expect(screen.getByRole('dialog'), '没删掉却关掉确认框 = 把失败渲染成成功').toBeTruthy()
    expect(mocks.fetchLifeCircleReports.mock.calls.length, '没删掉就不该触发重取').toBe(callsBefore)
  })

  it('正对照：同一套 UI 在 deleted:true 时要关框并重取（证明上一条不是恒真）', async () => {
    await setMode('live')
    mocks.deleteLifeCircleReport.mockResolvedValue({ ok: true, deleted: true })
    mocks.fetchLifeCircleReports.mockResolvedValue([
      {
        id: 'lc-kaili',
        title: '凯里老街 · 生活圈体检报告',
        scene_name: '凯里老街',
        city: '贵州·凯里',
        checked_at: '2026-09-19T20:00:00',
        total_score: 80,
        blindspot_count: 5,
        data_origin: 'live',
        interpolation: 'idw',
      } as LifeCircleRecord,
    ])
    const { default: Page } = await import('../pages/ReportsPage')
    const P = Page as ComponentType
    render(
      <MemoryRouter initialEntries={['/reports']}>
        <P />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '删除生活圈体检' }))
    const callsBefore = mocks.fetchLifeCircleReports.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(mocks.fetchLifeCircleReports.mock.calls.length).toBeGreaterThan(callsBefore)
  })
})

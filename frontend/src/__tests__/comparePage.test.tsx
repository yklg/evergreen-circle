// @vitest-environment jsdom
/**
 * F5 · ComparePage 双样例对比渲染、差异表、手动选择与跨城呈现。
 * 数据模式已运行时化：演示态（fixture）直接渲染；真实联调态 vi.mock api + 注入 store。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import ComparePage from '../pages/ComparePage'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'
import { useDataModeStore } from '../store/dataModeStore'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import { COMPARE_ROWS, compareDesc } from '../lib/livingCircle'
import type { LifeCircleRecord, LifeCircleCompare, LivingCircleReport } from '../types'

vi.mock('../lib/api', () => ({
  fetchLifeCircleReports: vi.fn(),
  fetchLifeCircleCompare: vi.fn(),
}))

const kailiReport = SAMPLE_COMMUNITIES[0].report
const jinsongReport = SAMPLE_COMMUNITIES[1].report
// 与凯里相距约 0.002°（≈0.2km）的「近邻」，用于触发同图真实叠加
const nearKailiReport = {
  ...kailiReport,
  id: 'kaili-near-fixture',
  scene: {
    ...kailiReport.scene,
    name: '凯里·近邻',
    center: [kailiReport.scene.center[0] + 0.002, kailiReport.scene.center[1]] as [number, number],
  },
}

const REPORT_OF: Record<string, typeof kailiReport> = {
  k1: kailiReport,
  k2: nearKailiReport,
  j1: jinsongReport,
}

function rec(id: string, name: string, city: string): LifeCircleRecord {
  return {
    id,
    title: name,
    scene_name: name,
    city,
    checked_at: '2026-09-01T08:00:00Z',
    total_score: REPORT_OF[id].scores.total,
    blindspot_count: REPORT_OF[id].blindspots.length,
    data_origin: 'fixture_sample',
    interpolation: 'idw',
  }
}

/**
 * 差异表的构造 —— **与后端真实契约同形**（6 行；行名 / 行序 / 句式都取自 `COMPARE_ROWS`）。
 *
 * 原来这里手写 `area_5 / area_10 / area_15 / area_20` 四个**假行名**，且 `a_value === b_value`
 * + `desc:'持平'` ⇒ 真实态 desc 的 **A>B / A<B 两个方向从未被覆盖**（方案评审 P1）。
 * 现在取值由行定义表派生 ⇒ 不会再长出「第二份契约副本」；方向覆盖面由下方断言守住。
 */
function diffOf(reports: LivingCircleReport[]): LifeCircleCompare['diff'] {
  return COMPARE_ROWS.map((def) => {
    const na = def.num(reports[0])
    const nb = def.num(reports[1])
    return { metric: def.key, a_value: na, b_value: nb, desc: compareDesc(def, na, nb, 'A', 'B') }
  })
}

function makeCompare(ids: string[]): LifeCircleCompare {
  const reports = ids.map((id) => REPORT_OF[id])
  return { reports, diff: diffOf(reports) }
}

/**
 * 构造一份**不守恒**的报告：Σcategories[].in_circle = 104，而图上只有 98 个点（截断方向）。
 * 用于 R6.9 披露的**成对**验证（守恒 ⇒ 不出现 / 不守恒 ⇒ 必出现）。
 */
const nonConservedReport: LivingCircleReport = {
  ...kailiReport,
  poi: {
    ...kailiReport.poi,
    categories: (kailiReport.poi.categories ?? []).map((c, i) =>
      i === 0 ? { ...c, in_circle: (c.in_circle ?? 0) + 6 } : c,
    ),
  },
}

const mockReports = vi.mocked(fetchLifeCircleReports)
const mockCompare = vi.mocked(fetchLifeCircleCompare)

afterEach(cleanup)

beforeEach(() => {
  useDataModeStore.setState({ mode: 'fixture' })
  mockReports.mockReset()
  mockCompare.mockReset()
  mockCompare.mockImplementation((ids: string[]) => Promise.resolve(makeCompare(ids)))
})

describe('ComparePage（演示态 · fixture）', () => {
  it('渲染双样例卡与各自总评分', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('凯里老街').length).toBeGreaterThan(0)
    expect(screen.getAllByText('北京劲松').length).toBeGreaterThan(0)
    expect(screen.getAllByText(String(SAMPLE_COMMUNITIES[0].report.scores.total)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(String(SAMPLE_COMMUNITIES[1].report.scores.total)).length).toBeGreaterThan(0)
  })

  it('关键差异表的行名集合与行序与行定义表逐项相同（收紧：不再只证「这行在」）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('关键差异').length).toBeGreaterThan(0)
    const want = COMPARE_ROWS.map((d) => d.key)
    // 行序：读差异表每一行的第一格。本页只有差异表一个 <table>（卡片指标行是 div），
    // 故 getAllByRole('row') 只会取到它 —— 不必为测试加 testid。
    const got = screen
      .getAllByRole('row')
      .slice(1) // 去掉表头行
      .map((tr) => tr.querySelector('td')?.textContent?.trim() ?? '')
    expect(
      got,
      `行名/行序与行定义表不符：\n  期望 ${JSON.stringify(want)}\n  实际 ${JSON.stringify(got)}\n` +
        `  差集(缺) ${JSON.stringify(want.filter((k) => !got.includes(k)))}` +
        ` 差集(多) ${JSON.stringify(got.filter((k) => !want.includes(k)))}`,
    ).toEqual(want)
  })

  it('差异表的值一律是纯数字（单位写进行名；带单位的展示形态只出现在卡片里）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    const body = screen.getAllByRole('row').slice(1)
    expect(body.length, '差异表应有 6 行').toBe(COMPARE_ROWS.length)
    for (const tr of body) {
      const tds = [...tr.querySelectorAll('td')].map((td) => td.textContent?.trim() ?? '')
      expect(tds, `每行应恰好 4 列（行名/A/B/解读），实得 ${JSON.stringify(tds)}`).toHaveLength(4)
      for (const [i, v] of [tds[1], tds[2]].entries()) {
        expect(
          /^-?\d+(\.\d+)?$/.test(v),
          `「${tds[0]}」第 ${i + 2} 列应为纯数字，实得 ${JSON.stringify(v)}`,
        ).toBe(true)
      }
    }
  })

  it('卡片指标行与差异表共用同一份行名（C1 收敛；旧的卡片专有行名已消失）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    // 旧 statList() 的卡片专有行名必须不再出现
    for (const gone of ['等时圈面积(15min)', '采样点数']) {
      expect(screen.queryByText(gone), `旧卡片行名 ${gone} 应已消失（C1 收敛）`).toBeNull()
    }
    // 差异表 1 处 + 两张卡片各 1 处 ⇒ 每个行名至少 3 处
    //（「综合评分」另有卡片右上角的大字标签，故用 >= 而非 ==）
    for (const def of COMPARE_ROWS) {
      expect(
        screen.getAllByText(def.key).length,
        `行名 ${def.key} 的出现次数（期望 >= 3：差异表 1 + 两卡片各 1）`,
      ).toBeGreaterThanOrEqual(3)
    }
  })

  it('演示态盲区行结论已修正（凯里 0 处 / 劲松 1 处 ⇒ 凯里老街盲区更少）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    // 旧实现把显示串交给 `>` 走字典序：'0 处' > '1 处' 为 false ⇒「北京劲松盲区更少」= 事实相反。
    expect(screen.getAllByText('凯里老街盲区更少').length).toBeGreaterThan(0)
    expect(screen.queryByText('北京劲松盲区更少')).toBeNull()
  })

  it('提供回到地图查看等时圈叠加的入口', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getAllByRole('button', { name: /回地图查看等时圈叠加/ }).length).toBeGreaterThan(0)
  })

  it('演示态为跨城样例（凯里 vs 北京）→ 走双图 + 归一化示意，不做同图伪叠加', async () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    // 跨城决策：不渲染「同图叠加」标题
    expect(screen.queryByText('同图叠加 · 等时圈对比')).toBeNull()
    // 双图区 + 归一化圈形示意 + 明示 banner 出现
    await waitFor(() => {
      expect(screen.getAllByText('A / B 所在城市等时圈 · 真实地理位置').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('圈形对比 · 归一化示意').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/两圈中心已归一对齐/).length).toBeGreaterThan(0)
    // fixture 态不出现选择器
    expect(screen.queryByText('对比对象')).toBeNull()
  })
})

describe('ComparePage（真实联调 · 手动选择 + 跨城呈现）', () => {
  beforeEach(() => {
    useDataModeStore.setState({ mode: 'live' })
  })

  it('默认选最近两次；跨城 A/B（凯里 vs 北京）→ 双图 + 归一，且提供选择器与交换按钮', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    // 选择器与交换按钮
    expect(screen.getByLabelText('场景 A')).toBeTruthy()
    expect(screen.getByLabelText('场景 B')).toBeTruthy()
    expect((screen.getByLabelText('场景 A') as HTMLSelectElement).options.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByLabelText('交换 A / B')).toBeTruthy()
    // 跨城呈现
    await waitFor(() => {
      expect(screen.getAllByText('A / B 所在城市等时圈 · 真实地理位置').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('同图叠加 · 等时圈对比')).toBeNull()
  })

  it('手动改选 A 后，对比请求带着新 id 重新发起', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳'), rec('k2', '凯里·近邻', '贵州凯里')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    const selA = screen.getByLabelText('场景 A') as HTMLSelectElement
    fireEvent.change(selA, { target: { value: 'k2' } })
    await waitFor(() => expect(mockCompare).toHaveBeenLastCalledWith(['k2', 'j1']))
  })

  it('交换按钮令 A/B 互换并重新取对比', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳'), rec('k2', '凯里·近邻', '贵州凯里')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    fireEvent.click(screen.getByLabelText('交换 A / B'))
    await waitFor(() => expect(mockCompare).toHaveBeenLastCalledWith(['j1', 'k1']))
  })

  it('选择器禁止把 A 选成与 B 相同（该 option 被禁用）', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    const selA = screen.getByLabelText('场景 A') as HTMLSelectElement
    const options = Array.from(selA.options)
    // 场景 B 是 j1，则 A 下拉里 j1 应为禁用；k1 保持当前选中
    const j1Option = options.find((o) => o.value === 'j1')
    expect(j1Option).toBeTruthy()
    expect(j1Option!.disabled).toBe(true)
    expect(selA.value).toBe('k1')
  })

  it('同片生活圈（凯里 vs 近邻）→ 同图真实叠加，不显示跨城双图', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('k2', '凯里·近邻', '贵州凯里')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'k2']))
    await waitFor(() => {
      expect(screen.getAllByText('同图叠加 · 等时圈对比').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('圈形对比 · 归一化示意')).toBeNull()
  })

  it('少于两条体检记录 → 空态引导', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText('至少需要两次体检记录').length).toBeGreaterThan(0)
    })
  })

  it('真实态 desc 的 A>B 与 A<B 两个方向都有覆盖（原 mock 恒为「持平」⇒ 两向从未被覆盖）', async () => {
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    // A 胜：POI 采集 217>175 · 综合评分 68.7>65.3 · 服务盲区 0<1
    await waitFor(() => expect(screen.getAllByText('A采集面更广').length).toBeGreaterThan(0))
    expect(screen.getAllByText('A更成熟').length).toBeGreaterThan(0)
    expect(screen.getAllByText('A盲区更少').length).toBeGreaterThan(0)
    // B 胜：面积 1.56<1.76 · 可达采样点 126<162 · 圈内 POI 98<104
    expect(screen.getAllByText('B可达范围更大').length).toBeGreaterThan(0)
    expect(screen.getAllByText('B可达采样点更多').length).toBeGreaterThan(0)
    expect(screen.getAllByText('B可达设施更密').length).toBeGreaterThan(0)
    // 凯里/劲松在这 6 项上没有一项相等 ⇒ 不应出现相等词
    expect(screen.queryByText('持平')).toBeNull()
  })

  it('R6.9 披露成对：守恒 ⇒ 不出现；Σ≠points ⇒ 必出现', async () => {
    // ① 守恒（真实夹具天然守恒：kaili 98/98、劲松 104/104）⇒ 不出现
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    const first = render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    // ⚠️ 先证明「表真的渲染出来了」再断言「不出现」—— 否则停在 loading 态也会得 0，是假通过。
    await waitFor(() => expect(screen.getAllByText('A采集面更广').length).toBeGreaterThan(0))
    expect(
      screen.queryAllByText(/报告圈内计数/).length,
      '守恒报告的差异表附近不应出现守恒披露',
    ).toBe(0)
    first.unmount()

    // ② 不守恒（构造 Σ=104 / points=98）⇒ 必出现，且文案与 poiConservationNote() 同源
    mockCompare.mockImplementation(() =>
      Promise.resolve({
        reports: [nonConservedReport, jinsongReport],
        diff: diffOf([nonConservedReport, jinsongReport]),
      }),
    )
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText(/报告圈内计数为 104 处/).length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText(/图上仅 98 个点/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/旧版按每类上限截断所致/).length).toBeGreaterThan(0)
  })
})
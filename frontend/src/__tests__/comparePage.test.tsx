// @vitest-environment jsdom
/**
 * F5 · ComparePage 双样例对比渲染、差异表、手动选择与跨城呈现。
 * 数据模式已运行时化：演示态（fixture）直接渲染；真实联调态 vi.mock api + 注入 store。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import ComparePage from '../pages/ComparePage'
import { SAMPLE_COMMUNITIES, demoCompareSamples } from '../mocks/livingCircleMock'
import { useDataModeStore } from '../store/dataModeStore'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import {
  CALIBER_GAP_DESC,
  COMPARE_ROWS,
  compareCaliberNotice,
  compareDesc,
  compareRows,
} from '../lib/livingCircle'
import type { LifeCircleRecord, LifeCircleCompare, LivingCircleReport } from '../types'

vi.mock('../lib/api', () => ({
  fetchLifeCircleReports: vi.fn(),
  fetchLifeCircleCompare: vi.fn(),
}))

// 一律按 id 取，不按位置：名册第 0 位是"演示默认打开的那份"，它会随演示口径移动；
// 名册里现在有两份同中心的凯里（台账上线前的冻结件 + ev-2 那份），按下标取会悄悄把
// "凯里 vs 北京"的跨城断言变成"凯里 vs 凯里"。演示态那一对直接调页面的同一个出口，
// 不在测试里重写一遍挑法。
const byId = (id: string) => SAMPLE_COMMUNITIES.find((c) => c.id === id)!
const [demoA, demoB] = demoCompareSamples()
const kailiReport = byId('kaili').report
const jinsongReport = byId('beijing-jinsong').report
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
 * 差异表定位。
 *
 * 笔1 之前本页只有一个 `<table>`（卡片指标行是 div），所以 `getAllByRole('row')` 天然只取到差异表。
 * 逐类目差距表上屏后这个前提不再成立 —— 用「表头首格＝指标」认那张差异表，
 * 而不是把期望行数改小或给生产码加 testid。
 */
function diffTable(): HTMLTableElement {
  const hit = [...document.querySelectorAll('table')].find(
    (t) => t.querySelector('th')?.textContent?.trim() === '指标',
  )
  if (!hit) throw new Error('没找到差异表（表头首格应为「指标」）')
  return hit as HTMLTableElement
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
    expect(screen.getAllByText(demoA.title).length).toBeGreaterThan(0)
    expect(screen.getAllByText(demoB.title).length).toBeGreaterThan(0)
    expect(screen.getAllByText(String(demoA.report.scores.total)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(String(demoB.report.scores.total)).length).toBeGreaterThan(0)
    // 这一对必须**跨城**（页面按跨城走双图 + 归一化示意）；同城两份并存是允许的，
    // 所以挑完还得验一次城市不同，否则名册再插一份同城样区会让本条静默失去判别力。
    expect(demoA.city).not.toBe(demoB.city)
  })

  it('关键差异表的行名集合与行序与行定义表逐项相同（收紧：不再只证「这行在」）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('关键差异').length).toBeGreaterThan(0)
    const want = COMPARE_ROWS.map((d) => d.key)
    // 行序：读差异表每一行的第一格（表已按「表头首格＝指标」定位，见 diffTable 那段）。
    const got = within(diffTable())
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
    const body = within(diffTable()).getAllByRole('row').slice(1)
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

  it('演示态差异表的结论句只有一个出口：与 compareRows() 逐字相同（页面不再自己判方向）', () => {
    // 旧实现把显示串交给 `>` 走字典序：'0 处' > '1 处' 为 false ⇒「北京劲松盲区更少」= 事实相反。
    // 方向判据本身由 `compareDiffContract.test.ts` 与后端 `test_compare_endpoint_blindspot_direction_*`
    // 用自带载体守；本页只守「演示态与真实态共用同一出口」这一条架构约束 —— 出厂快照的
    // 盲区数/口径代际会随重刷变化，页面断言不该挂在那上面。
    const want = compareRows(
      demoA.report,
      demoB.report,
      demoA.title,
      demoB.title,
    )
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    for (const row of want) {
      expect(
        screen.getAllByText(row.desc).length,
        `差异表缺少 compareRows() 判出的『${row.metric}』结论「${row.desc}」`,
      ).toBeGreaterThan(0)
    }
    // 出厂对目前版本错配（kaili 未声明 / jinsong ev-1）⇒ 顶部提示必须出现；同代际后自动收起
    const notice = compareCaliberNotice(demoA.report, demoB.report)
    if (notice) expect(screen.getAllByText(notice).length).toBeGreaterThan(0)
    else expect(screen.queryByText(CALIBER_GAP_DESC)).toBeNull()
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
    // 选择器**现在两态都有**（笔4）。原来这一条断言的是「fixture 态不出现选择器」——
    // 那条决定作废的理由：演示态是评审与提交材料实际看的那一态，把对子焊死在代码里
    // 意味着评委看到的"双样例对比"永远只有同一对，而名册里另有两份样区读不出来。
    // 断言改成反向半边：选择器必须出现，且候选是整份名册（它若再消失，这条立刻红）。
    expect(screen.getByText('对比对象')).toBeTruthy()
    const selA = screen.getByLabelText('场景 A') as HTMLSelectElement
    expect(selA.options.length).toBe(SAMPLE_COMMUNITIES.length)
    expect(selA.options.length, '名册少于两份 ⇒ 演示态选择器没有意义').toBeGreaterThanOrEqual(2)
  })

  it('演示态换 A ⇒ 卡片、差异表与逐类目那节都跟着换（不是只换下拉的显示值）', async () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    const sel = screen.getByLabelText('场景 A') as HTMLSelectElement
    // 默认 A 是名册首项（ev2）；换成同城那份冻结件 ⇒ 总分从 68.4 变 65.4
    const other = SAMPLE_COMMUNITIES.map((c) => ({ id: c.id, total_score: c.report.scores.total, scene_name: c.report.scene.name })).find((o) => o.id !== sel.value)!
    fireEvent.change(sel, { target: { value: other.id } })
    await waitFor(() => {
      expect(screen.getAllByText(String(other.total_score)).length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(String(demoA.report.scores.total))).toBeNull()
    // 副句由名字派生：原来这里写死「凯里老街（欠发达样本）vs 北京劲松（成熟样本）」，
    // 换样区后那句话就说谎了。断言两半：写死的样本标签不再出现，且副句等于当前这一对的名字。
    expect(screen.queryByText(/欠发达样本|成熟样本/)).toBeNull()
    expect(
      screen.getAllByText(`${other.scene_name} vs ${demoB.report.scene.name} —— 同一口径下的设施覆盖差距`).length,
    ).toBeGreaterThan(0)
  })

  it('演示态交换 A/B ⇒ 两侧对调；选择器仍不许把 A 选成与 B 相同', async () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    const before = (screen.getByLabelText('场景 B') as HTMLSelectElement).value
    fireEvent.click(screen.getByLabelText('交换 A / B'))
    await waitFor(() => {
      expect((screen.getByLabelText('场景 B') as HTMLSelectElement).value).not.toBe(before)
    })
    const selA = screen.getByLabelText('场景 A') as HTMLSelectElement
    const disabled = [...selA.options].filter((o) => o.disabled).map((o) => o.value)
    expect(disabled, 'A 里必须禁掉 B 当前那份').toEqual([(screen.getByLabelText('场景 B') as HTMLSelectElement).value])
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
    // A 胜：POI 采集 217 > 206。
    // ⚠️ 综合评分这一行的方向**在 10-01 反了**：`cov-1` 把凯里教育 coverage 从 1.0 打成 0.3333
    //    ⇒ 凯里总分 68.7 → **65.4** < 劲松 65.8 ⇒ 这句只能判「B更成熟」。
    //    （`rec()` 取的是 `SAMPLE_COMMUNITIES` 里那两份**真演示夹具**，不是手搓载荷，
    //    所以这一格确实是随口径翻的 —— 上一版注释写"compare 由 mock 提供、不依赖演示夹具"是
    //    我没核就写的假话，已按实测改掉。）两个方向的覆盖仍然成立：A 向由「采集面更广」守。
    await waitFor(() => expect(screen.getAllByText('A采集面更广').length).toBeGreaterThan(0))
    expect(screen.getAllByText('B更成熟').length).toBeGreaterThan(0)
    // B 胜：面积 1.56<1.76 · 可达采样点 126<162 · 圈内 POI 98<150
    expect(screen.getAllByText('B可达范围更大').length).toBeGreaterThan(0)
    expect(screen.getAllByText('B可达采样点更多').length).toBeGreaterThan(0)
    expect(screen.getAllByText('B可达设施更密').length).toBeGreaterThan(0)
    // ⚠️ 出厂快照现在两城实测盲区都是 0（ev-1 重刷后劲松的 1 处判没了）⇒ 这一行是**持平**，
    //    方向判据改由下一条自带载体的用例守（挂在快照字面数值上，快照一重刷就失去判别样本）。
    expect(screen.getAllByText('持平').length).toBe(1)
    expect(screen.queryByText('A盲区更少')).toBeNull()
    expect(screen.queryByText('B盲区更少')).toBeNull()
  })

  it('盲区行方向：0<1 与 1<0 双向都渲染得出来（自带载体，不依赖出厂快照的盲区数）', async () => {
    // 负对照：盲区越小越好。若误用「大者胜」，a=0 b=1 会输出「B盲区更少」（事实相反）。
    const withBlindspot: LivingCircleReport = {
      ...jinsongReport,
      blindspots: [
        {
          id: 'bs-方向载体-1',
          center: jinsongReport.scene.center,
          radius_m: 1000,
          missing_facilities: ['菜市场'],
          nearest: [{ facility: 'market', name: '载体', distance_m: 1450, direction: '正东' }],
          polygon: {
            type: 'Polygon',
            coordinates: [[
              [116.457, 39.879], [116.468, 39.879], [116.468, 39.887],
              [116.457, 39.887], [116.457, 39.879],
            ]],
          },
        },
      ],
    }
    const empty = { ...jinsongReport, blindspots: [] }

    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    mockCompare.mockImplementation(() =>
      Promise.resolve({ reports: [empty, withBlindspot], diff: diffOf([empty, withBlindspot]) }),
    )
    const first = render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getAllByText('A盲区更少').length).toBeGreaterThan(0))
    expect(screen.queryByText('B盲区更少')).toBeNull()
    first.unmount()

    mockCompare.mockImplementation(() =>
      Promise.resolve({ reports: [withBlindspot, empty], diff: diffOf([withBlindspot, empty]) }),
    )
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getAllByText('B盲区更少').length).toBeGreaterThan(0))
    expect(screen.queryByText('A盲区更少')).toBeNull()
  })

  it('R6.9 披露成对：守恒 ⇒ 不出现；Σ≠points ⇒ 必出现', async () => {
    // ① 守恒（真实夹具天然守恒：kaili 98/98、劲松 150/150）⇒ 不出现
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

/* ── 笔1 · 逐类目差距与盲区成对 ───────────────────────────────────────────
 *
 * 这一批判据守的不是"有没有多一块卡"，而是三种塌缩：
 *  ① 两种空值塌成一句（「一个都没有」vs「有但全在圈外」）；
 *  ② 门槛口径的"没发键"塌成 0（`types.ts` 明写不得印成 0）；
 *  ③ 0 处盲区塌成留白（读者分不清"齐备"与"还有格子判不了"）。
 * 另加一条反向守：一侧没值时**不许**画半条。
 */
describe('笔1 · 逐类目差距与盲区成对', () => {
  const renderFixture = () =>
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )

  it('逐类目差距上屏，八行类目全在（行名取自载荷，不是前端名单）', () => {
    renderFixture()
    expect(screen.getByText('逐类目差距')).toBeTruthy()
    for (const c of demoA.report.poi.categories) {
      expect(screen.getAllByText(c.label).length, `类目「${c.label}」没上屏`).toBeGreaterThan(0)
    }
  })

  it('两种空值形态各占一档：养老行 A 侧「一个都没有」、B 侧印最近耗时，差值列不硬算', () => {
    renderFixture()
    expect(screen.getByText('一个都没有')).toBeTruthy()
    // 劲松养老：total>0 而 in_circle=0 ⇒ 有最近耗时可言
    expect(screen.getByText('19.9')).toBeTruthy()
    expect(screen.getByText('一侧没值')).toBeTruthy()
  })

  it('一侧没值时不画半条（否则"没有"会被读成"很近"）', () => {
    renderFixture()
    expect(screen.getByText('一侧没有，不画条')).toBeTruthy()
  })

  it('门槛口径：只印发过口径那一侧的两句；没发键那一侧一句都不印，改由并排那句提示承担', () => {
    renderFixture()
    // 劲松有门槛项口径的类别恰好两类（医疗、教育）；若 ev2 被误当成"门槛 0"就会翻倍
    expect(screen.getAllByText(/覆盖度只数/).length).toBe(2)
    expect(screen.queryByText(/菜市场 · 覆盖度只数/)).toBeNull()
    const note = screen.getByText(/没发过门槛项口径/)
    expect(note.textContent).toContain(demoA.report.scene.name)
  })

  it('盲区成对：有盲区那一侧印出缺口与缺失类别，0 处那一侧印出空态句而不是留白', () => {
    renderFixture()
    expect(screen.getByText('盲区成对并排')).toBeTruthy()
    expect(screen.getByText(/缺失：小学/)).toBeTruthy()
    expect(screen.getByText(/缺口 0\.262/)).toBeTruthy()
    expect(screen.getAllByText(/未发现 1km 服务盲区/).length).toBeGreaterThan(0)
  })

  it('两侧都 0 处盲区 ⇒ 两侧都走空态句（真实态：凯里 × 劲松）', async () => {
    useDataModeStore.setState({ mode: 'live' })
    mockReports.mockResolvedValue([rec('k1', '凯里老街', '贵州凯里'), rec('j1', '北京劲松', '北京朝阳')])
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mockCompare).toHaveBeenCalledWith(['k1', 'j1']))
    expect(kailiReport.blindspots.length).toBe(0)
    expect(jinsongReport.blindspots.length).toBe(0)
    expect(screen.getAllByText(/未发现 1km 服务盲区/).length).toBe(2)
    expect(screen.queryByText(/缺失：/)).toBeNull()
  })
})

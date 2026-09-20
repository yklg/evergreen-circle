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
import type { LifeCircleRecord, LifeCircleCompare } from '../types'

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

function makeCompare(ids: string[]): LifeCircleCompare {
  const reports = ids.map((id) => REPORT_OF[id])
  const diff = reports[0].isochrones.map((z) => ({
    metric: `area_${z.minutes}`,
    a_value: z.area_km2,
    b_value: z.area_km2,
    desc: '持平',
  }))
  return { reports, diff }
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

  it('关键差异表包含五项指标（等时圈面积/采样点/POI/盲区/评分）', () => {
    render(
      <MemoryRouter>
        <ComparePage />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('关键差异').length).toBeGreaterThan(0)
    for (const row of ['等时圈面积(15min)', '采样点数', 'POI 采集', '服务盲区', '综合评分']) {
      expect(screen.getAllByText(row).length).toBeGreaterThan(0)
    }
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
})
// @vitest-environment jsdom
/**
 * F5 · ComparePage 双样例对比渲染与差异表。
 * 守护 fixture 态（USE_MOCK=1），与真实分支（ComparePage 非 mock）互不污染。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../mocks/livingCircleMock', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../mocks/livingCircleMock')>()
  return { ...actual, USE_MOCK: true }
})

import ComparePage from '../pages/ComparePage'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'

afterEach(cleanup)

describe('ComparePage（fixture 态）', () => {
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
})
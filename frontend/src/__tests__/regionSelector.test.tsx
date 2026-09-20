// @vitest-environment jsdom
/**
 * F3 · 省市区三级联动选择器（D1/T6）：
 * 拉取区划树 → 省/市/区逐级联动（未选上级时下级禁用）→ 选择后拼「省+市+区+详细」回填。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import RegionSelector from '../components/lifecircle/RegionSelector'

vi.mock('../lib/api', () => ({
  fetchLifeCircleRegions: vi.fn(async () => [
    {
      province: '上海市',
      cities: [{ name: '上海市', districts: ['黄浦区', '浦东新区'] }],
    },
    {
      province: '贵州省',
      cities: [
        { name: '贵阳市', districts: ['南明区', '云岩区'] },
        { name: '遵义市', districts: ['红花岗区'] },
      ],
    },
  ]),
}))

const api = vi.mocked(await import('../lib/api'))

const sel = (label: string) => screen.getByLabelText(label) as HTMLSelectElement

afterEach(cleanup)

describe('RegionSelector · 三级联动（D1）', () => {
  it('展开后默认选中首个省，市/区禁用；选择市后区可选', async () => {
    render(<RegionSelector visible onPick={vi.fn()} onClose={() => {}} />)
    await waitFor(() => {
      expect(sel('选择省').value).toBe('上海市')
    })
    // 直辖市：市自动选中（市名=省名），区可直接选
    await waitFor(() => {
      expect(sel('选择市').value).toBe('上海市')
      expect(sel('选择区县').options.length).toBeGreaterThanOrEqual(3)
    })
    // 切到贵州 → 市需手动选，区未选市前禁用
    fireEvent.change(sel('选择省'), { target: { value: '贵州省' } })
    await waitFor(() => {
      expect(sel('选择市').options[0].textContent).toBe('请选择市')
    })
    expect(sel('选择区县').options.length).toBe(1)
    expect(sel('选择区县').disabled).toBe(true)
    // 选市 → 区可选
    fireEvent.change(sel('选择市'), { target: { value: '贵阳市' } })
    await waitFor(() => {
      expect(sel('选择区县').options.length).toBeGreaterThanOrEqual(3)
    })
    expect(sel('选择区县').disabled).toBe(false)
  })

  it('选择区县后按「省+市+区」回填；直辖市不重复市名', async () => {
    const onPick = vi.fn()
    render(<RegionSelector visible onPick={onPick} onClose={() => {}} />)
    await waitFor(() => {
      expect(sel('选择省').value).toBe('上海市')
    })
    fireEvent.change(sel('选择市'), { target: { value: '上海市' } })
    fireEvent.change(sel('选择区县'), { target: { value: '浦东新区' } })
    await waitFor(() => {
      expect(onPick).toHaveBeenCalledWith('上海市浦东新区')
    })
  })

  it('详细地址参与拼串（省+市+区+详细）', async () => {
    const onPick = vi.fn()
    render(<RegionSelector visible onPick={onPick} onClose={() => {}} />)
    await waitFor(() => {
      expect(sel('选择省').value).toBe('上海市')
    })
    fireEvent.change(sel('选择市'), { target: { value: '上海市' } })
    fireEvent.change(sel('选择区县'), { target: { value: '浦东新区' } })
    fireEvent.change(screen.getByPlaceholderText(/详细地址/), { target: { value: '陆家嘴街道' } })
    await waitFor(() => {
      expect(onPick).toHaveBeenLastCalledWith('上海市浦东新区陆家嘴街道')
    })
  })

  it('区划数据加载失败：提示降级且不抛错', async () => {
    api.fetchLifeCircleRegions.mockRejectedValueOnce(new Error('network'))
    render(<RegionSelector visible onPick={vi.fn()} onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/区划数据加载失败/)).toBeTruthy()
    })
  })
})

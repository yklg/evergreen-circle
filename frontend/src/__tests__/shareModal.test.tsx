// @vitest-environment jsdom
/**
 * F4 · 报告分享弹窗（T6/E1）：
 * 分享按钮 → 弹窗含直达链接 + 复制按钮 + 二维码 canvas；share=1 横幅在报告页展示。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import ShareModal from '../components/lifecircle/ShareModal'

// 数据模式已运行时化：本用例走真实态（store 默认 live），share 端点被下方 mock 接管
vi.mock('../lib/api', () => ({
  fetchLifeCircleShare: vi.fn(async () => ({
    ok: true,
    url: '/report/lc-kaili?share=1',
    title: '凯里老街 · 生活圈体检报告',
    scene_name: '凯里老街',
  })),
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ShareModal · 分享直达链接 + 二维码（E1）', () => {
  beforeEach(() => {
    // jsdom 无 canvas 2D 上下文 → drawQrToCanvas 内部已 try/catch，不影响断言
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
  })

  it('渲染标题、直达链接与二维码 canvas', async () => {
    render(<ShareModal reportId="lc-kaili" title="凯里老街 · 生活圈体检报告" onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /分享体检报告/ })).toBeTruthy()
    })
    await waitFor(() => {
      expect(screen.getByDisplayValue(/\/report\/lc-kaili\?share=1/)).toBeTruthy()
    })
    const canvas = screen.getByLabelText('分享链接二维码')
    expect(canvas).toBeTruthy()
    expect(screen.getByText(/扫码直达本报告/)).toBeTruthy()
  })

  it('点击复制：写入完整链接（origin + path）并提示已复制', async () => {
    render(<ShareModal reportId="lc-kaili" title="t" onClose={() => {}} />)
    const btn = await screen.findByRole('button', { name: /复制/ })
    fireEvent.click(btn)
    // ⚠️ 断言顺序有意义：组件用 setTimeout(…, 2000) 自动复原「已复制」标签，
    // 而 waitFor 的耗时不可控（并行跑 31 个文件时会因 CPU 争抢超过 2s）。
    // 故**先**断言时间敏感的 UI 反馈，再断言无时序依赖的剪贴板写入，避免竞态误报。
    await screen.findByRole('button', { name: /已复制/ })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      `${window.location.origin}/report/lc-kaili?share=1`,
    )
  })

  it('关闭按钮触发 onClose', () => {
    const onClose = vi.fn()
    render(<ShareModal reportId="lc-kaili" title="t" onClose={onClose} />)
    fireEvent.click(screen.getByTitle('关闭'))
    expect(onClose).toHaveBeenCalled()
  })
})

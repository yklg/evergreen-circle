// @vitest-environment jsdom
/**
 * 工作台「纵向契约」结构性绊线（计划 fluid-mist-eel 阶段 2）
 *
 * 钉的是四件事：
 *   TW-1 首页恰好两个带，且带 1 装输入卡、带 2 装示例（绊线不能被随便两个 section 满足）；
 *   TW-2 带 1 = `flex-1`（吃视口余量）且**不得**出现 `min-h-0`；
 *   TW-3 带 2 = `shrink-0` 且间距归带所有（`pt-8`/`pb-24`），首子不再自带 `mt-8`；
 *   TW-4 两带共享同一条「带壳」= 层级 + 居中 + 度量 + 沟槽，且都不含 `100vh` / `min-h-[calc(`。
 *
 * ⚠️ 效力上限（必须读，否则本文件会伪装成防线）：
 * 这里只钉「边界被声明过」，**钉不住本症状复发** —— 下一个人往带 1 里再加一块，带 1 长过视口、
 * 示例照样掉出首屏，而本文件四条全绿。首屏可见像素、`z-index` 是否真生效、margin 是否塌陷
 * 都需要布局引擎，而 jsdom 没有、本仓也没有 e2e。
 * ⇒ 布局判据的唯一防线是人工重跑 `skip/tmp/home-fit-preview/verify.mjs` 多视口矩阵。
 * **别把本文件的绿色当布局证据**（见计划「评审记录 I 系列 · I7」）。
 *
 * 为什么断 DOM 的 class 串而不是扫源码：本文件所在仓库的守卫纪律是「扫全文会被注释里的散文
 * 误伤」（`tailwindClassIntegrity.test.ts:81-84` 明写此坑），而 `ComposerBand` 的注释里就带着
 * 旧字符串 `min-h-[calc(100vh-80px)]` —— 扫源码会当场假红。DOM 上的 class 才是真上屏的那一份。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  fetchExperts: vi.fn(),
  fetchResearchTypes: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  createTask: mocks.createTask,
  fetchExperts: mocks.fetchExperts,
}))
vi.mock('../lib/researchTypesClient', () => ({
  fetchResearchTypes: mocks.fetchResearchTypes,
}))

async function renderHome() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  mocks.createTask.mockReset()
  mocks.fetchExperts.mockReset().mockResolvedValue([])
  mocks.fetchResearchTypes.mockReset().mockResolvedValue([
    { key: 'guide', label: '游玩攻略', subtitle: '交通 · 住宿 · 路线' },
    { key: 'assessment', label: '调研评估', subtitle: '可达性 · 配套 · 安全' },
  ])
  const { default: HomePage } = await import('../pages/HomePage')
  return render(
    <MemoryRouter initialEntries={['/']}>
      <HomePage />
    </MemoryRouter>,
  )
}

afterEach(cleanup)

/** 取两个带 + 它们的 class 串。 */
async function bands() {
  const { container } = await renderHome()
  const sections = [...container.querySelectorAll('main section, section')]
  const cls = sections.map((s) => (s.getAttribute('class') ?? '').split(/\s+/).filter(Boolean))
  return { sections, cls }
}

describe('TW-1 · 带的身份：带 1 装输入卡，带 2 装示例', () => {
  it('两个带，且内容归属正确（防"随便给两个 section 挂上类名"过绊线）', async () => {
    const { sections } = await bands()
    expect(sections.length).toBe(2)
    expect(sections[0].querySelector('textarea[aria-label="调研需求"]')).not.toBeNull()
    expect(sections[1].textContent ?? '').toContain('试试这些示例')
  })
})

describe('TW-2 / TW-3 · 分配类：谁吃余量、谁不参与压缩', () => {
  it('带 1 有 flex-1 且**没有** min-h-0（写了就会塌陷并把内容顶到滚不回的块首）', async () => {
    const { cls } = await bands()
    expect(cls[0]).toContain('flex-1')
    expect(cls[0]).not.toContain('min-h-0')
    expect(cls[0]).toContain('justify-center')
  })

  it('带 2 有 shrink-0、没有 flex-1，且间距归带（pt-8 + pb-24 给固定浮条让位）', async () => {
    const { cls } = await bands()
    expect(cls[1]).toContain('shrink-0')
    expect(cls[1]).not.toContain('flex-1')
    expect(cls[1]).toContain('pt-8')
    expect(cls[1]).toContain('pb-24')
  })

  it('示例标题不再自带 mt-8（两处都留会变成 32+32 的双份间距）', async () => {
    await renderHome()
    const head = screen.getByText('试试这些示例 · 随所选类型切换')
    const c = (head.getAttribute('class') ?? '').split(/\s+/)
    expect(c).not.toContain('mt-8')
  })
})

describe('TW-4 · 带壳四件必须一起走', () => {
  const SHELL = ['relative', 'z-10', 'mx-auto', 'w-full', 'max-w-[880px]', 'px-6']

  it('两带都带完整带壳（漏 relative 或 z-10 ⇒ hero-bg 盖内容，且 `-z-0` 实为 z-index:0）', async () => {
    const { cls } = await bands()
    for (const c of cls) {
      for (const t of SHELL) expect(c).toContain(t)
    }
  })

  it('两带都不含视口高度类（`100vh` / `min-h-[calc(` 一旦被抄回来，症状会原样复发）', async () => {
    const { cls } = await bands()
    for (const c of cls) {
      expect(c.some((t) => t.includes('100vh'))).toBe(false)
      expect(c.some((t) => t.includes('min-h-[calc'))).toBe(false)
    }
  })
})

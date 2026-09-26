// @vitest-environment jsdom
/**
 * 首页调研类型「来源与降级」契约（M4b-2/S6 · 重锚至三能力入口 HomePage）
 *
 * 竞品时代此钉有 5 例（卡片互斥选中 / createTask 透传 type / 示例随域切换 / 类型来源 / 失败态）。
 * 其中「互斥选中、type 透传、示例随域切换」已由 skip 三能力入口的 `homeDomainEntry.test.tsx`
 * 就真实架构覆盖（FE-20 / FE-21 / FE-22-24）——本文件不再重复，是**覆盖迁移非放宽**。
 * 此处只守首页独有、且 homeDomainEntry 未覆盖的两条契约：
 *   HT-1 类型卡 label/subtitle 来自注册表适配层（前端不得硬编码中文类型名）——用哨兵值证明；
 *   HT-2 类型端点失败降级到本地快照时，页面照常渲染两型、不弹错误态、主 CTA 仍在。
 *
 * 契约变更说明（S6 决策）：skip 现架构采**优雅降级**——`researchTypesClient` 永不 reject，
 * 拉取失败即回落 `RESEARCH_TYPES_FALLBACK`（恒为 guide/assessment 两型）继续渲染；
 * 这取代了旧「类型接口失败 → 必报错 + 拦提交」的设计（旧设计怕的是静默塞单一错默认；
 * 而回落的是同一套官方两型，不存在错默认，且首页主流程不应因注册表瞬断而卡死）。
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

// 哨兵：若前端硬编码「游玩攻略/调研评估」，HT-1 的 null 断言会失败
const SENTINEL = [
  { key: 'guide', label: 'ZZTYPE_ALPHA', subtitle: 'ZZSUB_ALPHA' },
  { key: 'assessment', label: 'ZZTYPE_BETA', subtitle: 'ZZSUB_BETA' },
]
// 模拟降级快照（等价 RESEARCH_TYPES_FALLBACK 的两型官方文案）
const SNAPSHOT = [
  { key: 'guide', label: '游玩攻略', subtitle: '交通 · 住宿 · 路线' },
  { key: 'assessment', label: '调研评估', subtitle: '可达性 · 配套 · 安全' },
]

async function renderHome() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  mocks.createTask.mockReset()
  mocks.fetchExperts.mockReset().mockResolvedValue([])
  const { default: HomePage } = await import('../pages/HomePage')
  return render(
    <MemoryRouter initialEntries={['/']}>
      <HomePage />
    </MemoryRouter>,
  )
}

afterEach(cleanup)

describe('首页调研类型来源与降级（S6）', () => {
  it('HT-1 卡片文案全部来自注册表适配层，前端未硬编码中文类型名', async () => {
    mocks.fetchResearchTypes.mockResolvedValue(SENTINEL)
    await renderHome()
    expect(await screen.findByText('ZZTYPE_ALPHA')).toBeTruthy()
    expect(screen.getByText('ZZSUB_ALPHA')).toBeTruthy()
    expect(screen.getByText('ZZTYPE_BETA')).toBeTruthy()
    // 防回潮：后端注册表的中文文案不得出现在前端首页
    expect(screen.queryByText('游玩攻略')).toBeNull()
    expect(screen.queryByText('调研评估')).toBeNull()
  })

  it('HT-2 类型源降级到快照时：两型照常渲染、无错误态、主 CTA 仍在', async () => {
    mocks.fetchResearchTypes.mockResolvedValue(SNAPSHOT)
    await renderHome()
    await screen.findByText('游玩攻略')
    expect(screen.getByText('调研评估')).toBeTruthy()
    // 旧「调研类型加载失败」错误态不得回潮（skip 已改优雅降级）
    expect(screen.queryByRole('alert')).toBeNull()
    expect(
      screen.getByRole('button', { name: /开始调研|前往生活圈地图/ }),
    ).toBeTruthy()
  })
})

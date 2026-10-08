// @vitest-environment jsdom
/**
 * 分章静态地图的**画框**（`lcContentFrame`）契约 —— 治"图歪在纸边中间"。
 *
 * 症状与机制：投影画布恒 860×620、恒以社区中心为原点，而真实可达场只占其中一小块
 * （凯里样区实测内容宽只占画布 54%）。主图有底图瓦片填掉那片空白，静态分章图没有 ⇒
 * 读者看到一小坨图外加四边纸，且 SVG 只写 `w-full` 时高度按宽度自算出 612px，
 * 溢出 340px 的槽、把下面那句图注压住。
 *
 * 判据分两层：① 画框本身（逐样区钉实测值 ＋ 退化输入两态 ＋ 坏坐标被过滤）；
 * ② 渲染侧（`viewBox` 真的收了、`preserveAspectRatio` 与 `h-full` 在场 ⇒ 不再溢出）。
 * 期望值全部来自一次实跑探针（探针已删），不是推算出来的。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { LC_CANVAS, lcContentFrame, lcFrameViewBox } from '../lib/livingCircle'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { MemoryRouter } from 'react-router-dom'
import type { LivingCircleReport, Report } from '../types'

vi.mock('../lib/bmap', () => ({
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => { throw new Error('测试内不应注入 BMapGL') },
  geolocateMe: async () => null,
}))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => vi.fn() }
})
vi.mock('../components/VChart', () => ({ VChart: () => <div data-testid="mock-chart" /> }))

const lcOf = (id: string): LivingCircleReport =>
  (getLivingCircleReportMock(id) as unknown as { living_circle: LivingCircleReport }).living_circle

/** 实测基线（一次探针跑出来的，禁凭记忆改写）。 */
const PINNED = {
  'lc-kaili': '180.3 176.3 502.6 284.1',
  'lc-kaili-ev2': '180.3 176.3 502.6 284.1',
  'lc-beijing-jinsong': '205.3 127.6 475.8 362.4',
}
const FULL = `0.0 0.0 ${LC_CANVAS.W.toFixed(1)} ${LC_CANVAS.H.toFixed(1)}`

describe('lcContentFrame · 画框收进内容包围盒', () => {
  for (const [id, pinned] of Object.entries(PINNED)) {
    it(`${id}：画框逐字等于实测基线`, () => {
      expect(lcFrameViewBox(lcContentFrame(lcOf(id)))).toBe(pinned)
    })

    it(`${id}：框中心与画布中心同侧（图不再歪到角落），且明显比整幅画布紧`, () => {
      const f = lcContentFrame(lcOf(id))
      const cx = f.x + f.w / 2
      const cy = f.y + f.h / 2
      // 中心本身就在画布中心附近（投影以 scene.center 为原点）—— 歪的观感来自四周留白，不是数据偏。
      expect(Math.abs(cx - LC_CANVAS.W / 2), `${id} 框中心 x 偏离画布中心`).toBeLessThan(30)
      expect(Math.abs(cy - LC_CANVAS.H / 2), `${id} 框中心 y 偏离画布中心`).toBeLessThan(30)
      // 收框后内容占框 ≥ 80%（padding 只有 8%）⇒ 才谈得上"放大居中"而不只是"挪位置"。
      expect(f.w, `${id} 的框宽没比画布明显小 ⇒ 根本没收框`).toBeLessThan(LC_CANVAS.W * 0.75)
      expect(f.h, `${id} 的框高没比画布明显小 ⇒ 根本没收框`).toBeLessThan(LC_CANVAS.H * 0.75)
    })
  }

  it('退化输入两态：空载荷退回整幅、坏坐标被过滤（不产 NaN 也不炸）', () => {
    const lc = lcOf('lc-kaili')
    const empty = lcContentFrame({ ...lc, isochrones: [], blindspots: [], poi: { ...lc.poi, points: [] } })
    expect(lcFrameViewBox(empty), '什么都没画 ⇒ 退回整幅画布，别产一个零宽框').toBe(FULL)

    const dirty = lcContentFrame({
      ...lc,
      poi: { ...lc.poi, points: [{ id: 'bad', lnglat: [NaN, 31] as never, category: 'medical' }, ...lc.poi.points] as never },
    })
    expect(lcFrameViewBox(dirty), '坏点必须被过滤掉，不能把 NaN 带进 viewBox')
      .toBe(lcFrameViewBox(lcContentFrame(lc)))
    expect(lcFrameViewBox(dirty)).not.toMatch(/NaN|Infinity/)
  })

  it('确定性：同一份载荷两次取框逐字相同（框里不许有墙钟或随机）', () => {
    const lc = lcOf('lc-kaili-ev2')
    expect(lcFrameViewBox(lcContentFrame(lc))).toBe(lcFrameViewBox(lcContentFrame(lc)))
  })
})

describe('分章地图的渲染侧：收了框、且不再溢出槽', () => {
  afterEach(cleanup)

  it('svg 的 viewBox 是收过的框（不是整幅画布），并带 meet 与 h-full', async () => {
    const report = getLivingCircleReportMock('lc-kaili-ev2') as unknown as Report
    const view = render(
      <MemoryRouter initialEntries={['/report/lc-kaili-ev2']}>
        <LifeCircleReportView report={report} />
      </MemoryRouter>,
    )
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
    const svgs = [...view.container.querySelectorAll('svg[aria-label$="本章设施分布"]')]
    expect(svgs.length, '分章图一张都没渲染 ⇒ 本条空过').toBeGreaterThan(0)
    const pinned = PINNED['lc-kaili-ev2']
    for (const svg of svgs) {
      expect(svg.getAttribute('viewBox'), '画框没收到内容包围盒 ⇒ 图仍会歪在纸边中间').toBe(pinned)
      expect(svg.getAttribute('preserveAspectRatio'), '不 meet 就会裁掉一侧').toBe('xMidYMid meet')
      expect(svg.getAttribute('class'), '没有 h-full ⇒ SVG 按宽度自算高度、溢出槽压住图注')
        .toContain('h-full')
      // 槽的宽高比跟着同一个画框走 —— 这正是"两侧各空 124px"那一半的修法。
      const slot = svg.parentElement as HTMLElement
      expect(slot.style.aspectRatio, '槽高不跟画框 ⇒ meet 只能取小的缩放比，图两侧留大片空档')
        .toBe('502.6 / 284.1')
      expect(slot.className).toContain('max-h-[460px]')
    }
  })
})

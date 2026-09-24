// @vitest-environment jsdom
/**
 * V-P3 行程可视化测试钉：P-F1..F4（投影性质/退化/模板回退/名称归一）+
 * A-F1（VRoutePlan 逐日时间线 + 坐标缺→仅时间线）+ N5 价位带（有数值出带/无数值回落）。
 *
 * 投影是纯函数（lib/spotProjection），模板是数据资产（lib/spotSketchTemplates）——
 * 组件层只钉「出不出、挂哪」，不钉像素。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { finitePoints, projectPoints } from '../lib/spotProjection'
import { matchSketchTemplate, normalizeTemplateKey } from '../lib/spotSketchTemplates'
import { VRoutePlan, VStayTable } from '../components/VStructured'

afterEach(cleanup)

const W = 640
const H = 420

/* ── P-F1 性质钉：固定点集的相对方位与边界盒归一 ── */
describe('P-F1 投影性质', () => {
  const pts = [
    { id: 'a', lat: 25.6, lng: 100.1 },
    { id: 'b', lat: 25.7, lng: 100.2 },
    { id: 'c', lat: 25.65, lng: 100.3 },
    { id: 'd', lat: 25.8, lng: 100.15 },
  ]
  const out = projectPoints(pts, W, H, 56)

  it('经度大→x 大、纬度大→y 小（地图向），相对方位保序', () => {
    const m = new Map(out.map((p) => [p.id, p]))
    expect(m.get('b')!.x).toBeGreaterThan(m.get('a')!.x)
    expect(m.get('b')!.y).toBeLessThan(m.get('a')!.y)
    expect(m.get('c')!.x).toBeGreaterThan(m.get('b')!.x)
    expect(m.get('d')!.y).toBeLessThan(m.get('a')!.y)
  })

  it('边界盒归一：全部落在 [pad, size-pad] 内，极值点触边', () => {
    for (const p of out) {
      expect(p.x).toBeGreaterThanOrEqual(56 - 1e-6)
      expect(p.x).toBeLessThanOrEqual(W - 56 + 1e-6)
      expect(p.y).toBeGreaterThanOrEqual(56 - 1e-6)
      expect(p.y).toBeLessThanOrEqual(H - 56 + 1e-6)
    }
    const xs = out.map((p) => p.x)
    expect(Math.min(...xs)).toBeCloseTo(56)
    expect(Math.max(...xs)).toBeCloseTo(W - 56)
  })
})

/* ── P-F2 退化输入（评审④）：0/1 点、全同经纬 → 无 NaN、居中散点 ── */
describe('P-F2 投影退化', () => {
  it('0 点 → 空集；脏坐标点被过滤', () => {
    expect(projectPoints([], W, H)).toEqual([])
    expect(projectPoints([{ id: 'x', lat: NaN, lng: 100 }], W, H)).toEqual([])
    expect(finitePoints([{ id: 'a', lat: 1, lng: 2 }, { id: 'b', lat: 0, lng: Infinity }]))
      .toHaveLength(1)
  })

  it('1 点 → 画布中心', () => {
    const [p] = projectPoints([{ id: 'solo', lat: 25.7, lng: 100.15 }], W, H)
    expect(p).toEqual({ id: 'solo', x: W / 2, y: H / 2 })
  })

  it('全同经纬（零方差）→ 圆周散点回退：无 NaN、互不重合、仍居中', () => {
    const same = ['a', 'b', 'c', 'd'].map((id) => ({ id, lat: 25.7, lng: 100.15 }))
    const out = projectPoints(same, W, H, 56)
    expect(out).toHaveLength(4)
    for (const p of out) {
      expect(Number.isFinite(p.x)).toBe(true)
      expect(Number.isFinite(p.y)).toBe(true)
    }
    const keys = new Set(out.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`))
    expect(keys.size).toBe(4)
    const meanX = out.reduce((s, p) => s + p.x, 0) / out.length
    expect(meanX).toBeCloseTo(W / 2)
  })

  it('单轴零方差：退化轴散开，另一轴仍按真实值线性投影', () => {
    const row = [
      { id: 'a', lat: 25.7, lng: 100.0 },
      { id: 'b', lat: 25.7, lng: 100.2 },
    ]
    const out = projectPoints(row, W, H, 56)
    expect(out[1].x).toBeGreaterThan(out[0].x)
    expect(out[0].x).toBeCloseTo(56)
    expect(out[0].y).not.toBeCloseTo(out[1].y)
  })
})

/* ── P-F3/P-F4 模板回退与名称归一（数据资产层） ── */
describe('P-F3/P-F4 模板资产', () => {
  it('未知目的地 → 抽象底形 + schematic 标记（组件据此标注「示意」）', () => {
    const tpl = matchSketchTemplate('海口骑楼老街')
    expect(tpl.schematic).toBe(true)
    expect(tpl.blobPath).toMatch(/^M/)
    expect(tpl.roadPaths.length).toBeGreaterThan(0)
  })

  it('模板 key 名称归一：大理古城/大理 州 同族命中同一模板', () => {
    expect(normalizeTemplateKey('大理古城')).toBe(normalizeTemplateKey('大理'))
    expect(normalizeTemplateKey('大理市')).toBe('大理')
    const tpl = matchSketchTemplate('大理古城')
    expect(tpl.key).toBe('大理')
    expect(tpl.schematic).toBeUndefined()
  })
})

/* ── A-F1 VRoutePlan：逐日时间线 + 坐标齐出海报，坐标缺→仅时间线 ── */
const DAY_ROUTE = [
  {
    destination: '大理',
    days: [
      { day: 1, spots: [
        { name: '洱海生态廊道', spot_id: '大理_spot_1', lat: 25.72, lng: 100.18, transport: '公交：公交1路·约40分钟', duration: '约2小时' },
        { name: '崇圣寺三塔', spot_id: '大理_spot_2', lat: 25.70, lng: 100.15, transport: '打车：约15分钟', duration: '约2小时' },
        { name: '美食停靠：老字号', shop_id: '大理_shop_1', lat: null, lng: null, duration: '约1小时' },
      ] },
      { day: 2, spots: [
        { name: '喜洲古镇', spot_id: '大理_spot_3', lat: 25.85, lng: 100.12, transport: '公交：约50分钟' },
      ] },
    ],
  },
]

describe('A-F1 逐日时间线与分布海报', () => {
  it('坐标齐 → 出分布海报（svg + 分日路径 + 逐段注记）+ 时间线保底结构', () => {
    const { container } = render(<VRoutePlan data={DAY_ROUTE} />)
    expect(screen.getByText('大理 · 逐日路线')).toBeTruthy()
    expect(container.querySelector('[data-spot-sketch]')).not.toBeNull()
    expect(container.querySelectorAll('[data-day-path]').length).toBe(1) // DAY1 两点一线
    expect(container.querySelectorAll('[data-sketch-stop]').length).toBe(3) // 商铺无坐标不入点位
    expect(container.querySelectorAll('[data-leg-note]').length).toBe(1)
    expect(container.querySelector('[data-schematic]')).toBeNull() // 大理有专属模板
    // 时间线：Day 徽章 + 停靠实体键 + 徽标齐
    expect(container.querySelector('[data-route-day="1"]')).not.toBeNull()
    expect(container.querySelector('[data-spot-id="大理_spot_1"]')).not.toBeNull()
    expect(screen.getByText('美食停靠')).toBeTruthy()
  })

  it('坐标缺（LLM 旧版 route_plan 无 lat/lng）→ 海报与地图整体缺位，仅时间线', () => {
    const noCoord = [{ destination: '大理', days: [
      { day: 1, spots: [{ name: '大理古城', spot_id: '大理_spot_1', transport: '步行' }] },
      { day: 2, spots: [{ name: '双廊', spot_id: '大理_spot_2' }] },
    ] }]
    const { container } = render(<VRoutePlan data={noCoord} />)
    expect(container.querySelector('[data-spot-sketch]')).toBeNull()
    expect(container.querySelector('[data-bmap-holder]')).toBeNull()
    expect(container.querySelector('[data-map-placeholder]')).toBeNull()
    expect(container.querySelectorAll('[data-stop]').length).toBe(2)
    expect(screen.getByText(/交通：步行/)).toBeTruthy()
  })

  it('空/脏数据不崩', () => {
    expect(render(<VRoutePlan data={[]} />).container.firstChild).toBeNull()
  })
})

/* ── N5 价位带：有数值出带（区间条 + 端点标签），无数值回落纯文本 ── */
describe('N5 住宿价位带', () => {
  it('price_min/max 齐 → 按全组最大值归一出横向带；区间倒挂/缺值区域不进带', () => {
    const { container } = render(<VStayTable data={[{ destination: '大理', areas: [
      { area: '才村', price_range: '300-500', price_min: 300, price_max: 500 },
      { area: '古城', price_range: '150-250', price_min: 150, price_max: 250 },
      { area: '双廊', price_range: '价格面议', price_min: null, price_max: null },
    ] }]} />)
    const bands = container.querySelectorAll('[data-stay-band]')
    expect(bands.length).toBe(2)
    const first = container.querySelector('[data-stay-band="才村"] [data-band-style]') as HTMLElement
    expect(parseFloat(first.style.left)).toBeCloseTo(60)   // 300/500
    expect(parseFloat(first.style.width)).toBeCloseTo(40)  // (500-300)/500
    const second = container.querySelector('[data-stay-band="古城"] [data-band-style]') as HTMLElement
    expect(parseFloat(second.style.left)).toBeCloseTo(30)
    expect(screen.getByText('¥300-500')).toBeTruthy()
    expect(screen.getByText('¥150-250')).toBeTruthy()
    // 表内自由文本列仍在（未造数区域靠它）
    expect(screen.getByText('价格面议')).toBeTruthy()
  })

  it('全组无数值（旧报告）→ 无价位带块，表格照出', () => {
    const { container } = render(<VStayTable data={[{ destination: '大理', areas: [
      { area: '才村', price_range: '¥300-500' },
    ] }]} />)
    expect(container.querySelector('[data-stay-bands]')).toBeNull()
    expect(screen.getByText('¥300-500')).toBeTruthy()
  })

  it('单值/零宽区间（min≈max）→ 仍出带，宽度钳到最小可见 3%', () => {
    const { container } = render(<VStayTable data={[{ destination: '大理', areas: [
      { area: 'A', price_range: '约800起', price_min: 800, price_max: null },
      { area: 'B', price_range: '2000', price_min: 2000, price_max: 2000 },
    ] }]} />)
    const barA = container.querySelector('[data-stay-band="A"] [data-band-style]') as HTMLElement
    expect(parseFloat(barA.style.width)).toBeCloseTo(3) // hi 回落 = lo → 零宽钳到保底 3%
    expect(screen.getByText('¥800')).toBeTruthy() // 单值不带横杠
  })
})

// @vitest-environment jsdom
/**
 * 景点实体四件套渲染器（TC-F01 / M1e）
 *
 * 守护契约（数据形状 = 后端 schemas.coerce_* 冻结输出，键名成对）：
 *   SP-1  spot_ranking：评分明细列（声量·口碑·性价比）、data-spot-id 挂接键、
 *        matched===false → 「位置未匹配」占位（不得静默消失）
 *   SP-2  spot_routes：路线卡默认展开 Top3（前 3 个 <details open>）、
 *        空 routes → 「数据源暂不可用（路线待补充）」如实占位
 *   SP-3  shop_list：人均标「参考价」；缺价 → 「未公开」（LLM 参考价不是实价）
 *   SP-4  空数组 / 缺字段容错 + VStructuredBlock 分发（未知类型静默跳过）
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import {
  VStructuredBlock,
  VSpotRanking,
  VSpotRoutes,
  VShopList,
  VSpotAtlas,
  VSpotRankBar,
  VFoodRanking,
  rankBarWidth,
} from '../components/VStructured'
import type { StructuredBlockType } from '../types'

afterEach(() => cleanup())

const SPOT_RANKING = [
  {
    destination: '大理',
    items: [
      {
        spot_id: '大理_spot_1', name: '大理古城', area: '城区', matched: true,
        rank: 1, score: 86.4, dims: { voice: 100, sentiment: 82, value: 70 },
        ticket: '免费，无需预约', stay_minutes: 180, off_peak: '工作日上午',
        reason: '证据高频提及的地标片区', evidence_ids: ['e_1'],
      },
      {
        spot_id: '大理_spot_2', name: '理想邦', area: '环海东路', matched: false,
        rank: 2, score: 61.2, dims: { voice: 55, sentiment: 74, value: 60 },
        evidence_ids: ['e_2'],
      },
    ],
  },
]

describe('SP-1 景点评分榜', () => {
  it('行内展示综合分与三维明细，名次/门票/停留/避峰/理由齐备', () => {
    const { container, getByText } = render(<VSpotRanking data={SPOT_RANKING} />)
    expect(getByText('大理 · 景点综合评分榜')).toBeTruthy()
    expect(getByText('大理古城')).toBeTruthy()
    expect(getByText('86.4')).toBeTruthy()
    expect(getByText(/（100·82·70）/)).toBeTruthy()
    expect(getByText('免费，无需预约')).toBeTruthy()
    expect(getByText('180分钟')).toBeTruthy()
    expect(getByText('工作日上午')).toBeTruthy()
    expect(getByText('证据高频提及的地标片区')).toBeTruthy()
    // 实体挂接键：地图/舆情/路线联动全靠 data-spot-id
    expect(container.querySelector('[data-spot-id="大理_spot_1"]')).not.toBeNull()
  })

  it('matched=false → 显式「位置未匹配」占位（不是藏掉景点）', () => {
    const { getByText } = render(<VSpotRanking data={SPOT_RANKING} />)
    expect(getByText('位置未匹配')).toBeTruthy()
    expect(getByText('理想邦')).toBeTruthy()
  })
})

describe('SP-2 逐景点路线卡', () => {
  it('spot_id 原样挂接、默认展开 Top3、第 4 卡收起', () => {
    const items = [1, 2, 3, 4].map((i) => ({
      spot_id: `大理_spot_${i}`, spot_name: `景点${i}`,
      routes: [{ mode: '地铁', duration: '25分钟', cost: '4元', transfer: '1 次', note: '东门站下' }],
    }))
    const { container, getAllByText } = render(
      <VSpotRoutes data={[{ destination: '大理', items }]} />,
    )
    expect(getAllByText('地铁')).toHaveLength(4)
    const cards = Array.from(container.querySelectorAll('details'))
    expect(cards.slice(0, 3).every((d) => d.hasAttribute('open'))).toBe(true)
    expect(cards[3].hasAttribute('open')).toBe(false)
    expect(container.textContent).toContain('大理_spot_1')
  })

  it('routes 为空 → 「数据源暂不可用（路线待补充）」占位不崩', () => {
    const { container } = render(
      <VSpotRoutes data={[{ destination: '大理', items: [{ spot_id: 'x', spot_name: '古城' }] }]} />,
    )
    expect(container.textContent).toContain('数据源暂不可用（路线待补充）')
  })
})

describe('SP-3 美食商铺清单', () => {
  it('人均价标注「参考价」；缺价显示「未公开」而非 0', () => {
    const { container } = render(
      <VShopList data={[{ destination: '大理', items: [
        { shop_id: '大理_shop_1', name: '老字号', food: '乳扇', area: '古城',
          price_per_person: 58, queue_note: '饭点排队约 30 分钟' },
        { shop_id: '大理_shop_2', name: '无名小店' },
      ]}]} />,
    )
    expect(container.textContent).toContain('58元（参考价）')
    expect(container.textContent).toContain('美食商铺（人均为参考价）')
    expect(container.textContent).toContain('饭点排队约 30 分钟')
    expect(container.textContent).toContain('未公开')
    expect(container.textContent).not.toMatch(/0元/)
  })

  it('M3e 路线列：有真实公交路线则展示明细，无路线出「暂不可用」占位（缺 AK 降级不崩）', () => {
    const { container } = render(
      <VShopList data={[{ destination: '大理', items: [
        { shop_id: '大理_shop_1', name: '老字号', food: '乳扇', matched: true,
          routes: [{ mode: '公交/地铁', duration: '约40分钟', cost: '',
                     transfer: '公交1路', note: '自市中心出发，全程约8.2公里', evidence_ids: [] }] },
        { shop_id: '大理_shop_2', name: '配额外的店', food: '乳扇' },
      ]}]} />,
    )
    expect(container.textContent).toContain('约40分钟')
    expect(container.textContent).toContain('公交1路')
    expect(container.textContent).toContain('自市中心出发')
    expect(container.querySelectorAll('[data-shop-route-unavailable]')).toHaveLength(1)
    expect(container.textContent).toContain('路线数据源暂不可用')
  })
})

describe('SP-4 容错与分发', () => {
  it('空 data → 不渲染；缺字段行 → 占位字符回落', () => {
    expect(render(<VSpotRanking data={[]} />).container.textContent).toBe('')
    const r = render(<VSpotRanking data={[{ destination: '大理', items: [{ name: '光杆景点' }] }]} />)
    expect(r.container.textContent).toContain('光杆景点')
    expect(r.container.textContent).toContain('—')
  })

  it('VStructuredBlock 按类型分发四个新键（键集与后端 structured_keys 成对）', () => {
    const cases: [StructuredBlockType, string][] = [
      ['spot_ranking', '景点综合评分榜'],
      ['food_ranking', '美食 Top 榜'],
      ['spot_routes', '逐景点路线'],
      ['shop_list', '美食商铺'],
    ]
    const data = [{ destination: '大理', items: [{ name: '甲' }] }]
    for (const [type, marker] of cases) {
      const { container, unmount } = render(<VStructuredBlock block={{ type, data }} />)
      expect(container.textContent).toContain(marker)
      unmount()
    }
  })
})

/* ── K-F1/F2 景点榜单条图（F2 本地 CSS）+ 地图降级替身 ───────── */
describe('K-F1 条图归一映射', () => {
  it('rankBarWidth：0-10 与 0-100 双值域自适应 + 越界钳位 + 非数值回落 0', () => {
    expect(rankBarWidth(8.6)).toBeCloseTo(86)
    expect(rankBarWidth(86.4)).toBeCloseTo(86.4)
    expect(rankBarWidth(0)).toBe(0)
    expect(rankBarWidth(120)).toBe(100)
    expect(rankBarWidth(-5)).toBe(0)
    expect(rankBarWidth(undefined)).toBe(0)
    expect(rankBarWidth('8.6')).toBeCloseTo(86)
  })

  it('条图渲染：名次/名称/条宽=归一分/数值标签/门票价签', () => {
    const { container } = render(<VSpotRankBar data={SPOT_RANKING as never} />)
    expect(container.textContent).toContain('景点评分条图')
    const bars = container.querySelectorAll('[data-bar-width]')
    expect(bars).toHaveLength(2)
    expect(Number(bars[0].getAttribute('data-bar-width'))).toBeCloseTo(86.4)
    expect(Number(bars[1].getAttribute('data-bar-width'))).toBeCloseTo(61.2)
    expect(container.textContent).toContain('86.4')
    expect(container.textContent).toContain('免费，无需预约')
  })

  it('空榜不渲：data=[] / 组内 items 全空 → null（不占位造空图）', () => {
    expect(render(<VSpotRankBar data={[]} />).container.textContent).toBe('')
    expect(render(<VSpotRankBar data={[{ destination: '大理', items: [] }]} />).container.textContent).toBe('')
  })

  it('K-F2 降级替身：坐标全缺 → 条图顶上、不出现地图白框占位，评分表照常', () => {
    const noCoord = [{ destination: '大理', items: [
      { spot_id: 'a_spot_1', name: '古城', score: 88, matched: false },
      { spot_id: 'a_spot_2', name: '三塔', score: 70, lat: null, lng: null },
    ] }]
    const { container } = render(<VSpotAtlas data={noCoord as never} />)
    expect(container.querySelector('[data-spot-rankbar]')).not.toBeNull()
    expect(container.querySelector('[data-map-placeholder]')).toBeNull()
    expect(container.querySelector('[data-spot-id="a_spot_1"]')).not.toBeNull()
  })

  it('SP-4 联动：VSpotAtlas 有可定位实体时地图与条图并存（条图恒出）', () => {
    vi.stubEnv('VITE_BAIDU_AK', '') // 无 AK：BMapBlock 自有说明位，条图仍恒出
    const withCoord = [{ destination: '大理', items: [
      { spot_id: 'b_spot_1', name: '古城', score: 90, matched: true, lat: 25.69, lng: 100.16 },
    ] }]
    const { container } = render(<VSpotAtlas data={withCoord as never} />)
    expect(container.querySelector('[data-spot-rankbar]')).not.toBeNull()
    vi.unstubAllEnvs()
  })
})

/* ── K-F3 美食榜卡：字段齐 + 缺字段逐项回落 ───────────────── */
describe('K-F3 美食榜卡', () => {
  it('字段齐：名次/名称/品类 chip/人均 chip/评分条（0-10 归一）/理由', () => {
    const { container } = render(<VFoodRanking data={[{ destination: '大理', items: [
      { food_id: 'f1', name: '破酥粑粑', category: '小吃', price_range: '10-20元', score: 8.6, reason: '现烤出炉' },
    ] }]} />)
    expect(container.textContent).toContain('破酥粑粑')
    expect(container.textContent).toContain('小吃')
    expect(container.textContent).toContain('人均 10-20元')
    expect(container.textContent).toContain('现烤出炉')
    const bar = container.querySelector('[data-food-score]')!
    expect(bar.getAttribute('data-food-score')).toBe('8.6')
    expect((bar as HTMLElement).style.width).toBe('86%')
  })

  it('缺字段回落：无 score → 不渲评分条；无价/类/由 → 对应 chip 缺位，卡壳不崩', () => {
    const { container } = render(<VFoodRanking data={[{ destination: '大理', items: [
      { food_id: 'f1', name: '饵丝' },
      { food_id: 'f2', name: '乳扇', score: 7 },
    ] }]} />)
    expect(container.querySelectorAll('[data-food-card]')).toHaveLength(2)
    expect(container.querySelectorAll('[data-food-score]')).toHaveLength(1) // 仅带分条目有条
    expect((container.querySelector('[data-food-score]') as HTMLElement).style.width).toBe('70%')
    expect(container.textContent).toContain('饵丝')
  })
})

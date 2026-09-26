// @vitest-environment jsdom
/**
 * F2 结构化调研知识渲染（F2-1 ~ F2-4）
 *
 * 覆盖缺口（计划 §5.3 D8）：`VStructured` 的 6 个新渲染器此前**零测试**。
 * 守护契约：
 *   F2-1  6 个类型（guide 三件套 + assessment 三件套）happy path 关键字段可见
 *   F2-2  空数组 / 缺子字段 → 不渲染或不崩（表格缺列回落 '-'）
 *   F2-3  旧报告的**已退役** type（feature_tree / pricing_model / user_persona / swot / 空）
 *         静默跳过；而「后端会发、前端没渲染器」的未知 type 走可见降级
 *         （见 crossEndBlockTypes.test.ts——两者过去被同一个 `return null` 混为一谈）
 *   F2-4  ReportPage 接线：块出现在所属章节内 + 本章信源 [n] 角标 + 图集目的地角标
 *
 * 说明：F2-3 的旧 type 刻意用 `as unknown as StructuredBlockType` 绕过 TS —— 那正是
 * 「后端契约收缩后前端必须容错」的真实输入（旧报告的 data 仍带 feature_tree）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import {
  VStructuredBlock,
  VRoutePlan,
  VStayTable,
  VCostBreakdown,
  VAccessMatrix,
  VAmenityChecklist,
  VRiskProfile,
} from '../components/VStructured'
import type { StructuredBlock, StructuredBlockType } from '../types'
import ReportPage from '../pages/ReportPage'

const { holder } = vi.hoisted(() => ({ holder: { report: {} as Record<string, unknown> } }))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../store/reportStore', () => ({
  useReportStore: () => ({ current: holder.report, loading: false, error: null, load: vi.fn() }),
}))

vi.mock('../lib/api', () => ({
  refineSection: vi.fn(),
  submitFeedback: vi.fn(),
  refineReportEvidence: vi.fn(),
  openTaskStream: vi.fn(() => () => {}),
}))

beforeEach(() => {
  holder.report = {}
})

afterEach(() => {
  cleanup()
})

/* ── F2-1 六件套 happy path（键名与后端 coerce_* 契约一致） ── */

const ROUTE_PLAN = [
  {
    destination: '大理',
    days: [
      {
        day: 1,
        spots: [
          { name: '洱海生态廊道', transport: '包车', duration: '2h', tip: '早 8 点前到人少', eids: ['e_1'] },
        ],
      },
    ],
  },
]

const STAY_OPTIONS = [
  {
    destination: '大理',
    areas: [
      { area: '才村', price_range: '¥300-500', for_whom: '亲子家庭', pros: ['临海'], cons: ['餐饮少'], eids: ['e_2'] },
    ],
  },
]

const COST_BREAKDOWN = [
  {
    destination: '大理',
    items: [{ category: '门票', amount: 500, unit: '元', share: 25, note: '含景区联票', eids: ['e_3'] }],
  },
]

const ACCESS_MATRIX = [
  {
    destination: '成都',
    routes: [{ mode: '高铁', duration: '3h', cost: '¥120', frequency: '每 30 分钟', note: '东站出发', eids: ['e_4'] }],
  },
]

const AMENITY_CHECKLIST = [
  {
    destination: '杭州',
    items: [{ category: '医疗', item: '三甲医院', coverage: 'full', note: '主城区 5 家', eids: ['e_5'] }],
  },
]

const RISK_PROFILE = [
  {
    destination: '海口',
    items: [{ dimension: '台风', level: 'medium', note: '7-9 月高发', eids: ['e_6'] }],
  },
]

describe('F2-1 六个结构化渲染器 happy path', () => {
  it('逐日路线：章节头 + Day 序号 + 景点名/交通/停留/提示', () => {
    render(<VRoutePlan data={ROUTE_PLAN} />)
    expect(screen.getByText('大理 · 逐日路线')).toBeTruthy()
    expect(screen.getByText('Day 1')).toBeTruthy()
    expect(screen.getByText('洱海生态廊道')).toBeTruthy()
    expect(screen.getByText(/交通：包车/)).toBeTruthy()
    expect(screen.getByText(/停留：2h/)).toBeTruthy()
    expect(screen.getByText('早 8 点前到人少')).toBeTruthy()
  })

  it('M3a 一页视图：停靠点挂 data-spot-id/shop-id 实体键并出「美食停靠」徽标；旧数据无键不渲染', () => {
    const { container } = render(<VRoutePlan data={[{ destination: '大理', days: [
      { day: 1, spots: [
        { name: '大理古城', spot_id: '大理_spot_1', transport: '公交：公交1路·约40分钟' },
        { name: '美食停靠：老字号', shop_id: '大理_shop_1', duration: '约1小时' },
      ] },
    ] }]} />)
    expect(container.querySelector('[data-spot-id="大理_spot_1"]')).not.toBeNull()
    expect(container.querySelector('[data-shop-id="大理_shop_1"]')).not.toBeNull()
    expect(screen.getByText('美食停靠')).toBeTruthy()
    // 实体键只挂在真实引用上：景点行不带 shop-id、商铺行不带 spot-id
    expect(container.querySelectorAll('[data-spot-id]')).toHaveLength(1)
    expect(container.querySelectorAll('[data-shop-id]')).toHaveLength(1)
  })

  it('住宿选型：表头 + 区域/价格/适合人群/优劣势（优劣势取前 3 条）', () => {
    render(<VStayTable data={STAY_OPTIONS} />)
    expect(screen.getByText('大理 · 住宿区域选型')).toBeTruthy()
    expect(screen.getByText('价格区间')).toBeTruthy()
    expect(screen.getByText('才村')).toBeTruthy()
    expect(screen.getByText('¥300-500')).toBeTruthy()
    expect(screen.getByText('亲子家庭')).toBeTruthy()
    expect(screen.getByText(/临海.*⚠ 餐饮少/)).toBeTruthy()
  })

  it('花费拆解：金额带单位 + 占比百分号 + 说明', () => {
    render(<VCostBreakdown data={COST_BREAKDOWN} />)
    expect(screen.getByText('大理 · 花费拆解')).toBeTruthy()
    expect(screen.getByText('门票')).toBeTruthy()
    expect(screen.getByText('500元')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getByText('含景区联票')).toBeTruthy()
  })

  it('可达性矩阵：交通方式/耗时/费用/频次/备注', () => {
    render(<VAccessMatrix data={ACCESS_MATRIX} />)
    expect(screen.getByText('成都 · 可达性矩阵')).toBeTruthy()
    expect(screen.getByText('高铁')).toBeTruthy()
    expect(screen.getByText('3h')).toBeTruthy()
    expect(screen.getByText('¥120')).toBeTruthy()
    expect(screen.getByText('每 30 分钟')).toBeTruthy()
    expect(screen.getByText('东站出发')).toBeTruthy()
  })

  it('配套清单：覆盖度 full → 保留条目与分类前缀', () => {
    render(<VAmenityChecklist data={AMENITY_CHECKLIST} />)
    expect(screen.getByText('杭州 · 配套完善度')).toBeTruthy()
    expect(screen.getByText(/三甲医院/)).toBeTruthy()
    expect(screen.getByText(/医疗/)).toBeTruthy()
    expect(screen.getByText('主城区 5 家')).toBeTruthy()
  })

  it('风险画像：等级枚举 low|medium|high 映射中文标签', () => {
    render(<VRiskProfile data={RISK_PROFILE} />)
    expect(screen.getByText('海口 · 风险画像')).toBeTruthy()
    expect(screen.getByText('台风')).toBeTruthy()
    expect(screen.getByText('中')).toBeTruthy() // level: 'medium'
    expect(screen.getByText('7-9 月高发')).toBeTruthy()
  })
})

/* ── F2-2 空态与缺字段容错 ────────────────────────────── */

describe('F2-2 空态与缺字段不崩', () => {
  const ALL_TYPES: StructuredBlockType[] = [
    'route_plan', 'stay_options', 'cost_breakdown',
    'access_matrix', 'amenity_checklist', 'risk_profile',
  ]

  it('block 为空 / data 为空数组 → 什么都不渲染', () => {
    const { container } = render(<VStructuredBlock block={null} />)
    expect(container.textContent).toBe('')

    for (const type of ALL_TYPES) {
      const r = render(<VStructuredBlock block={{ type, data: [] }} />)
      expect(r.container.textContent).toBe('')
      r.unmount()
    }
  })

  it('缺子字段（只有 destination）→ 表头渲染、单元格回落占位不崩', () => {
    for (const type of ALL_TYPES) {
      const r = render(<VStructuredBlock block={{ type, data: [{ destination: '某地' }] }} />)
      expect(r.container.textContent).toContain('某地')
      r.unmount()
    }
  })

  it('未知覆盖度 / 未知风险等级 → 回落 partial / medium 而非空白', () => {
    const amenity = render(
      <VAmenityChecklist data={[{ destination: 'X', items: [{ item: '共享办公', coverage: 'weird' }] }]} />,
    )
    expect(amenity.container.textContent).toContain('共享办公')
    amenity.unmount()

    const risk = render(
      <VRiskProfile data={[{ destination: 'X', items: [{ dimension: '治安', level: 'critical' }] }]} />,
    )
    expect(risk.container.textContent).toContain('治安')
    expect(risk.container.textContent).toContain('中')
  })
})

/* ── F2-3 旧 structured.type 容错（后端契约已收缩） ───── */

describe('F2-3 旧报告已废弃 type 不渲染不报错', () => {
  const LEGACY = ['feature_tree', 'pricing_model', 'user_persona', 'swot', '']

  it('feature_tree / pricing_model / user_persona 等旧 type → 静默跳过', () => {
    for (const type of LEGACY) {
      const block = {
        type: type as unknown as StructuredBlockType,
        data: [{ destination: '佳沃食品', features: ['a'] }],
      } as StructuredBlock
      // 断言「不抛异常」：render 返回即说明分发未崩
      const r = render(<VStructuredBlock block={block} />)
      expect(r.container.textContent).toBe('')
      r.unmount()
    }
  })
})

/* ── F2-4 ReportPage 接线（章节内块 + 信源角标 + 图集角标） ── */

describe('F2-4 ReportPage 接线', () => {
  function makeReport() {
    return {
      id: 'r1',
      title: '大理 5 天亲子游攻略',
      subtitle: '基于 12 条联网证据',
      research_type: 'guide',
      created_at: '2026-09-16T22:27:49',
      experts: [],
      toc: [],
      claims: [],
      evidence: [
        // evIndex 以 evidence_id 为键（章节级溯源角标用它算序号）
        { id: 'e_1', evidence_id: 'e_1', title: '来源一', url: 'https://example.com/1', domain: 'example.com' },
        { id: 'e_2', evidence_id: 'e_2', title: '来源二', url: 'https://example.com/2', domain: 'example.com' },
      ],
      figures: [
        {
          src: 'https://cdn.example.com/a.jpg',
          title: '洱海实景',
          source_url: 'https://example.com/a',
          destination: '大理',
        },
      ],
      sections: [
        {
          id: 'route',
          title: '逐日路线',
          level: 2,
          paragraphs: ['正文'],
          structured: { type: 'route_plan', data: ROUTE_PLAN },
          source_evidence_ids: ['e_1', 'e_2'],
        },
      ],
      glossary: [],
      trace: [],
    }
  }

  function renderReport() {
    holder.report = makeReport()
    return render(
      <MemoryRouter initialEntries={['/report/r1']}>
        <Routes>
          <Route path="/report/:reportId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('结构化块渲染在所属章节内，且章节信源角标用证据序号', () => {
    const { container } = renderReport()
    const section = container.querySelector('[data-section-id="route"]')
    expect(section).not.toBeNull()
    expect(section?.textContent).toContain('大理 · 逐日路线')
    expect(section?.textContent).toContain('洱海生态廊道')
    // 本章信源 [1] [2]（evIndex 序号，非证据原 id）
    expect(section?.textContent).toContain('本章信源')
    expect(section?.textContent).toContain('[1]')
    expect(section?.textContent).toContain('[2]')
  })

  it('实景图集渲染目的地角标', () => {
    const { container } = renderReport()
    const figSection = container.querySelector('#sec-figures')
    expect(figSection).not.toBeNull()
    expect(figSection?.textContent).toContain('大理')
    expect(figSection?.textContent).toContain('洱海实景')
  })

  it('旧报告（无 research_type / 章节带废弃 structured）不崩', () => {
    // 显式宽松类型：旧报告的 sections 形状不受当前契约约束（structured.data 是旧结构）
    const legacy: Record<string, unknown> = {
      ...makeReport(),
      research_type: undefined,
      sections: [
        {
          id: 'feature',
          title: '功能对比',
          level: 2,
          paragraphs: ['旧正文'],
          structured: {
            type: 'feature_tree' as unknown as StructuredBlockType,
            data: [{ destination: '佳沃食品' }],
          },
          source_evidence_ids: [],
        },
      ],
    }
    holder.report = legacy
    const { container } = render(
      <MemoryRouter initialEntries={['/report/r1']}>
        <Routes>
          <Route path="/report/:reportId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(container.textContent).toContain('旧正文')
    expect(container.textContent).not.toContain('佳沃食品')
  })
})

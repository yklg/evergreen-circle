import { describe, it, expect } from 'vitest'
import { briefText, stripRefs, BRIEF_BUDGET, BRIEF_SLACK } from '../textBrief'
import { chapterMapLeaves, dataLabels, isSubstringOf } from '../chapterMap'
import type { ReportSection } from '../../types'

/** §6.6.4 断言 ②：不得出现内部编号 */
const LEAK_RE = /\b(c_|e_|L2-)[0-9a-z]/i

describe('stripRefs（引用剥离）', () => {
  it('剥离单个 [e_x]', () => {
    expect(stripRefs('判断成立[e_a968e0ad]')).toBe('判断成立')
  })
  it('剥离逗号并列 [e_a,e_b,e_z]（ch5 真实形态，单正则会漏）', () => {
    expect(stripRefs('佳沃18mm+大果券后106.6元[e_a968e0ad,e_b48ed6ba,e_df59c2dd]')).toBe(
      '佳沃18mm+大果券后106.6元'
    )
  })
  it('剥离连写 [e_x][e_y] 与全角括号', () => {
    expect(stripRefs('A【e_a1b2c3d4】B[e_a1b2c3d4][e_b1b2c3d4]')).toBe('AB')
  })
})

describe('briefText（分句边界抽取）', () => {
  const raw =
    '佳沃18mm+大果券后106.6元，比自家14mm+的119.8元还便宜13.2元——所谓"果径定级"的规格溢价叙事，在真实成交价面前已经破产，它的定价中枢其实是满减券。'

  it('短句原样返回', () => {
    expect(briefText('竞争降维为供应链成本战', BRIEF_BUDGET)).toBe('竞争降维为供应链成本战')
  })

  it('保留完整分句，不切在数字/英文中间（SLACK=6 的意义）', () => {
    const out = briefText(raw, BRIEF_BUDGET)
    expect(out.startsWith('佳沃18mm+大果券后106.6元')).toBe(true)
    expect(out.endsWith('…') && /[\d]…$/.test(out)).toBe(false) // 省略号不贴着数字
  })

  it('回归：拼接用各分句自己的尾随标点（顿号不被改写为逗号）', () => {
    const out = briefText('既有鲜果，又有深加工、礼盒、原料三条辅线，还有渠道账期优势', 12)
    expect(out).toBe('既有鲜果，又有深加工') // 首段尾随「，」原样保留，未归一化
    const out14 = briefText('既有鲜果，又有深加工、礼盒、原料三条辅线，还有渠道账期优势', 14)
    expect(out14).toBe('既有鲜果，又有深加工、礼盒') // 原文顿号原样保留
  })

  it('回归：时间状语开头的长句不会只剩碎片', () => {
    const out = briefText('未来1-2年，蓝莓赛道将从品牌溢价竞争切换为单位成本与产地卡位的淘汰赛', 34)
    expect(out.length).toBeGreaterThan(10)
    expect(out.startsWith('未来1-2年')).toBe(true)
  })

  it('回归：破折号是合法断点', () => {
    const out = briefText('佳沃是唯一坐稳品类王者的玩家——靠全产业链布局而非成本优势', 16)
    expect(out.startsWith('佳沃是唯一坐稳品类王者的玩家')).toBe(true)
  })

  it('回归：截断点回退到括号之前，不落进未闭合括号内', () => {
    // 括号在句中：截断点安全回退到「（」之前
    const out = briefText('在真实成交价面前（所谓果径定级）叙事已经破产，定价中枢其实是满减券', 14)
    expect(out).toBe('在真实成交价面前…')
    expect(out).not.toContain('（')
    // 品牌名括号整体在容差内：完整保留（不切在括号中间）
    const out2 = briefText('鑫荣懋（Joy Wing Mau）是山姆、永辉背后的供应商，渠道议价能力强', 14)
    expect(out2.startsWith('鑫荣懋（Joy Wing Mau）是山姆')).toBe(true)
  })
})

describe('chapterMapLeaves（分支白名单 v4.1）', () => {
  const mk = (over: Partial<ReportSection>): ReportSection => ({
    id: 's1',
    title: '测试章',
    level: 1,
    ...over,
  })

  it('只渲染四类内容分支：无 charts / 信源', () => {
    const sec = mk({
      key_takeaway: '判断',
      highlights: ['亮点'],
      claims: [
        {
          claim_id: 'c_x1',
          text: '论点[e_a1b2c3d4,e_b2c3d4e5]',
          field: 'f',
          evidence_ids: ['e_a1b2c3d4'],
          confidence: 'high',
          cross_validated: true,
          author: 'L2-001',
        },
      ],
      charts: [{ chart_id: 'ch1', type: 'bar', title: '图', data: {} }] as never,
      data_grid: null,
    })
    const B = chapterMapLeaves(sec)
    expect(B.map((b) => b.label)).toEqual(['核心判断', '关键亮点', '核心论点'])
    // L2：无内部编号泄漏；引用并列写法已剥离
    for (const b of B) for (const l of b.leaves) expect(LEAK_RE.test(l.text)).toBe(false)
    expect(B[2].leaves[0].text).toBe('论点')
    expect(B[2].leaves[0].badge).toBe('已交叉验证')
  })

  it('全空但有正文 → 降级为正文计数（ch13 真实形态）', () => {
    const B = chapterMapLeaves(mk({ paragraphs: Array(8).fill('p'), charts: [{ chart_id: 'c', type: 't', data: {} }] as never }))
    expect(B).toHaveLength(1)
    expect(B[0].label).toBe('正文')
    expect(B[0].leaves[0].text).toBe('8 段 · 1 图')
  })

  it('全空且无正文 → 不渲染（返回空）', () => {
    expect(chapterMapLeaves(mk({}))).toHaveLength(0)
  })

  it('每条叶子满足 L1′（原文子串 / 省略号前缀）、L2、预算 ≤34+6', () => {
    const rawHl = '佳沃18mm+大果券后106.6元，比自家14mm+的119.8元还便宜13.2元——所谓"果径定级"的规格溢价叙事，在真实成交价面前已经破产'
    const B = chapterMapLeaves(
      mk({
        key_takeaway: rawHl,
        highlights: [rawHl],
        claims: [
          {
            claim_id: 'c_x',
            text: rawHl,
            field: 'f',
            evidence_ids: [],
            confidence: 'high',
            cross_validated: false,
            author: 'L2-001',
          },
        ],
      })
    )
    for (const b of B) {
      for (const l of b.leaves) {
        expect(l.text.length).toBeLessThanOrEqual(BRIEF_BUDGET + BRIEF_SLACK)
        expect(LEAK_RE.test(l.text)).toBe(false)
        expect(isSubstringOf(rawHl, l.text)).toBe(true)
      }
    }
  })
})

describe('dataLabels（§6.0.5 三个实测 bug 的回归）', () => {
  it('公共后缀不切进未闭合括号；嵌套括号无孤立残留', () => {
    const r = dataLabels(['鑫荣懋（Joy Wing Mau） 市场份额', '佳沃（300268） 市场份额'])
    expect(r.kind).toBe('cols')
    expect(r.note).toBe('市场份额')
    expect(r.labels.join()).not.toContain('）')
  })

  it('满矩阵只列分组名 + 维度规模，不逐行铺值', () => {
    const groups = ['大理', '丽江', '香格里拉', '泸沽湖']
    const dims = ['交通', '住宿', '景点', '美食', '花费', '季节', '口碑']
    const rows = groups.flatMap((b) => dims.map((d) => `${b}·${d}`))
    const r = dataLabels(rows)
    expect(r.kind).toBe('matrix')
    expect(r.labels).toEqual(groups)
  })

  it('头部统一 → 注记 + 尾部标签', () => {
    const r = dataLabels(['云南蓝莓产地价·集中上市前', '云南蓝莓产地价·集中上市后'])
    expect(r.kind).toBe('rows')
    expect(r.note).toBe('云南蓝莓产地价')
    expect(r.labels).toEqual(['集中上市前', '集中上市后'])
  })
})

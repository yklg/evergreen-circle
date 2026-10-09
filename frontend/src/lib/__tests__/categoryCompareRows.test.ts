// 笔1 · 逐类目差距的取值出口（lib 侧）
//
// 这个出口守的是"两种空值不许塌成同一行"与"门槛口径的三档事实不许塌成 0"。
// 页面侧的渲染判据在 `src/__tests__/comparePage.test.tsx`；这里只钉取值，
// 因为配对/取整/缺席判定一旦写错，页面怎么渲染都是错的 —— 分开测才归因得动。
import { describe, it, expect } from 'vitest'

import { categoryCompareRows, lcCompareCaliberGapNote } from '../livingCircle'
import { SAMPLE_COMMUNITIES } from '../../mocks/livingCircleMock'
import type { LivingCircleReport } from '../../types'

const byId = (id: string) => SAMPLE_COMMUNITIES.find((c) => c.id === id)!.report
const EV2 = byId('kaili-ev2')
const JINSONG = byId('beijing-jinsong')

/** 造一份最小载荷：只带类目与场景名，够这两个出口用。 */
function withCats(name: string, cats: unknown[]): LivingCircleReport {
  return { scene: { name }, poi: { categories: cats } } as unknown as LivingCircleReport
}

describe('categoryCompareRows（笔1 取值出口）', () => {
  it('夹具前提自证：ev2 整份没发门槛键、劲松发了；两种空值形态各占一类（漂了本条就白测）', () => {
    const ev2Elder = EV2.poi.categories.find((c) => c.category === 'elderly')!
    const jinElder = JINSONG.poi.categories.find((c) => c.category === 'elderly')!
    expect('required_in_circle' in ev2Elder).toBe(false)
    expect('required_in_circle' in JINSONG.poi.categories[1]).toBe(true)
    // 凯里养老：一个都没有 ⇒ 后端不给最近耗时
    expect(ev2Elder.total).toBe(0)
    expect(ev2Elder.min_minutes ?? null).toBe(null)
    // 劲松养老：有 2 家但全在圈外 ⇒ 最近耗时有值
    expect(jinElder.total).toBeGreaterThan(0)
    expect(jinElder.in_circle).toBe(0)
    expect(jinElder.min_minutes).not.toBeNull()
  })

  it('行数与行名取自两份载荷的类目并集，顺序按 A 侧（不是前端硬编码名单）', () => {
    const rows = categoryCompareRows(EV2, JINSONG)
    expect(rows.map((r) => r.category)).toEqual(EV2.poi.categories.map((c) => c.category))
    expect(rows.map((r) => r.label)).toEqual(EV2.poi.categories.map((c) => c.label))
  })

  it('配对按类别键、不按数组下标：把 B 侧类目顺序打乱，每行仍是同类目对同类目', () => {
    const shuffled = { ...JINSONG, poi: { ...JINSONG.poi, categories: [...JINSONG.poi.categories].reverse() } }
    const plain = categoryCompareRows(EV2, JINSONG)
    const mixed = categoryCompareRows(EV2, shuffled)
    expect(mixed.map((r) => r.b?.total)).toEqual(plain.map((r) => r.b?.total))
    // 反面半边：若实现按下标配对，打乱后必然错位 —— 这条断言就是抓它的
    expect(plain.some((r) => r.a?.total !== r.b?.total)).toBe(true)
  })

  it('B 侧多出来的类别追加在末尾，A 侧为 null（不是 0）', () => {
    const a = withCats('甲', [{ category: 'market', label: '菜市场', total: 3, in_circle: 1, min_minutes: 4 }])
    const b = withCats('乙', [
      { category: 'market', label: '菜市场', total: 5, in_circle: 2, min_minutes: 6 },
      { category: 'clinic', label: '诊所', total: 7, in_circle: 7, min_minutes: 2 },
    ])
    const rows = categoryCompareRows(a, b)
    expect(rows.map((r) => r.category)).toEqual(['market', 'clinic'])
    expect(rows[1].a).toBe(null)
    expect(rows[1].b?.total).toBe(7)
  })

  it('差值先取整到一位小数再返回：屏上印的就是被减出来的那个数', () => {
    const a = withCats('甲', [{ category: 'market', label: '菜市场', total: 3, in_circle: 1, min_minutes: 7.44 }])
    const b = withCats('乙', [{ category: 'market', label: '菜市场', total: 5, in_circle: 2, min_minutes: 13.94 }])
    const [row] = categoryCompareRows(a, b)
    expect(row.deltaMin).toBe(6.5)
    expect(String(row.deltaMin)).toBe('6.5')
  })

  it('任一侧没有最近耗时 ⇒ deltaMin 为 null，调用方不得拿 0 去比', () => {
    const a = withCats('甲', [{ category: 'elderly', label: '养老', total: 0, in_circle: 0, min_minutes: null }])
    const b = withCats('乙', [{ category: 'elderly', label: '养老', total: 2, in_circle: 0, min_minutes: 19.9 }])
    const [row] = categoryCompareRows(a, b)
    expect(row.a?.minMinutes).toBe(null)
    expect(row.b?.minMinutes).toBe(19.9)
    expect(row.deltaMin).toBe(null)
  })

  it('门槛口径三档分明：整份没发键 / 发了但这类未建表 / 有门槛项数 —— 都不许塌成 0', () => {
    const a = withCats('甲', [
      { category: 'market', label: '菜市场', total: 3, in_circle: 1, min_minutes: 4 },
    ])
    const b = withCats('乙', [
      { category: 'market', label: '菜市场', total: 5, in_circle: 2, min_minutes: 6, required_in_circle: null },
      { category: 'clinic', label: '诊所', total: 1, in_circle: 1, min_minutes: 3, required_in_circle: 8, scored_as: ['诊所'] },
    ])
    const rows = categoryCompareRows(a, b)
    expect(rows[0].a?.required).toBe('absent')
    expect(rows[0].b?.required).toBe('none')
    expect(rows[1].b?.required).toBe(8)
    expect(rows[1].b?.scoredAs).toEqual(['诊所'])
    expect(rows[1].a).toBe(null)
  })
})

describe('lcCompareCaliberGapNote（并排时那句"一侧整份没发过口径"）', () => {
  it('只有一侧发过 ⇒ 出句，且点名"没发的那一份"与两份场景名', () => {
    const note = lcCompareCaliberGapNote(EV2, JINSONG)
    expect(note).not.toBeNull()
    expect(note).toContain('没发过门槛项口径')
    expect(note).toContain(EV2.scene.name)
    expect(note).toContain(JINSONG.scene.name)
  })

  it('两侧都发过 ⇒ 不出句（不许把"都按门槛计"说成差异）', () => {
    expect(lcCompareCaliberGapNote(JINSONG, JINSONG)).toBe(null)
  })

  it('两侧都没发过 ⇒ 也不出句（沉默是对的，没得比）', () => {
    const bare = withCats('裸件', [{ category: 'market', label: '菜市场', total: 3, in_circle: 1, min_minutes: 4 }])
    expect(lcCompareCaliberGapNote(bare, { ...bare, scene: { name: '裸件二' } } as LivingCircleReport)).toBe(null)
  })
})

// 词云布局纯函数的守卫（词云口碑化架构修复计划 v7 · 步骤 0 安全网 → 步骤 7 改造后定稿）。
//
// 为什么先补这个：wordcloudLayout.ts 是纯函数却此前零单测，而修复计划步骤 7 要把它
// 的字号归一从「全集合一个 min/max」改成「按 tier 各自归一」——改的正是这个无测函数。
// 本文件先冻结**当时的行为**作特征化基线，步骤 7 落地时按基线的 ⚠️ 指示改写为分层断言。
//
// 现状关键事实（构成下面断言的依据）：
//   · 载荷无 kind（存量报告）⇒ 单档归一：按 weight 降序、全体共用 min/max（42/14）
//   · 载荷带 kind ⇒ 分档归一：opinion 18–44、topic 12–15，评价词先排占螺旋中心
//   · 无随机数 ⇒ 同输入必同输出
import { describe, it, expect } from 'vitest'
import { layoutWords, type WordItem } from '../wordcloudLayout'

const W = 640
const H = 280

// 权重互异：可断言到坐标的完全一致性（同权重并列时螺旋下标会变，坐标不具可比性）
const DISTINCT: WordItem[] = [
  { word: '大理', weight: 309 },
  { word: '洱海', weight: 116 },
  { word: '古城', weight: 114 },
  { word: '美好', weight: 4 },
  { word: '惊喜', weight: 3 },
  { word: '值得去', weight: 1 },
]

// 同一载荷、同一权重，只补上后端算出的分层归属
const LAYERED: WordItem[] = DISTINCT.map((w) =>
  ['大理', '洱海', '古城'].includes(w.word) ? { ...w, kind: 'topic' as const } : { ...w, kind: 'opinion' as const }
)

function sizeOf(placed: { word: string; fontSize: number }[], word: string): number {
  const hit = placed.find((p) => p.word === word)
  if (!hit) throw new Error(`未渲染出「${word}」`)
  return hit.fontSize
}

describe('layoutWords · 确定性（I1）', () => {
  it('权重互异时，打乱入参顺序 → 输出坐标与字号逐项完全一致', () => {
    const forward = layoutWords(DISTINCT, W, H)
    const reversed = layoutWords([...DISTINCT].reverse(), W, H)
    expect(reversed).toEqual(forward)
  })

  it('分层载荷同样确定性：打乱入参 → 输出逐项一致', () => {
    expect(layoutWords([...LAYERED].reverse(), W, H)).toEqual(layoutWords(LAYERED, W, H))
  })

  it('重复调用同一输入 → 输出逐项一致（无隐藏随机源/无模块级可变状态）', () => {
    const a = layoutWords(DISTINCT, W, H)
    const b = layoutWords(DISTINCT, W, H)
    expect(b).toEqual(a)
  })

  it('同权重并列：字号映射稳定（坐标允许随入参顺序变化）', () => {
    // 带上下锚点，使并列词的字号落在插值中段而非退化到端点
    const tied: WordItem[] = [
      { word: '喜洲', weight: 8 },
      { word: '沙溪', weight: 8 },
      { word: '双廊', weight: 8 },
      { word: '苍山', weight: 100 },
      { word: '出片', weight: 1 },
    ]
    const map = (rows: WordItem[]) =>
      Object.fromEntries(layoutWords(rows, W, H).map((p) => [p.word, p.fontSize]))
    const sizes = map(tied)
    expect(map([...tied].reverse())).toEqual(sizes)
    // 并列三者字号相同，且确实落在两端之间（证明插值生效而非被端点短路）
    expect(sizes['喜洲']).toBe(sizes['沙溪'])
    expect(sizes['沙溪']).toBe(sizes['双廊'])
    expect(sizes['出片']).toBeLessThan(sizes['喜洲'])
    expect(sizes['喜洲']).toBeLessThan(sizes['苍山'])
  })
})

describe('layoutWords · 单档归一（kind 缺席 = 存量报告，须与分层改造前逐位相同）', () => {
  it('全体共用单一 min/max：最高权重取上限、最低权重取下限', () => {
    const placed = layoutWords(DISTINCT, W, H, 42, 14)
    expect(sizeOf(placed, '大理')).toBe(42)
    expect(sizeOf(placed, '值得去')).toBe(14)
  })

  it('字号随 weight 严格单调不增，且渲染顺序即 weight 降序', () => {
    const placed = layoutWords(DISTINCT, W, H)
    expect(placed.map((p) => p.word)).toEqual(['大理', '洱海', '古城', '美好', '惊喜', '值得去'])
    const sizes = placed.map((p) => p.fontSize)
    for (let i = 1; i < sizes.length; i++) expect(sizes[i]).toBeLessThanOrEqual(sizes[i - 1])
  })

  it('空输入 → 空表，不抛（调用方据此不产图）', () => {
    expect(layoutWords([], W, H)).toEqual([])
  })
})

describe('layoutWords · 分层归一（步骤 7：评价词大字、话题词小灰字垫背景）', () => {
  // 本块取代步骤 0 那条「现状缺陷」特征化断言 —— 它钉的是同一个病灶，方向反过来：
  // 改造前「地名 309 次把评价词压到 14px」，改造后「地名再高频也压不到评价档的下限」。
  it('话题档的 weight 再大，也压不动评价档的字号下限', () => {
    const placed = layoutWords(LAYERED, W, H)
    expect(sizeOf(placed, '值得去')).toBe(18) // opinion 档下限
    expect(sizeOf(placed, '大理')).toBe(15) // topic 档上限
    expect(sizeOf(placed, '值得去')).toBeGreaterThan(sizeOf(placed, '大理'))
  })

  it('各档按本档跨度归一：评价档最高权重取 44，话题档最高权重取 15', () => {
    const placed = layoutWords(LAYERED, W, H)
    expect(sizeOf(placed, '美好')).toBe(44) // opinion 档内最高（4 次）
    expect(sizeOf(placed, '大理')).toBe(15) // topic 档内最高（309 次）
    expect(sizeOf(placed, '惊喜')).toBeGreaterThan(sizeOf(placed, '值得去'))
  })

  it('渲染顺序：评价词整体先排（占螺旋中心），档内仍按 weight 降序', () => {
    expect(layoutWords(LAYERED, W, H).map((p) => p.word)).toEqual([
      '美好', '惊喜', '值得去', '大理', '洱海', '古城',
    ])
  })

  it('档内全等（真实小语料的常态：文档频次几乎都是 1）→ 取该档下限，不抛不塌陷', () => {
    const flat: WordItem[] = [
      { word: '清净', weight: 1, kind: 'opinion' },
      { word: '出片', weight: 1, kind: 'opinion' },
      { word: '大理', weight: 7, kind: 'topic' },
    ]
    const placed = layoutWords(flat, W, H)
    expect(sizeOf(placed, '清净')).toBe(18)
    expect(sizeOf(placed, '出片')).toBe(18)
  })

  it('混合载荷里缺 kind 的条目按话题档处理（不因脏数据崩，也不冒充评价词）', () => {
    const mixed: WordItem[] = [
      { word: '美好', weight: 4, kind: 'opinion' },
      { word: '某地', weight: 9 },
      { word: '他地', weight: 3 },
    ]
    const placed = layoutWords(mixed, W, H)
    expect(sizeOf(placed, '美好')).toBe(18) // 评价档下限
    expect(sizeOf(placed, '某地')).toBe(15) // 无 kind ⇒ 话题档上限
    expect(sizeOf(placed, '他地')).toBe(12)
    // 权重 9 > 4 却排得进话题档：归属由后端 kind 决定，不由权重决定
    expect(placed.map((p) => p.word)).toEqual(['美好', '某地', '他地'])
  })
})

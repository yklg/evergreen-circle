// @vitest-environment node
/**
 * 分隔式清单输入解析（计划 v3 §二 F1 · `lib/listInput`）。
 *
 * 这块被澄清页（自定义目的地）和首页（用户指定信源）共用，因此它的等价类是**跨功能**的：
 * 分隔符集合、去重、以及「超限必须回报而不是静默丢」。最后一条是本模块存在的理由 ——
 * 静默少一条在界面上表现为"我填了 12 条、系统只读 10 条却不说"，属于本项目点名禁止的形状。
 */
import { describe, it, expect } from 'vitest'
import { splitListItems, mergeListItems } from '../lib/listInput'

describe('splitListItems · 分隔口径', () => {
  it('逗号 / 中文逗号 / 顿号 / 空白（含换行）都算分隔', () => {
    expect(splitListItems('a,b，c、d e\nf')).toEqual(['a', 'b', 'c', 'd', 'e', 'f'])
  })

  it('连续分隔符与首尾空白不产生空项', () => {
    expect(splitListItems('  https://a.x ,, https://b.x ')).toEqual(['https://a.x', 'https://b.x'])
    expect(splitListItems('')).toEqual([])
    expect(splitListItems('   ')).toEqual([])
  })
})

describe('mergeListItems · 去重与可见截断', () => {
  it('重复项不新增（按已有值判重，保持先来后到）', () => {
    const r = mergeListItems(['https://a.x'], 'https://a.x https://b.x', 10)
    expect(r.items).toEqual(['https://a.x', 'https://b.x'])
    expect(r.added).toBe(1)
    expect(r.dropped).toBe(0)
  })

  it('超出 limit 时逐条计 dropped，而不是静默收下', () => {
    const r = mergeListItems(['u1', 'u2'], 'u3 u4 u5', 3)
    expect(r.items).toEqual(['u1', 'u2', 'u3'])
    expect(r.dropped).toBe(2)
  })

  it('不传 limit ⇒ 不截断（澄清页目的地选择不受 10 条约束）', () => {
    const many = Array.from({ length: 30 }, (_, i) => `d${i}`).join(' ')
    const r = mergeListItems([], many)
    expect(r.items.length).toBe(30)
    expect(r.dropped).toBe(0)
  })

  it('重复项不占额度：已有 9 条时再贴 3 条全重复 + 1 条新增，仍收 1 条', () => {
    const existing = Array.from({ length: 9 }, (_, i) => `u${i}`)
    const r = mergeListItems(existing, 'u0 u1 u2 new1', 10)
    expect(r.items.length).toBe(10)
    expect(r.added).toBe(1)
    expect(r.dropped).toBe(0)
  })
})

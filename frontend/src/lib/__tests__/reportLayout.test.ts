// 左侧目录链接样式的唯一来源 —— 守护 active/非 active 分支与字号层级（text-aux）
// 该字符串与 ReportPage / LifeCircleReportView 共用：任何分支变更会同时影响两个页面的左目录。
import { describe, it, expect } from 'vitest'
import { tocLinkCls } from '../reportLayout'

const BASE = 'flex w-full items-start gap-2.5 rounded-btn px-3 py-2 text-left text-aux transition-colors'

describe('tocLinkCls · 左侧目录链接样式（单一来源）', () => {
  it('两分支共享同一基础样式串（含导航字号 text-aux，防止字号漂移）', () => {
    expect(tocLinkCls(true)).toContain(BASE)
    expect(tocLinkCls(false)).toContain(BASE)
    expect(tocLinkCls(true)).toContain('text-aux')
    expect(tocLinkCls(false)).toContain('text-aux')
    // 目录不得回退到 label/tag 字号
    for (const c of [tocLinkCls(true), tocLinkCls(false)]) {
      expect(c).not.toContain('text-tag')
    }
  })

  it('active 分支 = 主色浅底 + 加粗 + 主题字', () => {
    expect(tocLinkCls(true)).toContain('bg-primary-tint font-medium text-primary-deep')
  })

  it('非 active 分支 = hover 弱高亮，且不加粗（与 active 区分）', () => {
    const c = tocLinkCls(false)
    expect(c).toContain('hover:bg-primary-tint/50')
    expect(c).not.toContain('font-medium')
    expect(c).not.toContain('bg-primary-tint font-medium')
  })
})
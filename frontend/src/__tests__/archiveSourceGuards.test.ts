/**
 * D5 · 归档入口唯一性守卫（路线乙：本分支自建等效锁）
 *
 * 为什么要在这里重造一遍 domainpack 的守卫：架构评审确认「历史」与「报告」是
 * 同一份数据的两套列表实现（同一 `GET /api/life-circle` + 同一 mock 被两页各自消费），
 * 而删掉历史页的难点在于「聚合统计与列表导航耦合在同一路由上」——不钉住文件级现状，
 * 收敛会在下一次改动里静默回退。判据形状直接对齐
 * `wip/domainpack:frontend/src/__tests__/archiveSourceGuards.test.ts:62-78`：
 * 三条都钉，**且必须同时钉 `/library` 半边**（v2 计划只钉了 `/dashboard`，漏掉
 * 「我的调研」= 第二个归档入口仍在）。
 *
 * 波次 A4 落地后本文件已从挂账转为**防回退**：四条判据全部转正（曾经的 `it.fails`
 * 是 `xfail(strict)` 的前端对应物，落地即报失败逼摘标记，先例
 * `visitorUnrated.test.tsx:121-122`）。长期保留 —— 只要有人重新注册这两条路由、
 * 或把页面文件以兼容垫片的名义请回来，这里就会红。
 *
 * 注意：`vsidebarRoutes.test.tsx` 的 B3 只按归档名白名单过滤后断言，新起名「情报中心」
 * 并不触发它 ⇒ 它不防第二归档，不可当本条防线引用（架构评审 v4 事实 1）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')

const read = (rel: string): string => readFileSync(join(SRC, rel), 'utf8')

describe('归档入口唯一性（防回退：报告中心是唯一归档）', () => {
  it('正面对照：本守卫读到的是真实源文件，不是空串或错路径', () => {
    // 路径写错时 `not.toMatch` 会在 readFileSync 处直接抛；而"文件已删"类判据以
    // `toThrow` 为通过条件，一旦 SRC 指错就会**假绿**。所以先独立钉一条可达性判据
    // （先例 conftest.py:40「证明门真的有牙」）。
    const app = read('App.tsx')
    const sidebar = read('layout/VSidebar.tsx')
    expect(app).toContain('<Route')
    expect(sidebar).toContain('工作台')
    expect(sidebar).toContain('navItems')
  })

  it('App.tsx 不再注册 /dashboard 与 /library 两条归档路由', () => {
    const text = read('App.tsx')
    expect(text).not.toMatch(/path="\/dashboard"/)
    expect(text).not.toMatch(/path="\/library"/)
  })

  it('App.tsx 源码里不残留 DashboardPage / LibraryPage 字样（不留兼容垫片）', () => {
    expect(read('App.tsx')).not.toMatch(/DashboardPage|LibraryPage/)
  })

  it('两个旧归档页面文件已不存在', () => {
    expect(() => read('pages/DashboardPage.tsx')).toThrow()
    expect(() => read('pages/LibraryPage.tsx')).toThrow()
  })

  it('侧栏导航项里不再有「历史」或「体检档案」', () => {
    const text = read('layout/VSidebar.tsx')
    expect(text).not.toMatch(/label:\s*'(历史|体检档案)'/)
    // 唯一归档入口仍在：否则上一条"没有历史"会因为整条导航被删而空过
    expect(text).toMatch(/to:\s*'\/reports'/)
  })
})

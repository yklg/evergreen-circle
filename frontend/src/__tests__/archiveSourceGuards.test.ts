/**
 * D5 · 归档入口唯一性守卫（路线乙：本分支自建等效锁）
 *
 * 为什么要在这里重造一遍 domainpack 的守卫：架构评审确认「历史」与「报告」是
 * 同一份数据的两套列表实现（同一 `GET /api/life-circle` + 同一 mock 被两页各自消费），
 * 而删掉历史页的难点在于「聚合统计与列表导航耦合在同一路由上」——不钉住文件级现状，
 * 收敛会在下一次改动里静默回退。判据形状直接对齐
 * `wip/domainpack:frontend/src/__tests__/archiveSourceGuards.test.ts:62-78`：
 * 三条都钉，**且必须同时钉 `/library` 半边**（v2 计划只钉了 `/dashboard`，漏掉
 * `App.tsx:56` 的「我的调研」= 第二个归档入口仍在）。
 *
 * 为什么用 `it.fails` 而不是直接写正向断言：波次 A 尚未落地，`App.tsx:52,56` 两条路由
 * 与两个页面文件都还在。`it.fails` 是本项目里 `xfail(strict)` 的前端对应物
 * （先例 `visitorUnrated.test.tsx:121-122`）——**删除收敛落地后本文件会主动报失败，
 * 逼着摘标记**，而不是留一套永远绿的空守卫。
 *
 * 注意：`vsidebarRoutes.test.tsx` 的 B3 只按归档名白名单过滤后断言，新起名「情报中心」
 * 并不触发它 ⇒ 它不防第二归档，不可当本条防线引用（架构评审 v4 事实 1）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')

const read = (rel: string): string => readFileSync(join(SRC, rel), 'utf8')

describe('归档入口唯一性（波次 A 落地后摘 it.fails 标记）', () => {
  it('正面对照：本守卫读到的是真实源文件，不是空串或错路径', () => {
    // 若路径写错，下面的 `not.toMatch` 会在 readFileSync 处直接抛 ⇒ 被 it.fails 吞成"通过"。
    // 所以先独立钉一条**必须绿**的可达性判据（先例 conftest.py:40「证明门真的有牙」）。
    const app = read('App.tsx')
    const sidebar = read('layout/VSidebar.tsx')
    expect(app).toContain('<Route')
    expect(sidebar).toContain('工作台')
    expect(sidebar).toContain('navItems')
  })

  it.fails('App.tsx 不再注册 /dashboard 与 /library 两条归档路由', () => {
    const text = read('App.tsx')
    expect(text).not.toMatch(/path="\/dashboard"/)
    expect(text).not.toMatch(/path="\/library"/)
  })

  it.fails('App.tsx 源码里不残留 DashboardPage / LibraryPage 字样（不留兼容垫片）', () => {
    expect(read('App.tsx')).not.toMatch(/DashboardPage|LibraryPage/)
  })

  it.fails('两个旧归档页面文件已不存在', () => {
    expect(() => read('pages/DashboardPage.tsx')).toThrow()
    expect(() => read('pages/LibraryPage.tsx')).toThrow()
  })

  it.fails('侧栏导航项里不再有「历史」或「体检档案」', () => {
    expect(read('layout/VSidebar.tsx')).not.toMatch(/label:\s*'(历史|体检档案)'/)
  })
})

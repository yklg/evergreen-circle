// @vitest-environment node
/**
 * 4b 前端半：时效那句的取数纪律 + `force` 这条通路的形状。
 *
 * 三件事各自都有明确的失败模式在防：
 *  ① 阈值（30 天 / 500m）**只许读 payload 的 `reuse_window`** —— 抄一份进前端，阈值改一次
 *     屏幕上的话就说一次谎，而后端测试全绿（本仓为这个形状立过多次规矩）；
 *  ② 缺 `reuse_window`（升级前落库的存量件、以及**演示态根本不发的件**）⇒ 降级成只报时点与
 *     年龄，不编一个 30 出来；坏时间戳 ⇒ `null`，不印"（NaN 天前）"；
 *  ③ `force` 是"用户点名重测"的唯一记号：不传就**不发这一位**（与 `city/address/travel_mode`
 *     同一条形状纪律），且全站只有一个控件带它 —— 否则"省配额的默认路径"会被某次普通点击
 *     悄悄换成全额重测（那是要花真钱的方向性错误）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { dataAgeDays, freshnessNote, generatedOn } from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

const ROOT = process.cwd()
const WINDOW = { report_ttl_s: 30 * 86400, aux_ttl_s: 7 * 86400, nearby_radius_m: 500 }
const GEN = '2026-09-30T16:00:25.024Z'
const NOW = new Date('2026-10-06T00:00:00Z')

const lc = (over: Partial<LivingCircleReport> = {}): LivingCircleReport =>
  ({ generated_at: GEN, reuse_window: WINDOW, ...over }) as unknown as LivingCircleReport

describe('① 时效那句：数字全部读自 payload', () => {
  it('带着 reuse_window ⇒ 时点、年龄、两个阈值全说得出', () => {
    const s = freshnessNote(lc(), NOW)!
    expect(s).toContain('2026-09-30')
    expect(s).toContain('5 天前')
    expect(s).toContain('30 天')
    expect(s).toContain('500m')
    expect(s).toContain('重新体检')
  })

  it('把窗口改成 7 天 / 600m ⇒ 句子跟着变（证明没有硬编码）', () => {
    const s = freshnessNote(lc({
      reuse_window: { report_ttl_s: 7 * 86400, aux_ttl_s: 3600, nearby_radius_m: 600 },
    } as Partial<LivingCircleReport>), NOW)!
    expect(s).toContain('7 天')
    expect(s).toContain('600m')
    expect(s).not.toContain('30 天')
    expect(s).not.toContain('500m')
  })

  it('缺 reuse_window（存量件与演示件）⇒ 只报时点与年龄，不编阈值', () => {
    const noWindow = freshnessNote(lc({ reuse_window: undefined }) as LivingCircleReport, NOW)!
    expect(noWindow).toBe('数据时点 2026-09-30（5 天前）')
    for (const bad of [null, { report_ttl_s: 0, aux_ttl_s: 0, nearby_radius_m: 0 },
      { report_ttl_s: 30 * 86400, aux_ttl_s: 0, nearby_radius_m: 0 }]) {
      const s = freshnessNote(lc({ reuse_window: bad }) as LivingCircleReport, NOW)!
      expect(s, `坏窗口值 ${JSON.stringify(bad)} 被当成可印的阈值`).not.toContain('天内')
    }
  })

  it('时间戳坏 ⇒ null（宁可不印，也不印一个 NaN 天前）', () => {
    expect(freshnessNote(lc({ generated_at: '不是日期' }) as LivingCircleReport, NOW)).toBeNull()
    expect(freshnessNote(lc({ generated_at: '' }) as LivingCircleReport, NOW)).toBeNull()
    expect(generatedOn(lc({ generated_at: 'x' }) as LivingCircleReport)).toBe('')
    expect(dataAgeDays(lc({ generated_at: 'x' }) as LivingCircleReport, NOW)).toBeNull()
  })

  it('年龄按天向下取整、且不出现负数（客户端时钟比数据还旧时按 0 处理）', () => {
    expect(dataAgeDays(lc(), new Date('2026-10-06T15:00:00Z'))).toBe(5)
    expect(dataAgeDays(lc(), new Date('2026-09-30T16:00:25Z'))).toBe(0)
    expect(dataAgeDays(lc(), new Date('2026-01-01T00:00:00Z'))).toBe(0)
    expect(freshnessNote(lc(), new Date('2026-09-30T18:00:00Z'))).toContain('今天')
  })

  it('两处渲染面都消费它（"发出去了却没人读"的反面）', () => {
    for (const rel of ['src/pages/LifeCirclePage.tsx',
      'src/components/lifecircle/LifeCircleReportView.tsx']) {
      const src = readFileSync(join(ROOT, rel), 'utf-8')
      expect(src, `${rel} 没调 freshnessNote ⇒ 这句上不了屏`).toContain('freshnessNote(')
    }
  })

  it('日期排版只有 `generatedOn` 一颗：打印水印不再自己拼一份', () => {
    const view = readFileSync(join(ROOT, 'src/components/lifecircle/LifeCircleReportView.tsx'), 'utf-8')
    expect(view, '水印那处又自己 getFullYear/padStart 拼了一遍日期 ⇒ 两份实现开始分叉')
      .toContain('generatedOn(lc)')
    expect(view).not.toMatch(/new Date\(lc\.generated_at\)/)
  })
})

describe('② force 通路：不传就不发这一位，全站只有一个入口带它', () => {
  afterEach(() => vi.unstubAllGlobals())

  async function bodyOf(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    vi.resetModules()
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {})
      return new Response(JSON.stringify({ taskId: 't-force' }), { status: 200 })
    }))
    const { createLivingCircleTask } = await import('../lib/api')
    await createLivingCircleTask(input as never)
    expect(calls).toHaveLength(1)
    return JSON.parse(String(calls[0].body)) as Record<string, unknown>
  }

  it('默认（没点名重测）⇒ 载荷里根本没有 force 这个键', async () => {
    const body = await bodyOf({ query: '凯里老街' })
    expect(body).not.toHaveProperty('force')
    expect(body.type).toBe('living_circle')
  })

  it('显式 false ⇒ 同样不发这一位（"没表态"与"表态不重测"在载荷上留同一个形状）', async () => {
    const body = await bodyOf({ query: '凯里老街', force: false })
    expect(body).not.toHaveProperty('force')
  })

  it('force=true ⇒ 发出 `force: true`，键名与后端 CreateTaskBody 逐字一致', async () => {
    const body = await bodyOf({ query: '凯里老街', force: true })
    expect(body.force).toBe(true)
    const backend = readFileSync(join(ROOT, '../backend/app/main.py'), 'utf-8')
    expect(backend, '后端 CreateTaskBody 没声明 force ⇒ extra="forbid" 下这一位会 422')
      .toContain('force: bool = False')
  })

  it('全站只有一个控件能强制重测', () => {
    const page = readFileSync(join(ROOT, 'src/pages/LifeCirclePage.tsx'), 'utf-8')
    const uses = page.split('force: true,\n').length - 1
    expect(uses, `带 \`force: true\` 的调用点有 ${uses} 处 —— 「开始体检」与输入新目标都不该带`)
      .toBe(1)
    // 传递那一处（CTA → flow）也只许有一个形状，且它读的是 `opts.force`：
    // 计数只数正向那一处会放走"把透传写成无条件 payload.force = true"这种改法。
    expect(page.split('opts.force ?').length - 1).toBe(1)
    // 反向钉住"没被顺手加力"的那一处：CTA 的「开始体检」保持不带 force 的原始形状。
    // 只数正向那一条会放走"两处都带"（数到 2 才红，但把 CTA 改成 force:true 同时把
    // 重新体检那处删掉，就还是 1 条 —— 这条负对照堵的就是这个缝）。
    const plain = 'startRealCheck({ pending: customCenter ? { lnglat: customCenter, coordSys: customCoordSys } : undefined })'
    expect(page.split(plain).length - 1, '「开始体检」那处的调用形状变了 ⇒ 默认省配额的路径被动过')
      .toBe(1)
  })

  it('日期按 UTC 排：同一份载荷在 UTC 与 +08 两台机器上印同一个"数据时点"', () => {
    // 时间戳是 `...Z`。用本地读法（`getFullYear`）会让 16:00Z 这一档在 +08 上变成次日，
    // 与同一句里按绝对时刻算出的年龄自相矛盾 —— 这台机器就是 +08，本用例的期望值
    // 若在本地时区下被满足就会在这里红。
    expect(generatedOn(lc())).toBe('2026-09-30')
    const s = freshnessNote(lc(), NOW)!
    expect(s).toContain('2026-09-30')
    expect(s).toContain('5 天前')
  })
})

/**
 * D4b · 静默兜底清单守卫：列表类取数不得用空数组把失败洗成"没有"
 *
 * `safeJson<T>(url, init, fallback)` 的第 3 参在**HTTP 非 2xx 或 JSON 解析失败**时返回，
 * 于是 `fallback = []` 的列表函数把「后端挂了」和「一条记录都没有」压成同一个值
 * （架构评审 v4 事实 7；`reportsPageErrorVsEmpty.test.tsx` 钉的是它的 UI 后果，
 * 这条钉的是它的**源头清单**，防止一边修一边新增）。
 *
 * 判据是**集合相等**，两个方向都钉：
 * - 新增一项 ⇒ 红：又造一个静默兜底；
 * - 少一项也 ⇒ 红：这是**有意的**（去掉兜底要同批更新基线，让债务的减少留下痕迹，
 *   而不是被顺手改掉的静默 diff）。基线里每一项都对应 `wip/domainpack` 已知的待修债。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const API_TS = join(process.cwd(), 'src', 'lib', 'api.ts')

/** 2026-09-27 基线。波次 A 第 3 步去掉了 `fetchLifeCircleReports` / `fetchReports` 两项
 *  （归档列表的失败必须与"没有报告"可分辨，判据见 reportsPageErrorVsEmpty.test.tsx）；
 *  剩余三项是**已登记的债**：订阅列表与专家负载目前还没有活消费方，情报中心落地（波次 B）
 *  时要一并处理，届时本清单继续缩短 —— 清单缩短必须是有意的，故两向都钉。 */
const BASELINE = new Set([
  'fetchSubscriptions', // → /api/subscriptions：情报中心订阅列表（波次 B 处理）
  'fetchWorkload',      // → /api/experts/workload（波次 B 处理）
  'getTaskStatus',      // → 任务状态列表
])

/** 本守卫的覆盖面边界（写清楚，免得日后把它当成全能闸）：只认
 *  `safeJson<T>(url, undefined, [])` 这一族**空数组**兜底。`null` / 对象字面量兜底
 *  （如 `fetchLifeCircleReport(..., null)`）不在本正则内 —— 那是另一类判据，
 *  要扩就先扩正则并同步基线，不要假装它已覆盖。 */

/** 把 api.ts 按导出函数切块，避免跨函数误判。 */
function functionBlocks(src: string): Map<string, string> {
  const blocks = new Map<string, string>()
  for (const chunk of src.split(/(?=export async function )/)) {
    const m = /^export async function ([A-Za-z0-9_]+)/.exec(chunk)
    if (m) blocks.set(m[1], chunk)
  }
  return blocks
}

describe('静默兜底清单（api.ts 列表类取数）', () => {
  it('解析真的跑起来了（判据不许与真实源脱节）', () => {
    const blocks = functionBlocks(readFileSync(API_TS, 'utf8'))
    // 宁可红，不空转：解析不出足量函数说明切块正则失效（先例 backend/tests/test_task_body_contract.py:51）
    expect(blocks.size).toBeGreaterThan(20)
    for (const name of BASELINE) {
      expect(blocks.has(name), `基线里的 ${name} 在 api.ts 中已不存在 —— 判据已与源脱节`).toBe(true)
    }
  })

  it('带空数组兜底的函数集合恰为基线（不新增、也不无声减少）', () => {
    const blocks = functionBlocks(readFileSync(API_TS, 'utf8'))
    const offenders = new Set<string>()
    for (const [name, body] of blocks) {
      if (/,\s*undefined,\s*\[\s*\]\s*\)/.test(body)) offenders.add(name)
    }
    const added = [...offenders].filter((n) => !BASELINE.has(n))
    const removed = [...BASELINE].filter((n) => !offenders.has(n))
    expect(added, `新增了静默兜底（失败会被洗成空列表）：${added.join(', ')}`).toEqual([])
    expect(removed, `兜底已被去掉：请同批把 ${removed.join(', ')} 移出基线，别留两套口径`).toEqual([])
  })
})

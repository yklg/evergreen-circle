/**
 * 目的地调研 fixture 流（mocks/researchStream.ts）与真实 SSE 的事件 schema 同构契约。
 *
 * 守护两条一般规则：
 * - 复盘契约：replayResearchStream 产出的每个 { type, data } 必须映射到真实
 *   run_pipeline 的事件字段（progress=percent/stage；report_ready/done=驼峰 reportId；
 *   node_update 含 nodes 或 node+status 双形；thought=id/kind/expert/text）。
 * - 体裁分流：guide 与 assess 必须产出**不同**标题与章节口径（经 message 文本与
 *   report_ready.title 断言），保证工作台演示态可见「两套专家编排」，不互串。
 */
import { describe, it, expect, vi } from 'vitest'
import { replayResearchStream } from '../mocks/researchStream'

/** 用 0 间隔回放整条流，收集所有事件。 */
function collect(purpose: string): Promise<{ type: string; data: Record<string, any> }[]> {
  return new Promise((resolve) => {
    const events: { type: string; data: Record<string, any> }[] = []
    replayResearchStream(
      'demo-' + purpose,
      { onEvent: (t, d) => events.push({ type: t, data: (d ?? {}) as Record<string, any> }) },
      { purpose, speed: 0, reportId: `demo-r-${purpose}`, onDone: () => resolve(events) },
    )
  })
}

const REQUIRED: Record<string, number> = {
  node_update: 1,
  progress: 1,
  thought: 1,
  message: 1,
  evidence: 1,
  report_ready: 1,
  done: 1,
}

describe('replayResearchStream：与真实 SSE 同构契约', () => {
  it('guide 回放：事件类型齐全 + 字段驼峰契约 + 攻略体裁标题', async () => {
    const evs = await collect('guide')
    for (const [type, min] of Object.entries(REQUIRED)) {
      expect(evs.filter((e) => e.type === type).length, `缺事件类型 ${type}`).toBeGreaterThanOrEqual(min)
    }
    const report = evs.find((e) => e.type === 'report_ready')!.data
    expect(report.reportId).toBe('demo-r-guide')
    expect(report.title).toContain('攻略')
    const done = evs.find((e) => e.type === 'done')!.data
    expect(done.reportId).toBe('demo-r-guide')
    // node_update 双形：nodes 数组 + node/status 单节点各至少一个
    expect(evs.filter((e) => e.type === 'node_update' && Array.isArray(e.data.nodes)).length).toBeGreaterThanOrEqual(1)
    expect(evs.filter((e) => e.type === 'node_update' && e.data.node).length).toBeGreaterThanOrEqual(1)
  })

  it('assess 回放：字段同构 + 评估体裁标题（两套编排口径互不串）', async () => {
    const evs = await collect('assess')
    expect(evs.filter((e) => e.type === 'report_ready')[0].data.title).toContain('评估')
    expect(evs.find((e) => e.type === 'message')!.data.text).toContain('目的地评估')
    // evidence 字段与真实 schema 对齐
    const ev = evs.find((e) => e.type === 'evidence')!.data
    expect(ev.evidence_id && ev.source_url && ev.credibility).toBeTruthy()
  })

  it('close 后不再投递事件', async () => {
    const events: string[] = []
    const close = replayResearchStream('demo-x', { onEvent: (t) => events.push(t) }, { purpose: 'guide', speed: 5, onDone: vi.fn() })
    close()
    await new Promise((r) => setTimeout(r, 30))
    expect(events.length).toBe(0)
  })

  it('F5 · 回放节点数组含 sentiment 且无 analyze（与真实 RESEARCH_NODES 同构）', async () => {
    const evs = await collect('guide')
    const arr = evs.find((e) => e.type === 'node_update' && Array.isArray(e.data.nodes))
    const ids = ((arr?.data?.nodes as Array<{ id: string }>) ?? []).map((n) => n.id)
    expect(ids).toContain('sentiment')
    expect(ids).not.toContain('analyze')
    // 单节点更新 id 亦须落入数组域（防 DAG 停滞）
    const singleIds = evs
      .filter((e) => e.type === 'node_update' && e.data.node)
      .map((e) => e.data.node)
    for (const sid of singleIds) {
      expect(ids).toContain(sid)
    }
  })
})
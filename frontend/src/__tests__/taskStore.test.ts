/**
 * 覆盖拓展方案 FE-5 / FE-6 · taskStore error 事件容错与语义。
 *
 * 被测范围：store/taskStore.ts ingest 的 error 分支（直调 zustand store，不经组件）。
 *
 * - FE-5 🟢 特征化绿：error.data 缺失（undefined，连接失败场景，见 apiTaskStream FE-4）
 *   → 不抛错、落兜底文案「发生未知错误」、running=false。
 *   ⚠️ 勘误登记（2026-09-20）：覆盖方案初判此用例 🔴「TypeError」，系仅 grep :182 单行的误读；
 *   全文阅读发现 ingest 入口 asObj()（taskStore.ts:78-80, :123）已把 undefined 归一 `{}`，
 *   容错成立。按 test-coverage-expander 纪律显式改判 🟢（钉住语义防回归），未静默改口径。
 * - FE-6 🟢 特征化绿：error.data={message} → error=message 且 running=false、finished 不置位。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useTaskStore } from '../store/taskStore'

describe('taskStore · error 事件（FE-5 / FE-6）', () => {
  beforeEach(() => {
    // reset 置 running=true，使 error 分支翻转 running 的效果可观测
    useTaskStore.getState().reset('lc-test', '测试查询')
  })

  it('FE-6 · error{message} → error=message 且 running=false（finished 不置位）', () => {
    useTaskStore.getState().ingest('error', { message: '配额耗尽' })
    const s = useTaskStore.getState()
    expect(s.error).toBe('配额耗尽')
    expect(s.running).toBe(false)
    expect(s.finished).toBe(false)
  })

  it('FE-5 · error data 缺失（undefined，连接失败路径）→ 不抛错 + 兜底文案 + running=false', () => {
    expect(() => useTaskStore.getState().ingest('error', undefined)).not.toThrow()
    const s = useTaskStore.getState()
    expect(s.error).toBe('发生未知错误')
    expect(s.running).toBe(false)
  })

  it('FE-5b · error data 为空对象 {}（缺 message 字段）→ 同样落兜底文案', () => {
    useTaskStore.getState().ingest('error', {})
    expect(useTaskStore.getState().error).toBe('发生未知错误')
  })
})

describe('taskStore · 展示事件 ingest（G6：工作台三栏数据源）', () => {
  beforeEach(() => {
    useTaskStore.getState().reset('t-research', '扫描黄山')
  })

  it('F1 · node_update 数组替换 nodes（权威节点集生效）', () => {
    useTaskStore.getState().ingest('node_update', {
      nodes: [{ id: 'sentiment', label: '聚合口碑舆情', status: 'working' }],
    })
    const s = useTaskStore.getState()
    expect(s.nodes.map((n) => n.id)).toEqual(['sentiment'])
    expect(s.nodes[0].status).toBe('working')
  })

  it('F1b · node_update 单节点按 id 翻转（命中聚合口碑舆情节点）', () => {
    useTaskStore.getState().ingest('node_update', { node: 'sentiment', status: 'done', expert: 'L3-002' })
    const s = useTaskStore.getState()
    const n = s.nodes.find((x) => x.id === 'sentiment')!
    expect(n.status).toBe('done')
    expect(n.expert).toBe('L3-002')
  })

  it('F2 · thought 追加至 thoughts', () => {
    useTaskStore.getState().ingest('thought', { id: 'th1', kind: 'plan', expert: 'L3-001', text: '目标已明确', ts: 1 })
    const s = useTaskStore.getState()
    expect(s.thoughts.length).toBe(1)
    expect(s.thoughts[0].kind).toBe('plan')
  })

  it('F3 · message{kind:team,members} 落位 teamMembers', () => {
    useTaskStore.getState().ingest('message', { id: 'm1', kind: 'team', members: ['L3-001', 'L1-003'] })
    expect(useTaskStore.getState().teamMembers).toEqual(['L3-001', 'L1-003'])
  })

  it('F4 · evidence 追加至 evidences', () => {
    useTaskStore.getState().ingest('evidence', {
      evidence_id: 'e1', source_url: 'https://x', credibility: 0.8, title: '线索',
    })
    const s = useTaskStore.getState()
    expect(s.evidences.length).toBe(1)
    expect(s.evidences[0].evidence_id).toBe('e1')
  })
})

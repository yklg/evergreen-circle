/**
 * 目的地「攻略/评估」调研 SSE 事件流 mock 回放器。
 *
 * 在数据模式为 fixture 且任务非生活圈（research / travel_*）时，替代真实 EventSource：
 * 以定时器重放一条**角色专家流水线**事件流（thought/DAG node_update/evidence/progress），
 * 让工作台三栏在演示态得到与 M3 真实 SSE 完全一致的契约（事件类型/字段同构）。
 *
 * 契约：本文件产出的每个事件 { type, data } 直接映射 onEvent(type, data)；字段与
 * run_pipeline 真实输出对齐（report_ready/done 用驼峰 reportId；progress 用
 * percent/stage/evidence_count；node_update 支持 {nodes:[…]} 与单节点两种形态）。
 */
import type { SSEEventType } from '../types'

export interface ResearchReplayOptions {
  /** 目的地产出体裁：guide(攻略) | assess(评估)，影响标题与取证话术 */
  purpose?: string
  /** 覆盖流内 report_ready/done 的目标报告 id */
  reportId?: string
  /** 事件步进间隔 ms（演示用；默认 120ms） */
  speed?: number
  onDone?: (reportId: string) => void
}

const STAGES = ['intake', 'orchestrator', 'collect', 'sentiment', 'write', 'audit', 'done']

const PURPOSE_LABEL: Record<string, string> = {
  guide: '目的地攻略',
  assess: '目的地评估',
}

const EXPERTS: { id: string; note: string }[] = [
  { id: 'L3-001', note: '决策层统筹：定义调研面与交付标准' },
  { id: 'L3-002', note: '策略顾问：编排角色流水线与证据框架' },
  { id: 'L1-003', note: '执行专家：交通/住宿/路线取证' },
  { id: 'L1-004', note: '执行专家：安全/预算/口碑真相核查' },
]

/** 回放目的地调研角色流水线；返回 close()。 */
export function replayResearchStream(
  _taskId: string,
  handlers: { onEvent: (type: SSEEventType, data: unknown) => void; onError?: (e: unknown) => void },
  opts: ResearchReplayOptions = {},
): () => void {
  const { purpose = 'guide', speed = 120, onDone } = opts
  const label = PURPOSE_LABEL[purpose] ?? '目的地调研'
  const reportId = opts.reportId ?? `demo-${purpose}-${Date.now()}`
  const timers: ReturnType<typeof setTimeout>[] = []
  let closed = false

  type Ev = { t: SSEEventType; d: unknown }
  const events: Ev[] = []

  const push = (t: SSEEventType, d: unknown) => events.push({ t, d })

  // intake
  push('node_update', { nodes: STAGES.map((s) => ({ id: s, label: '', status: 'idle' })) })
  push('node_update', { node: 'intake', status: 'working', expert: 'L3-001' })
  push('progress', { percent: 4, stage: 'intake', evidence_count: 0 })
  push('thought', { id: 'th-1', kind: 'plan', expert: 'L3-001', text: '目标已明确：对目的地做一次专家级调研，锁定信息口径与交付章节。', ts: Date.now() })

  // orchestrator
  push('node_update', { node: 'intake', status: 'done', expert: 'L3-001' })
  push('node_update', { node: 'orchestrator', status: 'working', expert: 'L3-002' })
  push('progress', { percent: 18, stage: 'orchestrator', evidence_count: 0 })
  push('message', { id: 'm-team', kind: 'team', text: `专家队就位，开始「${label}」调研`, expert: 'L3-002', members: EXPERTS.map((e) => e.id), membersNotes: EXPERTS })
  push('thought', { id: 'th-2', kind: 'dispatch', expert: 'L3-002', text: EXPERTS[1].note + '，并分配各执行专家取证面。', ts: Date.now() })
  push('node_update', { node: 'orchestrator', status: 'done', expert: 'L3-002' })

  // collect
  push('node_update', { node: 'collect', status: 'working', expert: 'L1-003' })
  push('progress', { percent: 40, stage: 'collect', evidence_count: 3 })
  const evs: { title: string; src: string; by: string; cred: number; ex: string }[] = [
    { title: '行前必读：目的地交通与到达方式', src: 'https://example.com/travel/transport', by: '交通出行', cred: 0.86, ex: 'L1-003' },
    { title: aim('住宿', purpose), src: 'https://example.com/travel/stay', by: '住宿攻略', cred: 0.82, ex: 'L1-003' },
    { title: '游玩路线与时间安排', src: 'https://example.com/travel/route', by: '路线攻略', cred: 0.78, ex: 'L1-004' },
  ]
  evs.forEach((e, i) => {
    push('evidence', {
      evidence_id: `ev-${i + 1}`,
      source_url: e.src,
      source_type: 'web',
      title: e.title,
      excerpt: e.title + ' —— 一份可照做的高参考度线索。',
      captured_at: new Date().toISOString(),
      credibility: e.cred,
      collected_by: e.by,
      brand: '',
      domain: 'example.com',
    })
  })
  push('thought', { id: 'th-3', kind: 'action', expert: 'L1-003', text: '已采集交通/住宿/路线多个角度的真实线索，进入交叉验证。', ts: Date.now() })
  push('node_update', { node: 'collect', status: 'done', expert: 'L1-004' })

  // sentiment
  push('node_update', { node: 'sentiment', status: 'working', expert: 'L3-002' })
  push('progress', { percent: 58, stage: 'sentiment', evidence_count: 3 })
  push('thought', { id: 'th-4', kind: 'finding', expert: 'L3-002', text: '交叉比对后确认：交通可达性与住宿配套是本次结论的关键变量。', ts: Date.now() })
  push('node_update', { node: 'sentiment', status: 'done', expert: 'L3-002' })

  // write
  push('node_update', { node: 'write', status: 'working', expert: 'L3-002' })
  const sections = purpose === 'guide'
    ? ['执行摘要', '目的地总览', '交通可达', '餐饮住宿', '路线规划', '安全应急', '预算性价比']
    : ['执行摘要', '可达性', '配套完善度', '性价比', '安全性', '总体结论']
  sections.forEach((s, i) => {
    const p = 62 + Math.round((28 * (i + 1)) / sections.length)
    push('progress', { percent: p, stage: 'write', evidence_count: 3 })
    push('thought', { id: `th-w${i}`, kind: 'finding', expert: 'L3-002', text: `「${s}」章撰写完成。`, ts: Date.now() })
  })
  push('node_update', { node: 'write', status: 'done', expert: 'L3-002' })

  // audit
  push('node_update', { node: 'audit', status: 'working', expert: 'L3-001' })
  push('progress', { percent: 97, stage: 'audit', evidence_count: 3 })
  push('thought', { id: 'th-5', kind: 'reflect', expert: 'L3-001', text: '质检复核：证据溯源完整、结论有据，签发报告。', ts: Date.now() })
  push('node_update', { node: 'audit', status: 'done', expert: 'L3-001' })

  // done
  push('node_update', { node: 'done', status: 'working', expert: 'L3-001' })
  push('progress', { percent: 99, stage: 'done', evidence_count: 3 })
  push('report_ready', { reportId, title: `${label}调研报告` })
  push('done', { reportId })
  push('node_update', { node: 'done', status: 'done', expert: 'L3-001' })
  push('progress', { percent: 100, stage: 'done', evidence_count: 3 })

  events.forEach((ev, i) => {
    const t = setTimeout(() => {
      if (closed) return
      handlers.onEvent(ev.t, ev.d)
      if (ev.t === 'done') onDone?.(reportId)
    }, i * speed)
    timers.push(t)
  })

  return () => {
    closed = true
    timers.forEach(clearTimeout)
  }
}

function aim(base: string, purpose: string): string {
  return purpose === 'assess' ? `${base}评估` : base
}
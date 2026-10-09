// @vitest-environment jsdom
/**
 * 席位归属（owner）进 `taskRegistry` 的管道判据（计划 F1 / TC-B1 / TC-B2 / TC-E1）。
 *
 * 立这四条的理由不是"多加点断言"，而是这条管道上有三个**只会静默出错**的形状：
 *  1. `upsert` 是逐字段手点的合并表 ⇒ 漏一行 `expert:` 的症状是"下一条 upsert 把它清成 undefined"，
 *     而不是编译错；
 *  2. owner 与 stage 分两处存 ⇒ 会出现"阶段已走到 collect、横幅还挂着 measure 的席位"；
 *  3. `load()` 是裸 `JSON.parse(...) as Record<string, TaskRecord>`，无校验无迁移 ⇒
 *     旧记录读出来是 `undefined` 而不是 `''`。
 *
 * 事件一律从 `subscribeLifeCircleTask` 那一侧灌进来（与真 SSE 同一个入口），
 * 不去测 `__test.onFlowEvent` —— 那只会测到"解析对了"，测不到"落库这一笔对不对"。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

type StreamHandlers = { onEvent: (t: string, d: unknown) => void; onError?: (e: unknown) => void }

const { api } = vi.hoisted(() => ({
  api: {
    openTaskStream: vi.fn(),
    createLivingCircleTask: vi.fn(async () => ({ taskId: 'lc-1' })),
    fetchLifeCircleReport: vi.fn(async () => null),
  },
}))

vi.mock('../lib/api', () => api)

import { subscribeLifeCircleTask } from '../lib/lifeCircleFlow'
import { useTaskRegistry } from '../store/taskRegistry'

const LS_KEY = 'verda.tasks.v1'
let fire!: (t: string, d: unknown) => void

const record = (taskId = 'lc-1') => useTaskRegistry.getState().tasks[taskId]

beforeEach(() => {
  localStorage.clear()
  useTaskRegistry.setState({ tasks: {} })
  api.openTaskStream.mockImplementation((_id: string, h: StreamHandlers) => {
    fire = (t: string, d: unknown) => h.onEvent(t, d)
    return () => {}
  })
  subscribeLifeCircleTask('lc-1')
})

describe('F1 · owner 与 stage 同一笔写', () => {
  it('progress 带 expert ⇒ registry 同时落 stage 与 expert', () => {
    fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    expect(record().stage).toBe('collect')
    expect(record().expert).toBe('L1-030')
  })

  it('随后一条**换了 stage 而不带 expert** 的帧 ⇒ 清掉 owner（不许替没算的那步举证）', () => {
    fire('progress', { stage: 'measure', percent: 30, expert: 'L1-027' })
    // 后端 C2 里"被缓存跳过的五步"就是这种帧：stage 在走，归属故意不发。
    fire('progress', { stage: 'diagnose', percent: 82 })
    expect(record().stage).toBe('diagnose')
    expect(record().expert, '沿用旧值＝横幅替 diagnose 署了 measure 的席位').toBeUndefined()
  })

  it('不带 expert 键的补写（evidence 计数 / 悬浮条 status 轮询）不得把 owner 清掉', () => {
    fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    fire('evidence', { evidence: { collected_by: 'L2-004' } })
    expect(record().expert, 'evidence 那一笔压根不提 expert，不该顺手清空').toBe('L1-030')
    // 悬浮条每 3s 轮 `/api/tasks/{id}/status` 并 upsert 一份**带 stage 而不带归属**的快照
    // （`TaskFloatBar.tsx:43-49`，那个端点没有 expert 这一位）。若把"带 stage"当成"归属说了算"，
    // 这一行就会每 3 秒被抹掉一次 —— 上一版判据按 stage 分叉时正是这个形状。
    useTaskRegistry.getState().upsert({ taskId: 'lc-1', stage: 'collect', percent: 55, evidence_count: 3 })
    expect(record().expert, 'status 快照不提 expert ⇒ 归属必须原样留着').toBe('L1-030')
  })

  it('演示夹具把 owner 挂在 message 上 ⇒ 同一行也拿得到（live 挂 progress，两源都收）', () => {
    fire('progress', { stage: 'measure', percent: 30 })
    expect(record().expert).toBeUndefined()
    fire('message', { stage: 'measure', text: '粗扫 400m 网格', expert: 'L2-005' })
    expect(record().expert).toBe('L2-005')
    expect(record().stage, 'message 不带 stage ⇒ 不许改阶段').toBe('measure')
  })

  it('owner 随 save/load 落进 localStorage（悬浮条与刷新后读的是同一份）', () => {
    fire('progress', { stage: 'audit', percent: 98, expert: 'L3-003' })
    const stored = JSON.parse(localStorage.getItem(LS_KEY) ?? '{}') as Record<string, { expert?: string }>
    expect(stored['lc-1'].expert).toBe('L3-003')
  })
})

describe('TC-B1 · 终态之后的迟到帧不回退 owner', () => {
  it('markDone 之后到达的 progress 不改 stage / expert', () => {
    fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    fire('done', { report_id: 'lc-kaili', reportId: 'lc-kaili' })
    expect(record().status).toBe('done')
    fire('progress', { stage: 'audit', percent: 100, expert: 'L3-003' })
    expect(record().expert, '终态后迟到帧替最后一步署了名').toBe('L1-030')
    expect(record().stage).toBe('collect')
  })

  it('markDone 之后的迟到 message 也不补写 owner', () => {
    fire('progress', { stage: 'collect', percent: 55, expert: 'L1-030' })
    fire('done', { report_id: 'lc-kaili' })
    fire('message', { text: '迟到的归属', expert: 'L2-008' })
    expect(record().expert).toBe('L1-030')
  })
})

describe('TC-E1 · 旧 localStorage 记录不含 expert 键', () => {
  it('裸 JSON.parse 出来的旧记录读出 undefined 且不抛，首次带 stage 的 upsert 归一', async () => {
    // 这就是 `load()` 的真实形状：没有校验、没有版本升级路径。
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({
        'lc-old': {
          taskId: 'lc-old', query: '凯里老街', kind: 'living_circle', purpose: 'living_circle',
          status: 'running', percent: 12, evidence_count: 0, stage: 'plan',
          startedAt: '2026-10-01T00:00:00.000Z', updatedAt: '2026-10-01T00:00:00.000Z', reportId: null,
        },
      }),
    )
    vi.resetModules()
    const { useTaskRegistry: rehydrated } = await import('../store/taskRegistry')
    const legacy = rehydrated.getState().tasks['lc-old']
    expect(legacy).toBeTruthy()
    expect(legacy.expert, '旧记录该是 undefined，而不是被当成空串').toBeUndefined()
    expect(() => rehydrated.getState().upsert({ taskId: 'lc-old', stage: 'measure', expert: 'L1-027' })).not.toThrow()
    expect(rehydrated.getState().tasks['lc-old'].expert).toBe('L1-027')
  })
})

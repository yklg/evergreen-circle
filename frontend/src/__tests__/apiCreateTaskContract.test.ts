// @vitest-environment node
/**
 * createTask / fetchExperts HTTP 契约（FE-6/7/8）：
 * - 真实态 POST body 只写权威 type（不写 purpose——方言归一在后端）；
 * - 演示态零网络，返回映射后的 kind 与回放桥 purpose；
 * - fetchExperts 按域带 ?domain= 查询参数。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

beforeEach(() => {
  vi.resetModules()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

async function loadApi() {
  return await import('../lib/api')
}

function stubDataMode(mode: 'live' | 'fixture') {
  vi.doMock('../store/dataModeStore', () => ({
    isFixtureMode: () => mode === 'fixture',
    useDataModeStore: { getState: () => ({ mode }) },
  }))
}

describe('FE-6 · 真实态 createTask 写权威 type', () => {
  it('assessment：body.type=assessment 且不含 purpose 键', async () => {
    stubDataMode('live')
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/tasks')) {
        calls.push(init ?? {})
        return new Response(JSON.stringify({ taskId: 't1', researchType: 'assessment' }), { status: 200 })
      }
      return new Response('{}', { status: 200 })
    }))
    const { createTask } = await loadApi()
    await createTask('评估成都和杭州', 'deep', null, 'assessment')
    expect(calls).toHaveLength(1)
    const body = JSON.parse(String(calls[0].body))
    expect(body.type).toBe('assessment')
    expect(body).not.toHaveProperty('purpose')
    expect(body.mode).toBe('deep')
    expect(body.model).toBeNull()
  })

  it('旧方言入参 assess 在客户端先归一为 assessment 再发出', async () => {
    stubDataMode('live')
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/tasks')) {
        calls.push(init ?? {})
        return new Response(JSON.stringify({ taskId: 't2', researchType: 'assessment' }), { status: 200 })
      }
      return new Response('{}', { status: 200 })
    }))
    const { createTask } = await loadApi()
    await createTask('q', 'deep', null, 'assess')
    expect(JSON.parse(String(calls[0].body)).type).toBe('assessment')
  })
})

describe('FE-7 · 演示态 createTask 零网络', () => {
  it('不调 fetch，返回 demo id + 映射 kind/purpose', async () => {
    stubDataMode('fixture')
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { createTask } = await loadApi()
    const r = await createTask('q', 'quick', null, 'assessment')
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(r.taskId.startsWith('demo-')).toBe(true)
    expect(r.kind).toBe('travel_assess')
    expect(r.purpose).toBe('assess')
  })
})

describe('FE-8 · fetchExperts 按域带查询参数', () => {
  it('living_circle → URL 含 ?domain=living_circle；默认无 query string', async () => {
    stubDataMode('live')
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url)
      return new Response(JSON.stringify([{ id: 'L3-001' }]), { status: 200 })
    }))
    const { fetchExperts } = await loadApi()
    await fetchExperts('living_circle')
    await fetchExperts('travel')
    expect(urls[0]).toContain('/api/experts?domain=living_circle')
    // travel 走无查询参的 URL：端点缺省＝travel 是公开契约（`fetchExperts` 的 domain
    // 本身已必填，这里钉的是**线上形状**没被改成 `?domain=travel`）。
    expect(urls[1].endsWith('/api/experts')).toBe(true)
  })
})

describe('FE-9 · 生活圈请求体的 travel_mode 只在用户表态后出现', () => {
  /** 抓 createLivingCircleTask 真正 POST 出去的 JSON（不是中间那层 TS 对象） */
  async function captureBody(input: Record<string, unknown>) {
    stubDataMode('live')
    // 用数组接：`let body: ... | null = null` 在闭包里赋值，TS 会把后续收窄成 never
    const captured: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/api/tasks')) {
        captured.push(JSON.parse(String(init?.body)))
        return new Response(JSON.stringify({ taskId: 'lc-t1' }), { status: 200 })
      }
      return new Response('{}', { status: 200 })
    }))
    const { createLivingCircleTask } = await loadApi()
    await createLivingCircleTask(input as never)
    if (!captured.length) throw new Error('没有 POST /api/tasks')
    return captured[0]
  }

  it('选骑行 ⇒ 键名逐字 travel_mode:"riding"（后端 CreateTaskBody 声明的就是这个名）', async () => {
    const body = await captureBody({ query: '凯里老街', travel_mode: 'riding' })
    expect(body.travel_mode).toBe('riding')
  })

  it('不表态 ⇒ 请求体**没有** travel_mode 键：缺键≠walking，后端才谈得上回落', async () => {
    const body = await captureBody({ query: '凯里老街' })
    expect('travel_mode' in body, `前端替用户预先表态了：${JSON.stringify(body)}`).toBe(false)
    // 其余键照常发出，别把这条判据写成"整个 body 是空的"
    expect(body.query).toBe('凯里老街')
    expect(body.type).toBe('living_circle')
  })

  it('显式选 walking 也要发键（用户确实选了步行 ≠ 没选）', async () => {
    const body = await captureBody({ query: '凯里老街', travel_mode: 'walking' })
    expect(body.travel_mode).toBe('walking')
  })
})

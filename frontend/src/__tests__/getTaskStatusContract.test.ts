// @vitest-environment node
/**
 * getTaskStatus 契约：notFound 仅在「HTTP 200 且 body.status 为空」为 true；
 * 网络失败 / 5xx → notFound=false（暂不可用，绝不误判不存在）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { getTaskStatus } from '../lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function ok(body: unknown) {
  return vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body })
}

describe('getTaskStatus notFound 契约', () => {
  it('HTTP 200 且 body.status 为空 → notFound=true', async () => {
    vi.stubGlobal(
      'fetch',
      ok({ status: null, percent: 0, stage: '', evidence_count: 0, report_id: null, started_at: null, updated_at: null }),
    )
    const r = await getTaskStatus('gone')
    expect(r.notFound).toBe(true)
    expect(r.status).toBeNull()
  })

  it('HTTP 200 且 status 有值 → notFound=false 且解析成功', async () => {
    vi.stubGlobal(
      'fetch',
      ok({ status: 'running', percent: 42, stage: 'collect', evidence_count: 3, report_id: null, started_at: 's', updated_at: 'u' }),
    )
    const r = await getTaskStatus('running-1')
    expect(r.notFound).toBe(false)
    expect(r.status).toBe('running')
    expect(r.percent).toBe(42)
  })

  it('网络失败 → notFound=false（暂不可用，不误判不存在）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const r = await getTaskStatus('x')
    expect(r.notFound).toBe(false)
  })

  it('HTTP 5xx → notFound=false', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))
    const r = await getTaskStatus('x')
    expect(r.notFound).toBe(false)
  })
})
// @vitest-environment node
/**
 * api 层封装测试：generateReportBrief（《报告简报与 PPT 汇报方案 v3》+ G7 迁移）。
 * 契约：POST /api/reports/{id}/brief → {taskId}（kind='brief' 后台任务，产物经 SSE done 后落 report.brief）；
 * 非 2xx / 无 taskId / 网络异常必须 throw（失败显式，不做静默兜底）。
 */
import { describe, it, expect, vi } from 'vitest'
import { generateReportBrief } from '../lib/api'

describe('generateReportBrief api 封装（G7 taskId 语义）', () => {
  it('POST /api/reports/{id}/brief → 返回 {taskId}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ taskId: 'bt_x1' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const res = await generateReportBrief('r1')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/reports/r1/brief'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(res).toEqual({ taskId: 'bt_x1' })
    vi.unstubAllGlobals()
  })

  it('HTTP 非 2xx（404）→ throw，且携带后端 detail 文案', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: '报告不存在或未就绪' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(generateReportBrief('r1')).rejects.toThrow('报告不存在或未就绪')
    vi.unstubAllGlobals()
  })

  it('HTTP 2xx 但无 taskId → throw（未返回任务 ID，不伪装成功）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
    await expect(generateReportBrief('r1')).rejects.toThrow(/任务 ID/)
    vi.unstubAllGlobals()
  })

  it('网络异常（fetch reject）→ throw', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('NetworkError')))
    await expect(generateReportBrief('r1')).rejects.toThrow()
    vi.unstubAllGlobals()
  })
})
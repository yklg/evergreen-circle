// @vitest-environment node
/**
 * 报告拉取链路的信封闸（live 档白屏缺陷的修法半边，独立于第五维）。
 *
 * 实测成因：旧版后端 `GET /api/reports/{id}` 对**不存在**的报告返回 **HTTP 200 + `{ok:false,
 * message:'report not ready'}`**，而 `safeJson` 只看 HTTP 状态 ⇒ 那枚错误信封被当成一份报告
 * 塞进 `reportStore.current`，`ReportPage` 的两道守卫（`error || !current`、`report_type` 判定）
 * 全部放行，最后死在 `r.evidence.map` 上 —— 整页零字符（真机复现：新浏览器无
 * `evergreen.dataMode.v1` ⇒ live 档打开任何演示报告 id 必白屏）。
 *
 * 后端已改成 404；这一层仍然留形状闸，因为"200 承载业务失败"是这个仓可能再出现的形状
 * （中间件、旧部署、代理都发得出来）。两条判据各钉一半：**信封不许进 store**、
 * **真报告不许被误杀**。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchReport } from '../lib/api'
import { useDataModeStore } from '../store/dataModeStore'
import { useReportStore } from '../store/reportStore'

const REAL_REPORT = {
  id: 'r-ok-1', title: '一份真报告', subtitle: '', created_at: '2026-10-13T00:00:00Z',
  experts: [], toc: [{ id: 's1', title: '章一', level: 2 }], sections: [], charts: [], evidence: [],
}

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => body })
}

afterEach(() => {
  vi.unstubAllGlobals()
  useReportStore.setState({ current: null, loading: false, error: null, cache: {} })
})

describe('fetchReport 的形状闸', () => {
  it('live 档：200 + {ok:false} 信封 ⇒ null（不许当成报告返回）', async () => {
    useDataModeStore.setState({ mode: 'live' })
    vi.stubGlobal('fetch', respond(200, { ok: false, message: 'report not ready' }))
    await expect(fetchReport('lc-nope')).resolves.toBeNull()
  })

  it('live 档：404 ⇒ null（后端已改判 404，这一半是回归网）', async () => {
    useDataModeStore.setState({ mode: 'live' })
    vi.stubGlobal('fetch', respond(404, { detail: 'report not ready' }))
    await expect(fetchReport('lc-nope')).resolves.toBeNull()
  })

  it('正对照：必填格齐的真报告原样返回（防"恒 null"也算通过）', async () => {
    useDataModeStore.setState({ mode: 'live' })
    vi.stubGlobal('fetch', respond(200, REAL_REPORT))
    await expect(fetchReport('r-ok-1')).resolves.toMatchObject({ id: 'r-ok-1' })
  })

  it('缺 `evidence`/`toc`/`sections` 任一必填格的半吊子对象 ⇒ 一律 null', async () => {
    useDataModeStore.setState({ mode: 'live' })
    for (const key of ['evidence', 'toc', 'sections'] as const) {
      const broken: Record<string, unknown> = { ...REAL_REPORT }
      delete broken[key]
      vi.stubGlobal('fetch', respond(200, broken))
      await expect(fetchReport('r-ok-1')).resolves.toBeNull()
    }
  })
})

describe('reportStore 不再把信封当报告', () => {
  it('拉取失败 ⇒ error 有值且 current 为 null（渲染层因此走"报告不存在"而不是白屏）', async () => {
    useDataModeStore.setState({ mode: 'live' })
    vi.stubGlobal('fetch', respond(200, { ok: false, message: 'report not ready' }))
    await useReportStore.getState().load('lc-nope')
    const s = useReportStore.getState()
    expect(s.current).toBeNull()
    expect(s.error, '没有错误态就没有"报告不存在"那一屏，白屏会回来').toBeTruthy()
    expect(s.loading).toBe(false)
  })
})

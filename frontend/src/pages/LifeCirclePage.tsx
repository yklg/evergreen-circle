/**
 * 生活圈体检地图页（F2 核心 · F0 实物版）。
 *
 * 本期（F 阶段）以 fixture 驱动的「静态画布」形态呈现：
 *   - 无 AK / 无 BMapGL 依赖，纯 SVG 投影渲染等时圈族 / POI / 盲区灰区
 *   - M 阶段接入 BMapGL 与真实 /api 后，本页升级为真地图交互，画布逻辑复用
 *
 * 契约：src/types.ts 的 LivingCircleReport（F0 冻结）。
 * 投影/配色与报告页快照共用 src/lib/livingCircle.ts（单一真相源）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  TriangleAlert,
  Crosshair,
  RotateCcw,
  MapPin,
  Info,
  FileText,
  Play,
  X,
} from 'lucide-react'
import {
  SAMPLE_COMMUNITIES,
  getLifeCircleMock,
  USE_MOCK,
} from '../mocks/livingCircleMock'
import { LC_REPORT_ID } from '../mocks/livingCircleReports'
import { replayLivingCircleStream, LC_STAGES, stageLabel } from '../mocks/livingCircleStream'
import { createLivingCircleTask, fetchLifeCircleReports, fetchLifeCircleReport } from '../lib/api'
import type {
  LngLat,
  LivingCircleReport,
  FacilityCategoryStat,
} from '../types'
import {
  LC_CANVAS,
  LC_CAT_COLOR,
  LC_ISO_COLORS,
  lcPolyPts,
  lcRightmost,
  lcToPx,
} from '../lib/livingCircle'
import { MiniRadar } from '../components/lifecircle/MiniRadar'

/* 画布几何与投影/配色：来自 lib/livingCircle.ts（W/H/R 见 LC_CANVAS） */

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line/60 py-1.5 last:border-0">
      <span className="text-tag text-ink-3">{label}</span>
      <span className="text-aux font-medium text-ink">{value}</span>
    </div>
  )
}

export default function LifeCirclePage() {
  const { sceneId = 'kaili' } = useParams()
  const navigate = useNavigate()
  const [customCenter, setCustomCenter] = useState<LngLat | null>(null)
  const [dragging, setDragging] = useState(false)

  /* A4 演示任务流（仅 mock 分支；M3 真实分支由工作台 SSE 接管） */
  const [playing, setPlaying] = useState(false)
  const [playStage, setPlayStage] = useState('intake')
  const [playProgress, setPlayProgress] = useState(0)
  const [playMsg, setPlayMsg] = useState('')
  const closeRef = useRef<(() => void) | null>(null)

  /* M3 真实分支：拉取最近一次体检记录渲染画布 + 顶部「开始体检」CTA */
  const [realReport, setRealReport] = useState<LivingCircleReport | null>(null)
  const [realLatestId, setRealLatestId] = useState('')
  const [realLoading, setRealLoading] = useState(!USE_MOCK)
  const [ctaText, setCtaText] = useState('')
  const [ctaBusy, setCtaBusy] = useState(false)
  const [ctaErr, setCtaErr] = useState('')

  useEffect(() => {
    if (USE_MOCK) return
    let cancelled = false
    fetchLifeCircleReports()
      .then((rows) => {
        if (cancelled || !rows.length) return
        setRealLatestId(rows[0].id)
        return fetchLifeCircleReport(rows[0].id)
      })
      .then((rep) => {
        if (!cancelled && rep?.living_circle) setRealReport(rep.living_circle)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setRealLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const report = useMemo<LivingCircleReport | null>(() => {
    if (!USE_MOCK) return realReport
    if (sceneId === 'custom') {
      // F 阶段：自定义中心点复用最近样例（M 阶段替换为在线计算）
      return SAMPLE_COMMUNITIES[0] ? SAMPLE_COMMUNITIES[0].report : null
    }
    return getLifeCircleMock(sceneId)
  }, [sceneId, realReport])

  const center: LngLat = customCenter ?? report?.scene.center ?? [0, 0]

  // 样区路由参数与报告 id：custom → 最近样例 kaili（仅 mock 分支使用）
  const effectiveScene = sceneId === 'custom' ? 'kaili' : sceneId
  const reportId = LC_REPORT_ID(effectiveScene)
  const targetReportId = USE_MOCK ? reportId : realLatestId

  /** M3：以当前输入（或画布新中心点）发起真实体检任务 → 工作台 SSE */
  async function startRealCheck(centerOverride?: LngLat) {
    if (ctaBusy) return
    const query = ctaText.trim()
    const m = /^\s*([\d.]+)\s*,\s*([\d.]+)\s*$/.exec(query)
    let center = centerOverride
    if (!center && m) center = [Number(m[1]), Number(m[2])]
    setCtaErr('')
    setCtaBusy(true)
    try {
      const r = await createLivingCircleTask({
        query: query || report?.scene.name || '生活圈体检',
        mode: 'standard',
        center,
        city: report?.scene.city ?? '',
      })
      navigate(`/workspace/${r.taskId}`, { state: { query: query || report?.scene.name || '' } })
    } catch (e) {
      setCtaErr(e instanceof Error ? e.message : String(e))
    } finally {
      setCtaBusy(false)
    }
  }

  useEffect(() => () => closeRef.current?.(), [])

  if (!report) {
    // 真实模式：暂无体检记录 → 引导发起
    if (!USE_MOCK) {
      return (
        <div className="mx-auto flex min-h-full max-w-[720px] flex-col items-center justify-center gap-4 px-6 py-16 text-center">
          <Info size={32} className="text-ink-3" />
          <div className="text-h3 text-ink">还没有体检记录</div>
          <p className="text-aux text-ink-2">
            输入社区名或坐标发起第一次生活圈体检，完成后会在这里展示等时圈与体检单
          </p>
          <div className="mt-1 flex w-full max-w-md items-center gap-2">
            <input
              value={ctaText}
              onChange={(e) => setCtaText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') startRealCheck()
              }}
              placeholder="社区名 / 或 经度,纬度（BD-09）—— 例如：凯里老街"
              className="h-11 flex-1 rounded-btn border border-line bg-card px-4 text-aux text-ink outline-none placeholder:text-ink-3 focus:border-primary"
            />
            <button
              onClick={() => startRealCheck()}
              disabled={ctaBusy || realLoading}
              className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-btn bg-primary px-5 font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <Play size={15} /> 开始体检
            </button>
          </div>
          {ctaErr && <div className="text-tag text-risk">创建失败：{ctaErr}</div>}
          {realLoading && <div className="text-tag text-ink-3">正在加载历史记录……</div>}
        </div>
      )
    }
    return (
      <div className="grid min-h-full place-items-center p-8 text-ink-2">
        <div className="rounded-card border border-line bg-card p-6 text-center">
          <Info size={22} className="mx-auto mb-2 text-ink-3" />
          <p>未找到该样区的体检数据</p>
        </div>
      </div>
    )
  }

  const isoZones = report.isochrones

  /** 画布点击 = 设定新中心点（D2：拖点/点选 → 确认后重新体检） */
  function onCanvasClick(e: ReactMouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * LC_CANVAS.W
    const py = ((e.clientY - rect.top) / rect.height) * LC_CANVAS.H
    const mx = ((px - LC_CANVAS.W / 2) / (LC_CANVAS.W / 2)) * LC_CANVAS.R
    const my = ((LC_CANVAS.H / 2 - py) / (LC_CANVAS.H / 2)) * LC_CANVAS.R
    const dLat = my / 111320
    const dLng = mx / (111320 * Math.cos((center[1] * Math.PI) / 180))
    setCustomCenter([center[0] + dLng, center[1] + dLat])
    setDragging(true)
  }

  /** A4：回放体检流水线事件流（演示用；M3 由真实任务流接管） */
  function startDemoFlow() {
    setPlaying(true)
    setPlayStage('intake')
    setPlayProgress(0)
    setPlayMsg('')
    closeRef.current = replayLivingCircleStream(
      `lc-${effectiveScene}`,
      {
        onEvent: (type, data) => {
          const d = data as { stage?: string; percent?: number; text?: string }
          if (type === 'progress' && d?.stage) {
            setPlayStage(d.stage)
            setPlayProgress(d.percent ?? 0)
          }
          if (type === 'message' && d?.text) setPlayMsg(d.text)
        },
      },
      { reportId, onDone: (rid) => navigate(`/report/${rid}`) },
    )
  }

  function stopDemoFlow(skipToReport = false) {
    closeRef.current?.()
    closeRef.current = null
    setPlaying(false)
    if (skipToReport) navigate(`/report/${reportId}`)
  }

  return (
    <div className="mx-auto flex min-h-full max-w-[1240px] flex-col gap-4 px-6 py-6">
      {/* 顶栏：mock=场景切换 + 演示流水线；M3=真实「开始体检」CTA + 最新报告入口 */}
      {USE_MOCK ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {SAMPLE_COMMUNITIES.map((c) => (
              <button
                key={c.id}
                onClick={() => navigate(`/life-circle/${c.id}`)}
                className={`flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux transition-colors ${
                  sceneId === c.id ? 'bg-primary text-white' : 'bg-primary-tint/60 text-ink-2 hover:bg-primary-tint'
                }`}
              >
                <MapPin size={14} />
                {c.title}
              </button>
            ))}
            <button
              onClick={startDemoFlow}
              disabled={playing}
              title="演示：回放体检 SSE 流水线（intake→…→audit）后打开报告"
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint disabled:opacity-50"
            >
              <Play size={13} /> 演示体检流水线
            </button>
            <button
              onClick={() => navigate('/compare')}
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
            >
              对比双样例 →
            </button>
          </div>
          {report.data_origin === 'fixture_sample' && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-warn/60 bg-warn/10 px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> 演示数据模式（fixture · 等时圈为圆形近似，M5 后真实路网覆写）
            </span>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-[300px] flex-1 items-center gap-2">
            <input
              value={ctaText}
              onChange={(e) => setCtaText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') startRealCheck()
              }}
              placeholder="输入社区名 / 或 经度,纬度（BD-09）后重新体检，例如：凯里老街"
              className="h-9 flex-1 rounded-btn border border-line bg-card px-3 text-aux text-ink outline-none placeholder:text-ink-3 focus:border-primary"
            />
            <button
              onClick={() => startRealCheck(customCenter ?? undefined)}
              disabled={ctaBusy}
              className="flex h-9 shrink-0 items-center gap-1.5 rounded-btn bg-primary px-4 text-aux font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <Play size={13} /> 开始体检
            </button>
          </div>
          <div className="flex items-center gap-2">
            {targetReportId && (
              <button
                onClick={() => navigate(`/report/${targetReportId}`)}
                className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
              >
                浏览最新报告 →
              </button>
            )}
            <button
              onClick={() => navigate('/compare')}
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
            >
              对比双样例 →
            </button>
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-warn/60 bg-warn/10 px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> {report.data_origin === 'fixture_sample' ? '演示数据模式（fixture）' : '真实数据模式（live）'}
            </span>
          </div>
        </div>
      )}
      {!USE_MOCK && ctaErr && (
        <div className="rounded-btn bg-risk/10 px-3 py-1.5 text-tag text-risk" role="alert">
          体检任务创建失败：{ctaErr}
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* 地图画布 */}
        <div className="relative overflow-hidden rounded-card border border-line bg-card shadow-card">
          <svg
            viewBox={`0 0 ${LC_CANVAS.W} ${LC_CANVAS.H}`}
            className="block w-full cursor-crosshair select-none"
            onClick={onCanvasClick}
            role="img"
            aria-label="生活圈等时圈画布"
          >
            <rect x={0} y={0} width={LC_CANVAS.W} height={LC_CANVAS.H} fill="#f9faf8" />
            {[-2, -1, 0, 1, 2].map((i) => (
              <line key={`v${i}`} x1={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y1={0} x2={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y2={LC_CANVAS.H} stroke="#e7ebe7" strokeWidth={1} />
            ))}
            {[-2, -1, 0, 1, 2].map((i) => (
              <line key={`h${i}`} x1={0} y1={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} x2={LC_CANVAS.W} y2={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} stroke="#e7ebe7" strokeWidth={1} />
            ))}

            {[...isoZones].sort((a, b) => b.minutes - a.minutes).map((z) => {
              const color = LC_ISO_COLORS[isoZones.findIndex((x) => x.minutes === z.minutes)] ?? LC_ISO_COLORS[0]
              const ring = z.geojson.coordinates[0]
              return (
                <g key={z.minutes}>
                  <polygon points={lcPolyPts(center, ring)} fill={color.fill} stroke={color.stroke} strokeWidth={1.5} strokeLinejoin="round" />
                  {(() => {
                    const [lx, ly] = lcRightmost(center, ring)
                    return (
                      <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>
                        {z.minutes} min
                      </text>
                    )
                  })()}
                </g>
              )
            })}

            {report.blindspots.map((b) => (
              <g key={b.id}>
                <polygon points={lcPolyPts(center, b.polygon.coordinates[0])} fill="rgba(120,120,120,0.16)" stroke="#8a8a8a" strokeWidth={1} strokeDasharray="5 4" />
                <circle cx={lcToPx(center, b.center[0], b.center[1])[0]} cy={lcToPx(center, b.center[0], b.center[1])[1]} r={5} fill="#E8B54D" stroke="#fff" strokeWidth={1.5} />
              </g>
            ))}

            {report.sampling.points.length > 0 &&
              report.poi.categories.map((c: FacilityCategoryStat) => {
                const idx = report.poi.categories.indexOf(c)
                const theta = idx * 2.4
                const radius = 260 + ((idx * 70) % 520)
                const [px, py] = lcToPx(center, center[0], center[1])
                return (
                  <circle
                    key={c.category}
                    cx={px + Math.cos(theta) * radius * 0.9}
                    cy={py + Math.sin(theta) * radius * 0.9}
                    r={7}
                    fill={LC_CAT_COLOR[c.category] ?? '#7c6670'}
                    stroke="#fff"
                    strokeWidth={1.5}
                    opacity={0.92}
                  />
                )
              })}

            {(() => {
              const [x, y] = lcToPx(center, center[0], center[1])
              return (
                <g>
                  <circle cx={x} cy={y} r={14} fill="rgba(124,152,133,0.18)" stroke="#5F7B69" strokeWidth={1.5} strokeDasharray="3 3" />
                  <circle cx={x} cy={y} r={6} fill="#5F7B69" stroke="#fff" strokeWidth={2} />
                  <text x={x} y={y - 20} fontSize={12} fill="#3f5042" textAnchor="middle" fontWeight={600}>
                    {report.scene.name}
                  </text>
                </g>
              )
            })()}
          </svg>

          {/* 图例（悬浮） */}
          <div className="absolute left-3 top-3 flex max-w-[190px] flex-col gap-1.5 rounded-btn border border-line bg-card/90 p-3 backdrop-blur">
            <span className="text-tag font-medium text-ink-2">图层</span>
            {Object.entries(LC_CAT_COLOR).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1.5 text-tag text-ink-3">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: v }} />
                {k === 'market' ? '菜市场' : k === 'medical' ? '医疗' : k === 'education' ? '教育' : k === 'shopping' ? '购物' : k === 'elderly' ? '养老' : k === 'finance' ? '金融' : k === 'recreation' ? '文体' : '政务/服务'}
              </span>
            ))}
          </div>

          {dragging ? (
            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-chip border border-line bg-card/95 px-4 py-2 shadow-card backdrop-blur">
              <span className="text-tag text-ink-2">
                已设定新中心点（{center[0].toFixed(4)}, {center[1].toFixed(4)}）
              </span>
              <button
                onClick={() => {
                  if (USE_MOCK) {
                    const next = sceneId === 'custom' ? SAMPLE_COMMUNITIES[0] : SAMPLE_COMMUNITIES.find((c) => c.id === sceneId)
                    if (next) navigate(`/life-circle/${next.id}`)
                    setDragging(false)
                  } else {
                    setDragging(false)
                    startRealCheck(customCenter ?? undefined)
                  }
                }}
                className="ml-2 inline-flex items-center gap-1 rounded-chip bg-primary px-2.5 py-1 text-tag font-medium text-white hover:bg-primary-deep"
              >
                <RotateCcw size={12} /> 重新体检
              </button>
            </div>
          ) : (
            <div className="absolute bottom-3 left-3 hidden items-center gap-1 rounded-chip bg-card/80 px-3 py-1.5 text-tag text-ink-3 backdrop-blur sm:flex">
              <Crosshair size={12} /> 点击画布任意位置设定新中心点
            </div>
          )}
        </div>

        {/* 体检单右栏 */}
        <aside className="flex flex-col gap-4">
          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="flex items-end justify-between">
              <div>
                <div className="text-aux font-semibold text-ink">{report.scene.name} · 生活圈体检单</div>
                <div className="mt-0.5 text-tag text-ink-3">
                  {report.scene.city} · {report.scene.address}
                </div>
              </div>
              <div className="text-right">
                <div className="font-serif text-[34px] font-semibold leading-none text-primary">{report.scores.total}</div>
                <div className="mt-1 text-tag text-ink-3">综合评分</div>
              </div>
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <MiniRadar report={report} />
            </div>
          </div>

          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="mb-1 text-aux font-semibold text-ink">必备设施三要素</div>
            <div className="flex flex-wrap gap-2 py-2">
              {report.scores.triads.map((t) => (
                <span
                  key={t.facility}
                  className={`inline-flex items-center gap-1.5 rounded-chip px-2.5 py-1 text-tag font-medium ${
                    t.covered ? 'bg-ok/10 text-primary-deep' : 'bg-warn/10 text-ink-2'
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${t.covered ? 'bg-ok' : 'bg-warn'}`} />
                  {t.facility} · {t.covered ? `最近 ${t.nearest_minutes}min` : '1km 内缺失'}
                </span>
              ))}
            </div>
            <StatRow label="POI 采集" value={`${report.poi.total} 个（圈内 ${report.poi.in_circle}）`} />
            <StatRow label="采样点" value={`${report.sampling.points.length} 个（可达 ${report.sampling.points.filter((p) => p.reachable).length}）`} />
            <StatRow label="15min 等时圈面积" value={`${(report.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0).toFixed(2)} km²`} />
            <StatRow label="服务盲区" value={`${report.blindspots.length} 处`} />
            <button
              onClick={() => targetReportId && navigate(`/report/${targetReportId}`)}
              disabled={!targetReportId}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-4 h-10 font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <FileText size={15} /> 查看{USE_MOCK ? '体检报告' : '最新报告'}
            </button>
          </div>

          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
              <TriangleAlert size={15} className="text-warn" /> 服务盲区清单
            </div>
            {report.blindspots.length === 0 ? (
              <p className="text-tag text-ink-3">覆盖良好，未发现 1km 服务盲区</p>
            ) : (
              <div className="flex flex-col gap-2">
                {report.blindspots.map((b) => (
                  <div key={b.id} className="rounded-btn border border-line/70 bg-ink-3/10 p-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-aux font-medium text-ink">{b.id.replace('bs-', '盲区 ')}</span>
                      <span className="text-tag text-ink-3">{b.center[0].toFixed(4)},{b.center[1].toFixed(4)}</span>
                    </div>
                    <div className="mt-1 text-tag text-ink-3">
                      缺失：{b.missing_facilities.join(' / ')}
                    </div>
                    <div className="mt-0.5 text-tag text-ink-3">
                      {b.nearest[0]?.facility === 'market' ? `最近菜市 ${b.nearest[0]?.name ?? ''} ${b.nearest[0]?.distance_m}m·${b.nearest[0]?.direction}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* A4 演示流水线 overlay：回放 SSE 事件流 */}
      {playing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-card border border-line bg-card p-6 shadow-float">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                <Play size={15} className="text-primary" /> 常青圈 · 体检流水线
              </div>
              <button onClick={() => stopDemoFlow(true)} title="跳过并直接查看报告" className="grid h-8 w-8 place-items-center rounded-btn text-ink-3 hover:bg-primary-tint">
                <X size={15} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {LC_STAGES.map((s) => (
                <span
                  key={s}
                  className={`rounded-chip px-2 py-1 text-tag font-medium ${
                    LC_STAGES.indexOf(s) < LC_STAGES.indexOf(playStage)
                      ? 'bg-ok/15 text-ok'
                      : s === playStage
                        ? 'bg-primary text-white'
                        : 'bg-bg text-ink-3'
                  }`}
                >
                  {stageLabel(s)}
                </span>
              ))}
            </div>
            <div className="mt-4">
              <div className="flex items-center justify-between text-tag text-ink-3">
                <span className="truncate pr-3">{playMsg || '流水线启动中…'}</span>
                <span className="shrink-0">{playProgress}%</span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-chip bg-line">
                <div className="h-full rounded-chip bg-primary transition-all duration-200" style={{ width: `${playProgress}%` }} />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between gap-2">
              <span className="text-tag text-ink-3">演示数据 · 事件契约与 M3 真实 SSE 一致（A4）</span>
              <button
                onClick={() => stopDemoFlow(true)}
                className="rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
              >
                跳过并查看报告
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
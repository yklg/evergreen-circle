/**
 * 常青圈 · 生活圈体检报告双层视图（F3 · A1 渲染适配器的 living_circle 分支）。
 *
 * 结构（D3 同页上下 + 锚点）：
 *   ① 顶层体检单（sticky 摘要条 + 首屏整单）—— 地图快照 / 总评分 / 雷达 / 三要素 / 盲区清单
 *   ② 下层完整章节报告 —— 医疗/教育/购物/养老/可达性/盲区/结论逐章（专家署名 + 图表 + 溯源）
 *
 * M 阶段 BMapGL 接入后仅替换快照渲染层，页面骨架不变。
 */
import { useNavigate } from 'react-router-dom'
import {
  ChevronLeft,
  MapPin,
  Timer,
  TriangleAlert,
  Radar,
  Users,
  ArrowDown,
  GitCompare,
  Database,
  Sparkles,
} from 'lucide-react'
import type { Report, LivingCircleReport, LngLat, FacilityCategoryStat } from '../../types'
import {
  LC_CANVAS,
  LC_CAT_COLOR,
  LC_CAT_LABEL_OF,
  LC_ISO_COLORS,
  lcPolyPts,
  lcRightmost,
  lcToPx,
  scoreGrade,
} from '../../lib/livingCircle'
import { MiniRadar } from './MiniRadar'
import { VChart } from '../VChart'
import { VDataGrid } from '../VDataGrid'
import { LC_EXPERT } from '../../mocks/livingCircleReports'

/* ── 地图快照（静态投影，非交互） ─────────────────────────── */
function IsochroneSnapshot({ lc }: { lc: LivingCircleReport }) {
  const { W, H } = LC_CANVAS
  const center: LngLat = lc.scene.center
  const isoZones = lc.isochrones
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full select-none" role="img" aria-label="等时圈快照">
      <rect x={0} y={0} width={W} height={H} fill="#f9faf8" />
      {[-2, -1, 0, 1, 2].map((i) => (
        <line key={`v${i}`} x1={W / 2 + (i * W) / 5} y1={0} x2={W / 2 + (i * W) / 5} y2={H} stroke="#e7ebe7" strokeWidth={1} />
      ))}
      {[-2, -1, 0, 1, 2].map((i) => (
        <line key={`h${i}`} x1={0} y1={H / 2 + (i * H) / 5} x2={W} y2={H / 2 + (i * H) / 5} stroke="#e7ebe7" strokeWidth={1} />
      ))}
      {[...isoZones].sort((a, b) => b.minutes - a.minutes).map((z) => {
        const color = LC_ISO_COLORS[isoZones.findIndex((x) => x.minutes === z.minutes)] ?? LC_ISO_COLORS[0]
        const ring = z.geojson.coordinates[0]
        const [lx, ly] = lcRightmost(center, ring)
        return (
          <g key={z.minutes}>
            <polygon points={lcPolyPts(center, ring)} fill={color.fill} stroke={color.stroke} strokeWidth={1.5} strokeLinejoin="round" />
            <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>
              {z.minutes} min
            </text>
          </g>
        )
      })}
      {lc.blindspots.map((b) => (
        <g key={b.id}>
          <polygon points={lcPolyPts(center, b.polygon.coordinates[0])} fill="rgba(120,120,120,0.16)" stroke="#8a8a8a" strokeWidth={1} strokeDasharray="5 4" />
          <circle cx={lcToPx(center, b.center[0], b.center[1])[0]} cy={lcToPx(center, b.center[0], b.center[1])[1]} r={5} fill="#E8B54D" stroke="#fff" strokeWidth={1.5} />
        </g>
      ))}
      {lc.poi.categories.map((c: FacilityCategoryStat, idx) => {
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
              {lc.scene.name}
            </text>
          </g>
        )
      })()}
    </svg>
  )
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line/60 py-1.5 last:border-0">
      <span className="text-tag text-ink-3">{label}</span>
      <span className="text-aux font-medium text-ink">{value}</span>
    </div>
  )
}

/** 章节锚点跳转（sticky 摘要条内） */
function jumpToSection(id: string) {
  document.getElementById(`lc-sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export default function LifeCircleReportView({ report }: { report: Report }) {
  const navigate = useNavigate()
  const lc = report.living_circle as LivingCircleReport
  const grade = scoreGrade(lc.scores.total)
  // 报告 id 形如 lc-{sceneId}，反推样区路由参数（如 lc-kaili → kaili）
  const sceneKey = report.id.startsWith('lc-') ? report.id.slice(3) : 'kaili'
  const reachable = lc.sampling.points.filter((p) => p.reachable).length
  const area15 = lc.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      {/* sticky 摘要条：场景 + 评分 + 盲区 + 锚点导航 */}
      <header className="sticky top-0 z-30 border-b border-line bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-2.5">
          <button
            onClick={() => navigate(`/life-circle/${sceneKey}`)}
            title="返回体检地图"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="flex min-w-0 items-center gap-2">
            <MapPin size={15} className="shrink-0 text-primary" />
            <span className="truncate text-aux font-semibold text-ink">{lc.scene.name} · 生活圈体检报告</span>
            <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag font-medium text-primary-deep">体检单</span>
            {lc.data_origin === 'fixture_sample' && (
              <span className="hidden rounded-chip border border-warn/60 bg-warn/10 px-2 py-0.5 text-tag text-ink-2 sm:inline">演示数据</span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-4">
            <span className="hidden items-center gap-1 text-tag text-ink-2 md:inline-flex">
              <Timer size={13} /> 15min 圈 {area15.toFixed(2)} km²
            </span>
            <span className="hidden items-center gap-1 text-tag text-ink-2 md:inline-flex">
              <TriangleAlert size={13} className="text-warn" /> 盲区 {lc.blindspots.length} 处
            </span>
            <button
              onClick={() => navigate('/compare')}
              className="inline-flex items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
            >
              <GitCompare size={14} /> 双样例对比
            </button>
          </div>
        </div>
        {/* 章节锚点 */}
        <nav className="mx-auto flex max-w-6xl items-center gap-1.5 overflow-x-auto px-6 pb-2">
          {report.toc.map((t) => (
            <button
              key={t.id}
              onClick={() => jumpToSection(t.id)}
              className="shrink-0 rounded-chip bg-bg px-2.5 py-1 text-tag text-ink-2 transition-colors hover:bg-primary-tint hover:text-primary-deep"
            >
              {t.title}
            </button>
          ))}
        </nav>
      </header>

      {/* 可滚动区 */}
      <div className="flex-1 overflow-y-auto">
        {lc.data_origin === 'fixture_sample' && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-center gap-2 rounded-card border border-warn/40 bg-warn/10 px-4 py-2 text-tag text-ink-2">
              <InfoBadge /> 演示数据模式（fixture_sample）：等时圈为圆形近似，M5 阶段由真实百度 API 路网测时覆写
            </div>
          </div>
        )}

        {/* ① 顶层体检单（一屏） */}
        <section className="mx-auto max-w-6xl px-6 pt-5" aria-label="体检单">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
            {/* 左：地图快照 + 图例 */}
            <div className="relative overflow-hidden rounded-card border border-line bg-card shadow-card">
              <IsochroneSnapshot lc={lc} />
              <div className="absolute left-3 top-3 flex max-w-[150px] flex-col gap-1 rounded-btn border border-line bg-card/90 p-2.5 backdrop-blur">
                <span className="text-tag font-medium text-ink-2">图层</span>
                {Object.entries(LC_CAT_COLOR).slice(0, 6).map(([k, v]) => (
                  <span key={k} className="flex items-center gap-1.5 text-tag text-ink-3">
                    <span className="h-2 w-2 rounded-full" style={{ background: v }} />
                    {LC_CAT_LABEL_OF(k)}
                  </span>
                ))}
              </div>
            </div>

            {/* 右：评分 + 三要素 + 汇总 */}
            <div className="flex flex-col gap-4">
              <div className="rounded-card border border-line bg-card p-4 shadow-card">
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-aux font-semibold text-ink">{lc.scene.name} · 体检单</div>
                    <div className="mt-0.5 text-tag text-ink-3">
                      {lc.scene.city} · {lc.scene.address}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-serif text-[40px] font-semibold leading-none" style={{ color: grade.color }}>
                      {lc.scores.total}
                    </div>
                    <div className="mt-1 text-tag text-ink-3">
                      综合评分 · {grade.label}
                    </div>
                  </div>
                </div>
                <div className="mt-3 border-t border-line pt-3">
                  <MiniRadar report={lc} />
                </div>
              </div>

              <div className="rounded-card border border-line bg-card p-4 shadow-card">
                <div className="mb-1 text-aux font-semibold text-ink">必备设施三要素（1km）</div>
                <div className="flex flex-wrap gap-2 py-2">
                  {lc.scores.triads.map((t) => (
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
                <StatRow label="POI 采集" value={`${lc.poi.total} 个（圈内 ${lc.poi.in_circle}）`} />
                <StatRow label="采样点" value={`${lc.sampling.points.length} 个（可达 ${reachable}）`} />
                <StatRow label="15min 等时圈面积" value={`${area15.toFixed(2)} km²`} />
                <StatRow label="服务盲区" value={`${lc.blindspots.length} 处`} />
              </div>
            </div>
          </div>

          {/* 盲区清单（体检单内嵌） */}
          {lc.blindspots.length > 0 && (
            <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
              <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
                <TriangleAlert size={15} className="text-warn" /> 服务盲区清单（{lc.blindspots.length}）
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {lc.blindspots.map((b) => (
                  <div key={b.id} className="rounded-btn border border-line/70 bg-bg p-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-aux font-medium text-ink">{b.id.replace(/^bs-/, '盲区 ')}</span>
                      <span className="text-tag text-ink-3">
                        {b.center[0].toFixed(4)},{b.center[1].toFixed(4)}
                      </span>
                    </div>
                    <div className="mt-1 text-tag text-ink-3">缺失：{b.missing_facilities.join(' / ')}</div>
                    {b.nearest[0] && (
                      <div className="mt-0.5 text-tag text-ink-3">
                        最近「{b.nearest[0].name}」{Math.round(b.nearest[0].distance_m)}m·{b.nearest[0].direction}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4 flex justify-center pb-4">
            <button
              onClick={() => report.toc[0] && jumpToSection(report.toc[0].id)}
              className="inline-flex items-center gap-2 rounded-btn bg-primary px-5 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
            >
              查看完整章节报告 <ArrowDown size={16} />
            </button>
          </div>
        </section>

        {/* ② 下层完整章节报告 */}
        <main className="mx-auto max-w-4xl px-6 py-8">
          <div className="mb-6 flex items-center gap-2">
            <Radar size={17} className="text-primary" />
            <h2 className="font-serif text-h2 text-ink">完整章节报告</h2>
            <span className="ml-auto flex items-center gap-1 text-tag text-ink-3">
              <Users size={13} /> {report.experts.length} 位规划专家署名
            </span>
          </div>

          <div className="space-y-10">
            {report.sections.map((sec, idx) => (
              <section key={sec.id} id={`lc-sec-${sec.id}`} className="scroll-mt-28">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-card bg-primary-tint font-serif text-[18px] font-semibold text-primary-deep">
                    {idx + 1}
                  </span>
                  <h3 className="font-serif text-h2 text-ink">{sec.title}</h3>
                </div>

                {sec.key_takeaway && (
                  <div className="mt-3 flex gap-3 rounded-card border-l-[3px] border-primary bg-primary-tint/40 p-4">
                    <Sparkles size={18} className="mt-0.5 shrink-0 text-primary-deep" />
                    <p className="text-body font-medium text-ink">{sec.key_takeaway}</p>
                  </div>
                )}

                {sec.paragraphs && sec.paragraphs.length > 0 && (
                  <div className="mt-4 space-y-3">
                    {sec.paragraphs.map((p, i) => (
                      <p key={i} className="text-body leading-relaxed text-ink-2">
                        {p}
                      </p>
                    ))}
                  </div>
                )}

                {sec.claims && sec.claims.length > 0 && (
                  <div className="mt-5 space-y-2.5">
                    {sec.claims.map((c) => (
                      <div key={c.claim_id} className="flex items-start gap-2.5 rounded-card border border-line/60 bg-card/70 p-3">
                        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-chip bg-primary-tint text-[12px] font-semibold text-primary-deep">
                          {c.author[0]}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-aux leading-relaxed text-ink">{c.text}</p>
                          {c.cross_validated && (
                            <div className="mt-1 flex items-center gap-2">
                              <span className="inline-flex items-center gap-1 rounded-chip bg-ok/10 px-1.5 py-0.5 text-tag font-medium text-ok">
                                交叉验证
                              </span>
                              <span className="rounded-chip bg-primary-tint px-1.5 py-0.5 text-tag text-primary-deep">
                                {c.author} 署名
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {sec.charts && sec.charts.length > 0 && (
                  <div className="mt-5 grid grid-cols-1 gap-4">
                    {sec.charts.map((c) => (
                      <VChart key={c.chart_id} spec={c} />
                    ))}
                  </div>
                )}

                {sec.data_grid && <div className="mt-5"><VDataGrid grid={sec.data_grid} title={`${sec.title} · 盲区明细`} /></div>}

                {/* 章节溯源 + 专家署名 */}
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line/60 pt-3">
                  {sec.source_evidence_ids && sec.source_evidence_ids.length > 0 && (
                    <span className="inline-flex items-center gap-1 text-tag text-ink-3" title={sec.source_evidence_ids.slice(0, 3).join(', ')}>
                      <Database size={13} /> 证据 {sec.source_evidence_ids.length} 条
                    </span>
                  )}
                  <span className="text-tag text-ink-3">本章署名：</span>
                  {(sec.claims ?? []).slice(0, 1).map((c) => {
                    const e = LC_EXPERT[c.author] ?? { name: c.author, role: '规划专家' }
                    return (
                      <span key={c.claim_id} className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">
                        {e.name} · {e.role}
                      </span>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>

          {/* 术语表 + 方法论 */}
          <section className="mt-10 border-t border-line pt-6">
            <div className="text-aux font-semibold text-ink">术语表</div>
            <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {report.glossary.map((g) => (
                <div key={g.term} className="rounded-card border border-line/60 bg-card/60 p-3">
                  <div className="text-aux font-semibold text-ink">{g.term}</div>
                  <p className="mt-1 text-tag leading-relaxed text-ink-2">{g.definition}</p>
                </div>
              ))}
            </div>
            {report.methodology?.note && (
              <p className="mt-4 rounded-card border border-dashed border-line bg-bg/60 p-3 text-tag leading-relaxed text-ink-3">
                方法论：{report.methodology.note}
              </p>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

function InfoBadge() {
  return <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-warn/20 text-[11px] font-bold text-warn">i</span>
}
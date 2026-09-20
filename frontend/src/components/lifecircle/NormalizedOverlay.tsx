/**
 * 常青圈 · 归一化形状对比示意（跨城圈形对比）。
 *
 * 真实地理位置跨城（北京 vs 昆明）时，把 A/B 两社区各自的等时圈用各自 center
 * 归一投影（lcToPx 以自家 center 为画布中心）后，叠加在同一坐标系——两圈中心对齐，
 * 对比的是「圈形/面积几何差异」（即等时圈面积/形状差异表的视觉化），
 * 不代表真实相对距离。顶部横幅明确标注避免误导。
 */
import type { LivingCircleReport } from '../../types'
import { LC_CANVAS, lcPolyPts } from '../../lib/livingCircle'

interface IsoRing {
  minutes: number
  points: string
}

/** 等时圈 15min 面积（km²），用于尺度感知与层序。 */
function area15(lc: LivingCircleReport): number {
  return lc.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0
}

/** 把一份报告的等时圈族归一投影为 polygon points（大圈先画、小圈后画，分钟绑定）。 */
function ringsOf(lc: LivingCircleReport): IsoRing[] {
  return [...lc.isochrones]
    .sort((x, y) => x.minutes - y.minutes)
    .map((z) => ({ minutes: z.minutes, points: lcPolyPts(lc.scene.center, z.geojson.coordinates[0] ?? []) }))
    .reverse()
}

export function NormalizedOverlay({ a, b }: { a: LivingCircleReport; b: LivingCircleReport }) {
  const { W, H } = LC_CANVAS
  const [cx, cy] = [W / 2, H / 2]
  const rings = { a: ringsOf(a), b: ringsOf(b) }
  // 等高线分层编码：面积小者后画（置顶）+ 白 halo 反衬，保证小场景圈层恒可见
  const scenes = [
    { key: 'a', rings: rings.a, name: a.scene.name, area: area15(a), line: '#5F7B69', fill: 'rgba(124,152,133,0.07)', w: 2 },
    { key: 'b', rings: rings.b, name: b.scene.name, area: area15(b), line: '#1677ff', fill: 'rgba(22,119,255,0.08)', w: 2.5 },
  ].sort((x, y) => y.area - x.area) // 从大画到小，最后一个即最小（顶层）
  // 图例行：超长名 = 头6字 + 省略号 + 尾4字（保留可识别尾部），全文以悬停 title 承载
  const legend =
    scenes.length === 2
      ? scenes.map((s) => ({
          ...s,
          short: s.name.length > 10 ? `${s.name.slice(0, 6)}…${s.name.slice(-4)}` : s.name,
        }))
      : []
  const LX = W - 340
  return (
    <div className="mx-auto flex h-full w-full max-w-[520px] flex-col rounded-card border border-line/60 bg-card p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-aux font-semibold text-ink">圈形对比 · 归一化示意</div>
      </div>
      <div className="relative min-h-0 flex-1">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-full w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="两社区等时圈归一化圈形对比示意">
          <defs>
            <filter id="normalized-legend-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="1" stdDeviation="2" floodColor="#000" floodOpacity="0.12" />
            </filter>
          </defs>
          <rect x={0} y={0} width={W} height={H} fill="#f9faf8" />
          {/* 参考网格：十字 + 等米征信圈（示意尺度，非真实地理网格） */}
          <line x1={W / 2} y1={22} x2={W / 2} y2={H - 22} stroke="#e7ebe7" strokeWidth={1} />
          <line x1={22} y1={H / 2} x2={W - 22} y2={H / 2} stroke="#e7ebe7" strokeWidth={1} />
          {[1, 2, 3].map((k) => {
            const rx = (LC_CANVAS.R / 3) * k
            return <circle key={k} cx={cx} cy={cy} r={(rx / LC_CANVAS.R) * (W / 2)} fill="none" stroke="#e9eee9" strokeWidth={1} />
          })}
          {scenes.map((s, si) =>
            s.rings.map((r) => (
              <g key={`${s.key}-${r.minutes}`}>
                {si === scenes.length - 1 && (
                  <polygon points={r.points} fill="none" stroke="#ffffff" strokeWidth={6} strokeLinejoin="round" style={{ opacity: 0.9 }} />
                )}
                <polygon
                  points={r.points}
                  fill={s.fill}
                  stroke={s.line}
                  strokeWidth={si === scenes.length - 1 ? s.w + 1 : s.w}
                  strokeLinejoin="round"
                />
              </g>
            )),
          )}
          {scenes.map((s, si) => {
            // 中心彩色锚点：A 上、B 下，横向错开避免极端缩放叠压
            const ox = si === 0 ? -10 : 10
            const oy = si === 0 ? -6 : 6
            return (
              <g key={`${s.key}-anchor`}>
                <circle cx={cx + ox} cy={cy + oy} r={11} fill={s.line} />
                <text x={cx + ox} y={cy + oy + 4} fontSize={12} fill="#fff" textAnchor="middle" fontWeight={700}>
                  {s.key.toUpperCase()}
                </text>
              </g>
            )
          })}
          {/* 右上图例面板：白底 + 阴影，圆点·A·短线 + 名称·面积（完整名悬停） */}
          {legend.length === 2 && (
            <g data-testid="overlay-legend" filter="url(#normalized-legend-shadow)">
              <rect x={LX} y={16} width={324} height={64} rx={8} fill="#ffffff" stroke="#e5e7eb" strokeWidth={1} />
              {legend.map((s, si) => {
                const ly = 40 + si * 26
                return (
                  <g key={s.key}>
                    <title>{s.name}</title>
                    <circle cx={LX + 24} cy={ly - 5} r={5} fill={s.line} />
                    <text x={LX + 38} y={ly} fontSize={12.5} fill="#4b5563" fontWeight={600} textAnchor="middle">
                      {s.key.toUpperCase()}
                    </text>
                    <line x1={LX + 62} y1={ly - 5} x2={LX + 92} y2={ly - 5} stroke={s.line} strokeWidth={3} />
                    <text x={LX + 100} y={ly} fontSize={12.5} fill="#111827" fontWeight={500}>
                      {s.short} · {s.area.toFixed(2)} km²
                    </text>
                  </g>
                )
              })}
            </g>
          )}
        </svg>
        <div className="absolute bottom-2 left-2 inline-flex items-center gap-2 rounded-lg border border-warn/50 bg-amber-50/90 px-2.5 py-1.5 text-tag font-medium text-ink-2 shadow-sm">
          <span className="w-0.5 self-stretch rounded-full bg-[#e8590c]" aria-hidden />
          <span>两圈中心已归一对齐 · 仅对比圈形/面积，不代表真实相对位置</span>
        </div>
      </div>
      {rings.b.length ? (
        <p className="mt-2 text-tag text-ink-3">
          等时圈层：{[...rings.a].reverse().map((r) => r.minutes).join('/')} min（A 绿系） 与{' '}
          {[...rings.b].reverse().map((r) => r.minutes).join('/')} min（B 蓝系）
        </p>
      ) : null}
    </div>
  )
}
import { projectPoints, type GeoPoint } from '../lib/spotProjection'
import { matchSketchTemplate } from '../lib/spotSketchTemplates'

/** N6 景点分布图（B 自绘 SVG 海报）：真实经纬度线性投影 + 目的地模板化手绘底形。
 * 消费 route_plan 块数据（停靠点随冻结实体带入 lat/lng）；坐标点 <2 时整体缺位，
 * 由调用方（VRoutePlan）回落为「仅时间线」。投影在 lib/spotProjection.ts（纯函数），
 * 湖形/路网模板在 lib/spotSketchTemplates.ts（数据资产层）——本组件零 per-destination 硬编码。 */

type Row = Record<string, unknown>

const W = 640
const H = 420
// 与后端 charts.py SERIES 同一色板（分日色带）
const DAY_COLORS = ['#7C9885', '#E0B775', '#8FA8C0', '#CE9A92', '#A8C0A8', '#C2B59B']
const KAI = "'Kaiti SC','STKaiti','KaiTi',serif"

type Stop = { id: string; name: string; lat: number; lng: number; transport: string; duration: string }

function stopsOf(group: Row): Stop[] {
  const out: Stop[] = []
  for (const day of (group.days as Row[]) || []) {
    for (const s of (day.spots as Row[]) || []) {
      // null 坐标（未 matched/商铺停靠）→ NaN 被滤，绝不当 0 度入图
      const lat = s.lat == null ? NaN : Number(s.lat)
      const lng = s.lng == null ? NaN : Number(s.lng)
      const name = String(s.name ?? '')
      if (!name || !Number.isFinite(lat) || !Number.isFinite(lng)) continue
      out.push({
        id: String(s.spot_id || name), name, lat, lng,
        transport: String(s.transport ?? ''), duration: String(s.duration ?? ''),
      })
    }
  }
  return out
}

function daySegments(group: Row): Stop[][] {
  return ((group.days as Row[]) || [])
    .map((day) => {
      const ids = new Set<string>()
      for (const s of (day.spots as Row[]) || []) ids.add(String(s.name ?? ''))
      return stopsOf(group).filter((st) => ids.has(st.name))
    })
    .filter((seg) => seg.length > 0)
}

export function VSpotSketch({ data }: { data: Row[] }) {
  const groups = (data || []).filter((g) => stopsOf(g).length >= 2).slice(0, 1)
  if (!groups.length) return null
  return (
    <div className="space-y-4">
      {groups.map((g, gi) => <Poster key={gi} group={g} />)}
    </div>
  )
}

function Poster({ group }: { group: Row }) {
  const stops = stopsOf(group)
  const dest = String(group.destination ?? '')
  const tpl = matchSketchTemplate(dest)
  const geo: GeoPoint[] = stops.map((s) => ({ id: s.id, lat: s.lat, lng: s.lng }))
  const proj = new Map(projectPoints(geo, W, H, 56).map((p) => [p.id, p]))
  const segs = daySegments(group)

  return (
    <div data-spot-sketch className="overflow-hidden rounded-card border border-line bg-[#F6EFDE] shadow-card">
      <div className="flex items-baseline justify-between px-4 py-2">
        <span className="text-aux font-semibold text-ink" style={{ fontFamily: KAI }}>
          {dest} · 景点分布示意图
        </span>
        <span className="text-tag text-ink-3">点位 = 真实经纬度投影 · 连线 = 逐日行程</span>
      </div>
      <div className="flex flex-col gap-3 p-3 md:flex-row">
        <svg viewBox={`0 0 ${W} ${H}`} className="min-w-0 flex-1" role="img"
          aria-label={`${dest}景点分布海报`}>
          {/* 模板底形（湖形 + 路网氛围线），无专属模板时抽象形 + 角标 */}
          <path d={tpl.blobPath} fill="#DCE8DC" stroke="#A8C0A8" strokeOpacity="0.6" strokeWidth="1.5" />
          {tpl.roadPaths.map((rd, i) => (
            <path key={i} d={rd} fill="none" stroke="#C2B59B" strokeWidth="1.5" strokeDasharray="1 6" strokeLinecap="round" />
          ))}
          {tpl.schematic ? (
            <text x="14" y={H - 12} fontSize="11" fill="#9A8F7A" data-schematic>底形为示意（非精确地理轮廓）</text>
          ) : null}

          {/* 分日色带路径（圆角手绘线型） */}
          {segs.map((seg, di) => {
            if (seg.length < 2) return null
            const pts = seg.map((s) => proj.get(s.id)!).filter(Boolean)
            const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
            return (
              <path key={di} d={d} data-day-path={di + 1} fill="none"
                stroke={DAY_COLORS[di % DAY_COLORS.length]} strokeWidth="3"
                strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.85" />
            )
          })}

          {/* 逐段抵达注记（direction 真实路线摘要：上一站 → 本站的交通·耗时） */}
          {segs.map((seg, di) => seg.map((s, si) => {
            if (si === 0 || !s.transport) return null
            const a = proj.get(seg[si - 1].id)
            const b = proj.get(s.id)
            if (!a || !b) return null
            return (
              <text key={`${di}-${si}`} x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4}
                fontSize="9" fill="#7A6F5C" textAnchor="middle" fontFamily={KAI} data-leg-note>
                {s.transport.length > 14 ? `${s.transport.slice(0, 14)}…` : s.transport}
              </text>
            )
          }))}

          {/* 点位 + 楷体标签 + DAY 徽章 */}
          {segs.map((seg, di) => seg.map((s, si) => {
            const p = proj.get(s.id)
            if (!p) return null
            const color = DAY_COLORS[di % DAY_COLORS.length]
            return (
              <g key={`${di}-${si}`} data-sketch-stop={s.id}>
                <circle cx={p.x} cy={p.y} r="6" fill={color} stroke="#F6EFDE" strokeWidth="2.5" />
                <text x={p.x + 9} y={p.y + 4} fontSize="12" fill="#4A4436" fontFamily={KAI}>{s.name}</text>
                {si === 0 ? (
                  <g>
                    <rect x={p.x - 16} y={p.y - 26} width="34" height="14" rx="7" fill={color} />
                    <text x={p.x + 1} y={p.y - 15.5} fontSize="9.5" fill="#FFFDF6" textAnchor="middle" fontWeight="600">
                      DAY {di + 1}
                    </text>
                  </g>
                ) : null}
              </g>
            )
          }))}
        </svg>

        {/* 侧边星星榜单：逐日停靠顺序速览（与海报同源的冻结实体序） */}
        <aside className="w-full shrink-0 rounded-btn bg-white/70 p-3 md:w-44" data-sketch-rank>
          <div className="pb-1 text-tag font-semibold text-ink">行程星榜</div>
          <ol className="space-y-1.5">
            {segs.map((seg, di) => (
              <li key={di} className="text-tag text-ink-2">
                <span className="mr-1 inline-block rounded-chip px-1.5 py-0.5 text-[10px] font-semibold text-white"
                  style={{ background: DAY_COLORS[di % DAY_COLORS.length] }}>
                  DAY{di + 1}
                </span>
                {seg.map((s) => s.name).join(' → ')}
                <span className="ml-0.5 text-warn">{'★'.repeat(Math.min(5, seg.length))}</span>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  )
}

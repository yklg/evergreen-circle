import { Check, Minus, X } from 'lucide-react'
import { useState, type ReactElement } from 'react'
import { BMapBlock, hasBMapAk, type MapSpot } from './BMapBlock'
import { VSpotSketch } from './VSpotSketch'
import type { StructuredBlock, StructuredBlockType } from '../types'

type Row = Record<string, unknown>

/* 三档支持度/覆盖度 → 图标 + 配色（full/partial/none 与后端 coerce 枚举一致） */
const TRI_ICON = { full: Check, partial: Minus, none: X } as const
const TRI_TINT = {
  full: 'bg-ok/10 text-ok',
  partial: 'bg-sun-soft text-warn',
  none: 'bg-risk/10 text-risk',
} as const

function tri(v: unknown): 'full' | 'partial' | 'none' {
  return v === 'full' || v === 'none' ? v : 'partial'
}

/* 风险等级 low|medium|high → 中文 + 配色 */
const LEVEL_LABEL: Record<string, string> = { low: '低', medium: '中', high: '高' }
const LEVEL_TINT: Record<string, string> = {
  low: 'bg-ok/10 text-ok',
  medium: 'bg-sun-soft text-warn',
  high: 'bg-risk/10 text-risk',
}

/* ── 景点实体（spots 阶段冻结的唯一实体表） ───────────────── */

/** 景点综合评分榜：规则算分（声量/口碑/性价比明细）+ 门票/停留/避峰，matched=false 显示占位。
 * selectedId/onSelect 为与地图的双向联动接缝（spot_id 为唯一挂接键）。 */
export function VSpotRanking({
  data,
  selectedId,
  onSelect,
}: {
  data: Row[]
  selectedId?: string | null
  onSelect?: (spotId: string | null) => void
}) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 景点综合评分榜
          </div>
          <table className="w-full text-tag">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="px-3 py-1.5 text-left font-medium">#</th>
                <th className="px-2 py-1.5 text-left font-medium">景点 / 区域</th>
                <th className="px-2 py-1.5 text-left font-medium">综合分（声量·口碑·性价比）</th>
                <th className="px-2 py-1.5 text-left font-medium">门票与预约</th>
                <th className="px-2 py-1.5 text-left font-medium">停留</th>
                <th className="px-2 py-1.5 text-left font-medium">避峰</th>
                <th className="px-3 py-1.5 text-left font-medium">入选理由</th>
              </tr>
            </thead>
            <tbody>
              {((d.items as Row[]) || []).map((it: Row, ii: number) => {
                const dims = (it.dims as Row) || {}
                const unmatched = it.matched === false
                const spotId = String(it.spot_id ?? '')
                const active = !!spotId && spotId === selectedId
                return (
                  <tr
                    key={ii}
                    data-spot-row={spotId}
                    data-selected={active || undefined}
                    onMouseEnter={() => onSelect?.(spotId)}
                    onClick={() => onSelect?.(spotId)}
                    className={`cursor-pointer border-b border-line/60 last:border-0 ${
                      active ? 'bg-primary-tint/60' : ''
                    }`}
                  >
                    <td className="px-3 py-1.5 font-semibold text-primary-deep">{String(it.rank ?? ii + 1)}</td>
                    <td className="px-2 py-1.5">
                      <span className="font-medium text-ink" data-spot-id={String(it.spot_id ?? '')}>
                        {String(it.name ?? '')}
                      </span>
                      {it.area ? <span className="ml-1 text-ink-3">· {String(it.area)}</span> : null}
                      {unmatched ? (
                        <span className="ml-1 rounded-chip bg-sun-soft px-1.5 py-0.5 text-tag text-warn">位置未匹配</span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-primary-deep">
                      {it.score != null ? String(it.score) : '—'}
                      <span className="ml-1 font-normal text-ink-3">
                        {dims.voice != null
                          ? `（${String(dims.voice)}·${String(dims.sentiment)}·${String(dims.value)}）`
                          : ''}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-ink-2">{String(it.ticket ?? '—')}</td>
                    <td className="px-2 py-1.5 text-ink-2">{it.stay_minutes != null ? `${String(it.stay_minutes)}分钟` : '—'}</td>
                    <td className="px-2 py-1.5 text-ink-2">{String(it.off_peak ?? '—')}</td>
                    <td className="px-3 py-1.5 text-ink-2">{String(it.reason ?? '-')}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** 榜单 ↔ 地图组合位：selected spot_id 提升于此，两子件共享（唯一挂接键仍是冻结实体 spot_id）。
 * 条图（F2 本地 CSS）恒出，不依赖 LLM/后端 spec；坐标全缺时它兼任地图的降级替身。 */
export function VSpotAtlas({ data }: { data: Row[] }) {
  const [selected, setSelected] = useState<string | null>(null)
  if (!data?.length) return null
  const spots: MapSpot[] = data
    .flatMap((d) => ((d.items as Row[]) || []) as Row[])
    .map((it) => ({
      spot_id: String(it.spot_id ?? ''),
      name: String(it.name ?? ''),
      area: it.area ? String(it.area) : undefined,
      score: typeof it.score === 'number' ? it.score : undefined,
      matched: it.matched === false ? false : undefined,
      lat: it.lat as number | null | undefined,
      lng: it.lng as number | null | undefined,
    }))
    .filter((s) => s.spot_id)
  const mappable = spots.filter(
    (s) => s.matched !== false && typeof s.lat === 'number' && typeof s.lng === 'number',
  )
  return (
    <div className="mt-4 flex flex-col gap-3">
      {mappable.length > 0 && (
        <BMapBlock spots={spots} selectedId={selected} onSelect={setSelected} />
      )}
      <VSpotRankBar data={data} />
      <VSpotRanking data={data} selectedId={selected} onSelect={setSelected} />
    </div>
  )
}

/** 分数 → 条宽（%）：0-10 与 0-100 双值域自适应归一，越界钳位；非数值 → 0。 */
export function rankBarWidth(score: unknown): number {
  const v = typeof score === 'number' && Number.isFinite(score) ? score : Number(score) || 0
  const pct = v <= 10 ? v * 10 : v
  return Math.min(100, Math.max(0, pct))
}

/** 景点 Top 榜条图（F2）：纯 CSS 横向条，评分归一映射条宽 + 数值标签 + 门票价签。 */
export function VSpotRankBar({ data }: { data: Row[] }) {
  const groups = (data || []).filter((d) => Array.isArray(d.items) && (d.items as Row[]).length > 0)
  if (groups.length === 0) return null
  return (
    <div className="space-y-4">
      {groups.map((d, di) => (
        <div key={di} data-spot-rankbar className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 景点评分条图
          </div>
          <div className="space-y-2 p-4">
            {((d.items as Row[]) || []).map((it, ii) => {
              const w = rankBarWidth(it.score)
              return (
                <div key={ii} className="flex items-center gap-2">
                  <span className="w-5 shrink-0 text-right text-tag font-semibold text-primary-deep">
                    {String(it.rank ?? ii + 1)}
                  </span>
                  <span className="w-28 shrink-0 truncate text-tag font-medium text-ink" title={String(it.name ?? '')}>
                    {String(it.name ?? '')}
                  </span>
                  <span className="h-3 min-w-0 flex-1 overflow-hidden rounded-full bg-primary-tint/60">
                    <span
                      className="block h-full rounded-full bg-primary"
                      style={{ width: `${w}%` }}
                      data-bar-width={w}
                    />
                  </span>
                  <span className="w-12 shrink-0 text-tag tabular-nums text-primary-deep">
                    {it.score != null ? String(it.score) : '—'}
                  </span>
                  {it.ticket ? (
                    <span className="hidden shrink-0 text-tag text-ink-3 sm:inline" title={String(it.ticket)}>
                      {String(it.ticket)}
                    </span>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 美食 Top 榜卡（N2）：名称 + 评分条（score 有则归一 0-10 映射）+ 人均价 chip + 品类标签 + 推荐理由；
 * 缺字段逐项回落（schema 不保证 score/price 恒在，条图与 chip 只按在位字段渲染）。 */
export function VFoodRanking({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 美食 Top 榜
          </div>
          <div className="grid grid-cols-1 gap-2.5 p-4 sm:grid-cols-2">
            {((d.items as Row[]) || []).map((it: Row, ii: number) => {
              const hasScore = it.score != null && Number.isFinite(Number(it.score))
              const w = rankBarWidth(it.score)
              return (
                <div key={ii} data-food-card className="rounded-card border border-line/60 bg-paper p-3">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="text-tag font-semibold text-primary-deep">{ii + 1}</span>
                    <span className="text-aux font-medium text-ink">{String(it.name ?? '')}</span>
                    {it.category ? (
                      <span className="rounded-chip bg-primary-tint px-1.5 py-0.5 text-tag text-primary-deep">
                        {String(it.category)}
                      </span>
                    ) : null}
                    {it.price_range ? (
                      <span className="rounded-chip bg-sun-soft px-1.5 py-0.5 text-tag text-warn">
                        人均 {String(it.price_range)}
                      </span>
                    ) : null}
                  </div>
                  {hasScore && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-card/70">
                        <span
                          className="block h-full rounded-full bg-warn"
                          style={{ width: `${w}%` }}
                          data-food-score={String(it.score)}
                        />
                      </span>
                      <span className="text-tag tabular-nums text-warn">{String(it.score)}</span>
                    </div>
                  )}
                  {it.reason ? (
                    <p className="mt-1.5 text-tag leading-relaxed text-ink-2">{String(it.reason)}</p>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 逐景点路线卡：地铁/公交/打车逐条换乘方案，默认展开 Top3。 */
export function VSpotRoutes({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="rounded-card border border-line bg-white p-4">
          <div className="mb-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 逐景点路线
          </div>
          <div className="space-y-2">
            {((d.items as Row[]) || []).map((sp: Row, si: number) => (
              <details key={si} open={si < 3} className="rounded-btn border border-line/70 bg-white">
                <summary className="cursor-pointer select-none px-3 py-1.5 text-tag font-medium text-ink">
                  {String(sp.spot_name ?? '')}
                  {sp.spot_id ? <span className="ml-1 font-normal text-ink-3">{String(sp.spot_id)}</span> : null}
                </summary>
                <div className="space-y-1.5 px-3 pb-2.5">
                  {((sp.routes as Row[]) || []).map((r: Row, ri: number) => (
                    <div key={ri} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="rounded-chip bg-paper px-1.5 py-0.5 text-tag font-medium text-primary-deep ring-1 ring-line">
                        {String(r.mode ?? '')}
                      </span>
                      {r.duration ? <span className="text-tag text-ink-2">{String(r.duration)}</span> : null}
                      {r.cost ? <span className="text-tag text-warn">{String(r.cost)}</span> : null}
                      {r.transfer ? <span className="text-tag text-ink-2">换乘：{String(r.transfer)}</span> : null}
                      {r.note ? <span className="text-tag text-ink-3">{String(r.note)}</span> : null}
                    </div>
                  ))}
                  {!(sp.routes as Row[])?.length ? (
                    <div className="text-tag text-ink-3">数据源暂不可用（路线待补充）</div>
                  ) : null}
                </div>
              </details>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 美食商铺清单：对应美食 / 商铺 / 区域 / 人均参考价 / 排队情况 / 公交路线（M3e 真实数据，缺则占位）。 */
export function VShopList({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 美食商铺（人均为参考价）
          </div>
          <table className="w-full text-tag">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="px-4 py-1.5 text-left font-medium">商铺</th>
                <th className="px-2 py-1.5 text-left font-medium">对应美食</th>
                <th className="px-2 py-1.5 text-left font-medium">区域</th>
                <th className="px-2 py-1.5 text-left font-medium">人均</th>
                <th className="px-2 py-1.5 text-left font-medium">排队情况</th>
                <th className="px-4 py-1.5 text-left font-medium">路线</th>
              </tr>
            </thead>
            <tbody>
              {((d.items as Row[]) || []).map((it: Row, ii: number) => {
                const routes = Array.isArray(it.routes) ? (it.routes as Row[]) : []
                return (
                  <tr key={ii} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-1.5 font-medium text-ink">{String(it.name ?? '')}</td>
                    <td className="px-2 py-1.5 text-ink-2">{String(it.food ?? '-')}</td>
                    <td className="px-2 py-1.5 text-ink-2">{String(it.area ?? '-')}</td>
                    <td className="px-2 py-1.5 text-primary-deep">
                      {it.price_per_person != null ? `${String(it.price_per_person)}元（参考价）` : '未公开'}
                    </td>
                    <td className="px-2 py-1.5 text-ink-2">{String(it.queue_note ?? '-')}</td>
                    <td className="px-4 py-1.5 text-ink-2">
                      {routes.length ? (
                        <span data-shop-route>
                          {routes.map((r, ri) => (
                            <span key={ri} className="block">
                              {String(r.mode ?? '')}
                              {r.duration ? ` · ${String(r.duration)}` : ''}
                              {r.transfer ? ` · ${String(r.transfer)}` : ''}
                              {r.note ? `（${String(r.note)}）` : ''}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span data-shop-route-unavailable className="text-ink-3">
                          路线数据源暂不可用
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** 逐日路线（N4/A-F1）：分布海报 + 折线地图（坐标齐时）→ 逐日时间线卡。
 * 时间线为保底形态：坐标缺/AK 缺时仅时间线，结构断言不依赖地图与海报。 */
export function VRoutePlan({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => {
        const days = (d.days as Row[]) || []
        const trail: MapSpot[] = days
          .flatMap((day) => ((day.spots as Row[]) || []) as Row[])
          .filter((s) => s.spot_id && !s.shop_id
            && typeof s.lat === 'number' && typeof s.lng === 'number')
          .map((s) => ({
            spot_id: String(s.spot_id),
            name: String(s.name ?? ''),
            lat: s.lat as number,
            lng: s.lng as number,
          }))
        const mappableTrail = trail
        return (
          <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
            <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
              {String(d.destination ?? '')} · 逐日路线
            </div>
            <div className="space-y-3 p-4">
              <VSpotSketch data={[d]} />
              {hasBMapAk() && mappableTrail.length >= 2 ? (
                <BMapBlock
                  spots={mappableTrail}
                  trail
                  height={300}
                  caption={`行程串联 · ${mappableTrail.length} 站按逐日顺序连线`}
                />
              ) : null}
              <div className="space-y-4">
                {days.map((day: Row, yi: number) => (
                  <div key={yi} className="relative pl-6">
                    <span
                      className="absolute left-0 top-0.5 inline-flex h-5 items-center rounded-chip bg-primary px-1.5 text-tag font-semibold text-white"
                      data-route-day={yi + 1}
                    >
                      Day {String(day.day ?? yi + 1)}
                    </span>
                    <div className="mt-1.5 space-y-1.5 border-l border-dashed border-line/80 pl-3">
                      {((day.spots as Row[]) || []).map((s: Row, si: number) => (
                        <div
                          key={si}
                          data-stop
                          data-spot-id={s.spot_id ? String(s.spot_id) : undefined}
                          data-shop-id={s.shop_id ? String(s.shop_id) : undefined}
                          className="relative flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-btn bg-paper px-2.5 py-1.5"
                        >
                          <span className="absolute -left-[19px] top-2.5 h-1.5 w-1.5 rounded-full bg-primary/70" />
                          <span className="text-tag font-medium text-ink">{String(s.name ?? '')}</span>
                          {s.shop_id ? <span className="rounded-full bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">美食停靠</span> : null}
                          {s.transport ? <span className="rounded-chip bg-white px-1.5 py-0.5 text-tag text-ink-3">交通：{String(s.transport)}</span> : null}
                          {s.duration ? <span className="text-tag text-ink-3">停留：{String(s.duration)}</span> : null}
                          {s.tip ? <span className="w-full text-tag text-ink-2">{String(s.tip)}</span> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** 住宿区域选型表（N5）：区域 / 价格区间 / 适合人群 / 优劣势 + 横向价位带。
 * 价位带为纯 CSS 条（区域 × 区间，按全组最大值归一）；price_min/max 缺失的
 * 区域只留在表格里看自由文本，不进带（判据不造数）。 */
export function VStayTable({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => {
        const areas = (d.areas as Row[]) || []
        const num = (v: unknown): number | null =>
          typeof v === 'number' && Number.isFinite(v) ? v : null
        const bounds = areas.map((a) => {
          const lo = num(a.price_min) ?? num(a.price_max)
          const hi = num(a.price_max) ?? lo
          return { lo, hi }
        })
        const scale = Math.max(0, ...bounds.map((b) => b.hi ?? 0))
        const bandAreas = areas
          .map((a, ai) => ({ a, b: bounds[ai] }))
          .filter((x) => x.b.lo != null && x.b.hi != null && scale > 0)
        return (
          <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
            <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
              {String(d.destination ?? '')} · 住宿区域选型
            </div>
            <table className="w-full text-tag">
              <thead>
                <tr className="border-b border-line text-ink-3">
                  <th className="px-4 py-1.5 text-left font-medium">区域</th>
                  <th className="px-2 py-1.5 text-left font-medium">价格区间</th>
                  <th className="px-2 py-1.5 text-left font-medium">适合人群</th>
                  <th className="px-4 py-1.5 text-left font-medium">优劣势</th>
                </tr>
              </thead>
              <tbody>
                {areas.map((a: Row, ai: number) => (
                  <tr key={ai} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-1.5 font-medium text-ink">{String(a.area ?? '')}</td>
                    <td className="px-2 py-1.5 text-primary-deep">{String(a.price_range ?? '未公开')}</td>
                    <td className="px-2 py-1.5 text-ink-2">{String(a.for_whom ?? '-')}</td>
                    <td className="px-4 py-1.5 text-ink-2">
                      {[...(a.pros as string[]) || [], ...((a.cons as string[]) || []).map((c) => `⚠ ${c}`)]
                        .slice(0, 3)
                        .join(' / ') || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {bandAreas.length > 0 ? (
              <div className="space-y-1.5 border-t border-line/60 bg-paper/50 px-4 py-3" data-stay-bands>
                <div className="text-tag font-medium text-ink">价位带对比（元/晚）</div>
                {bandAreas.map(({ a, b }, bi) => {
                  const left = ((b.lo ?? 0) / scale) * 100
                  const width = Math.max(3, (((b.hi ?? 0) - (b.lo ?? 0)) / scale) * 100)
                  return (
                    <div key={bi} className="flex items-center gap-2" data-stay-band={String(a.area ?? bi)}>
                      <span className="w-20 shrink-0 truncate text-tag text-ink-2">{String(a.area ?? '')}</span>
                      <div className="relative h-2.5 min-w-0 flex-1 rounded-full bg-white">
                        <div className="absolute top-0 h-full rounded-full bg-primary/80"
                          data-band-style style={{ left: `${left.toFixed(1)}%`, width: `${width.toFixed(1)}%` }} />
                      </div>
                      <span className="shrink-0 text-tag text-primary-deep">¥{b.lo}{b.hi !== b.lo ? `-${b.hi}` : ''}</span>
                    </div>
                  )
                })}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

/** 花费拆解表：分类 / 金额 / 占比。 */
export function VCostBreakdown({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 花费拆解
          </div>
          <table className="w-full text-tag">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="px-4 py-1.5 text-left font-medium">分类</th>
                <th className="px-2 py-1.5 text-left font-medium">金额</th>
                <th className="px-2 py-1.5 text-left font-medium">占比</th>
                <th className="px-4 py-1.5 text-left font-medium">说明</th>
              </tr>
            </thead>
            <tbody>
              {((d.items as Row[]) || []).map((it: Row, ii: number) => (
                <tr key={ii} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-1.5 font-medium text-ink">{String(it.category ?? '')}</td>
                  <td className="px-2 py-1.5 text-primary-deep">
                    {it.amount != null ? `${String(it.amount)}${String(it.unit ?? '')}` : '—'}
                  </td>
                  <td className="px-2 py-1.5 text-ink-2">{it.share != null ? `${String(it.share)}%` : '-'}</td>
                  <td className="px-4 py-1.5 text-ink-2">{String(it.note ?? '-')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** 可达性矩阵：交通方式 / 耗时 / 费用 / 班次频次。 */
export function VAccessMatrix({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 可达性矩阵
          </div>
          <table className="w-full text-tag">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="px-4 py-1.5 text-left font-medium">交通方式</th>
                <th className="px-2 py-1.5 text-left font-medium">耗时</th>
                <th className="px-2 py-1.5 text-left font-medium">费用</th>
                <th className="px-2 py-1.5 text-left font-medium">班次频次</th>
                <th className="px-4 py-1.5 text-left font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {((d.routes as Row[]) || []).map((r: Row, ri: number) => (
                <tr key={ri} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-1.5 font-medium text-ink">{String(r.mode ?? '')}</td>
                  <td className="px-2 py-1.5 text-ink-2">{String(r.duration ?? '-')}</td>
                  <td className="px-2 py-1.5 text-primary-deep">{String(r.cost ?? '-')}</td>
                  <td className="px-2 py-1.5 text-ink-2">{String(r.frequency ?? '-')}</td>
                  <td className="px-4 py-1.5 text-ink-2">{String(r.note ?? '-')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** 配套完善度清单：分类 / 项目 / 覆盖程度（full|partial|none）。 */
export function VAmenityChecklist({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="rounded-card border border-line bg-white p-4">
          <div className="mb-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 配套完善度
          </div>
          <div className="space-y-2.5">
            {((d.items as Row[]) || []).map((it: Row, ii: number) => {
              const level = tri(it.coverage)
              const Icon = TRI_ICON[level]
              return (
                <div key={ii} className="flex items-start gap-2">
                  <span className={`mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-chip px-2 py-0.5 text-tag ${TRI_TINT[level]}`}>
                    <Icon size={11} /> {String(it.item ?? '')}
                  </span>
                  <span className="min-w-0 text-tag text-ink-2">
                    {it.category ? <span className="text-ink-3">{String(it.category)} · </span> : null}
                    {String(it.note ?? '')}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 风险画像：风险维度 / 等级（low|medium|high）/ 说明。 */
export function VRiskProfile({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="rounded-card border border-line bg-white p-4">
          <div className="mb-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 风险画像
          </div>
          <div className="space-y-2">
            {((d.items as Row[]) || []).map((it: Row, ii: number) => {
              const level = typeof it.level === 'string' && it.level in LEVEL_TINT ? it.level : 'medium'
              return (
                <div key={ii} className="flex items-start gap-2">
                  <span className={`inline-flex shrink-0 items-center rounded-chip px-2 py-0.5 text-tag ${LEVEL_TINT[level]}`}>
                    {LEVEL_LABEL[level]}
                  </span>
                  <div className="min-w-0">
                    <span className="text-tag font-medium text-ink">{String(it.dimension ?? '')}</span>
                    {it.note ? <p className="text-tag text-ink-2">{String(it.note)}</p> : null}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/* 类型 → 渲染器（键集与后端 research_types.structured_keys 一致） */
const BLOCKS: Record<StructuredBlockType, (p: { data: Row[] }) => ReactElement | null> = {
  spot_ranking: VSpotAtlas,
  spot_routes: VSpotRoutes,
  food_ranking: VFoodRanking,
  shop_list: VShopList,
  route_plan: VRoutePlan,
  stay_options: VStayTable,
  cost_breakdown: VCostBreakdown,
  access_matrix: VAccessMatrix,
  amenity_checklist: VAmenityChecklist,
  risk_profile: VRiskProfile,
}

/** 结构化块分发。旧报告的已废弃类型（feature_tree 等）不渲染也不报错。 */
export function VStructuredBlock({ block }: { block?: StructuredBlock | null }) {
  if (!block) return null
  const Renderer = BLOCKS[block.type]
  if (!Renderer) return null
  return <Renderer data={block.data as Row[]} />
}

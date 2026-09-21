import { Check, Minus, X } from 'lucide-react'
import type { ReactElement } from 'react'
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

/** 逐日路线表：按天展示景点、交通方式、停留时长与提示。 */
export function VRoutePlan({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
        <div key={di} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="bg-paper px-4 py-2 text-aux font-semibold text-ink">
            {String(d.destination ?? '')} · 逐日路线
          </div>
          <div className="space-y-3 p-4">
            {((d.days as Row[]) || []).map((day: Row, yi: number) => (
              <div key={yi}>
                <div className="text-tag font-medium text-primary-deep">Day {String(day.day ?? yi + 1)}</div>
                <div className="mt-1.5 space-y-1.5">
                  {((day.spots as Row[]) || []).map((s: Row, si: number) => (
                    <div key={si} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-btn bg-paper px-2.5 py-1.5">
                      <span className="text-tag font-medium text-ink">{String(s.name ?? '')}</span>
                      {s.transport ? <span className="text-tag text-ink-3">交通：{String(s.transport)}</span> : null}
                      {s.duration ? <span className="text-tag text-ink-3">停留：{String(s.duration)}</span> : null}
                      {s.tip ? <span className="w-full text-tag text-ink-2">{String(s.tip)}</span> : null}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 住宿区域选型表：区域 / 价格区间 / 适合人群 / 优劣势。 */
export function VStayTable({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((d, di) => (
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
              {((d.areas as Row[]) || []).map((a: Row, ai: number) => (
                <tr key={ai} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-1.5 font-medium text-ink">{String(a.area ?? '')}</td>
                  <td className="px-2 py-1.5 text-primary-deep">{String(a.price_range ?? '未公开')}</td>
                  <td className="px-2 py-1.5 text-ink-2">{String(a.for_whom ?? '-')}</td>
                  <td className="px-4 py-1.5 text-ink-2">
                    {[...((a.pros as string[]) || []), ...((a.cons as string[]) || []).map((c) => `⚠ ${c}`)]
                      .slice(0, 3)
                      .join(' / ') || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
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

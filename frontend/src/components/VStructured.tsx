import { Check, Minus, X } from 'lucide-react'

type Row = Record<string, unknown>

/** 功能树矩阵：展示各品牌的功能模块与支持程度。 */
export function VFeatureMatrix({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((brand, bi) => (
        <div key={bi} className="rounded-card border border-line bg-white p-4">
          <div className="mb-2 text-aux font-semibold text-ink">{String(brand.brand ?? '')} · 功能树</div>
          <div className="space-y-2.5">
            {((brand.modules as Row[]) || []).map((m: Row, mi: number) => (
              <div key={mi}>
                <div className="text-tag font-medium text-primary-deep">
                  {m.category ? `${String(m.category)} · ` : ''}{String(m.name ?? '')}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {((m.sub_features as Row[]) || []).map((sf: Row, si: number) => {
                    const Icon = sf.support === 'full' ? Check : sf.support === 'none' ? X : Minus
                    const tint =
                      sf.support === 'full' ? 'bg-ok/10 text-ok'
                        : sf.support === 'none' ? 'bg-risk/10 text-risk'
                          : 'bg-sun-soft text-warn'
                    return (
                      <span key={si} title={String(sf.note ?? '')} className={`inline-flex items-center gap-1 rounded-chip px-2 py-0.5 text-tag ${tint}`}>
                        <Icon size={11} /> {String(sf.name ?? '')}
                      </span>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 定价模型表：展示各品牌的定价档位。 */
export function VPricingTable({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-4">
      {data.map((brand, bi) => (
        <div key={bi} className="overflow-hidden rounded-card border border-line bg-white">
          <div className="flex items-center justify-between bg-bg px-4 py-2">
            <span className="text-aux font-semibold text-ink">{String(brand.brand ?? '')}</span>
            <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">
              {String(brand.model_type ?? '')}{brand.free_tier ? ' · 含免费版' : ''}
            </span>
          </div>
          <table className="w-full text-tag">
            <thead>
              <tr className="border-b border-line text-ink-3">
                <th className="px-4 py-1.5 text-left font-medium">档位</th>
                <th className="px-2 py-1.5 text-left font-medium">价格</th>
                <th className="px-2 py-1.5 text-left font-medium">目标用户</th>
                <th className="px-4 py-1.5 text-left font-medium">主要权益</th>
              </tr>
            </thead>
            <tbody>
              {((brand.tiers as Row[]) || []).map((t: Row, ti: number) => (
                <tr key={ti} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-1.5 font-medium text-ink">{String(t.name ?? '')}</td>
                  <td className="px-2 py-1.5 text-primary-deep">
                    {t.price != null ? `${String(t.price)}${String(brand.currency ?? '')}/${String(t.period ?? '')}` : '未公开'}
                  </td>
                  <td className="px-2 py-1.5 text-ink-2">{String(t.target_user ?? '-')}</td>
                  <td className="px-4 py-1.5 text-ink-2">{((t.includes as string[]) || []).slice(0, 3).join('、') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** 用户画像卡：展示各品牌的核心用户画像。 */
export function VPersonaCards({ data }: { data: Row[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-4 space-y-3">
      {data.map((brand, bi) =>
        ((brand.personas as Row[]) || []).map((p: Row, pi: number) => {
          const needs = (p.needs as string[]) || []
          const scenarios = (p.scenarios as string[]) || []
          const painPoints = (p.pain_points as string[]) || []
          const decisionFactors = (p.decision_factors as string[]) || []
          return (
            <div key={`${bi}-${pi}`} className="rounded-card border border-line bg-white p-4">
              <div className="flex items-center gap-2">
                <span className="text-aux font-semibold text-ink">{String(p.name ?? '')}</span>
                <span className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-3">{String(brand.brand ?? '')}</span>
                {p.segment ? <span className="text-tag text-ink-3">· {String(p.segment)}</span> : null}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-tag">
                {needs.length > 0 && <Field label="核心需求" items={needs} />}
                {scenarios.length > 0 && <Field label="使用场景" items={scenarios} />}
                {painPoints.length > 0 && <Field label="痛点" items={painPoints} />}
                {decisionFactors.length > 0 && <Field label="决策因素" items={decisionFactors} />}
              </div>
              {p.migration_cost ? (
                <p className="mt-2 rounded-btn bg-bg px-2.5 py-1.5 text-tag text-ink-2">
                  迁移成本：{String(p.migration_cost)}
                </p>
              ) : null}
            </div>
          )
        }),
      )}
    </div>
  )
}

function Field({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="text-ink-3">{label}</div>
      <div className="text-ink-2">{items.slice(0, 4).join('、')}</div>
    </div>
  )
}

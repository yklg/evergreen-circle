import { useCallback, useState } from 'react'
import { ArrowUpRight, BellPlus, Rss } from 'lucide-react'
import { VCard } from '../../components/ui'
import { useResource, type Resource } from '../../hooks/useResource'
import { createSubscription, fetchEvidences, fetchSubscriptions } from '../../lib/api'
import type { DestinationGraphNode, Subscription } from '../../types'

/**
 * C6 · 全局证据溯源库 + 目的地持续追踪（2:1 双栏，沿用源页版式）。
 *
 * 两处口径写死：
 * - 证据流是**分页样本**（端点 limit 默认 200），卡角必须写明"当前 N 条 / 库内共 M 条"，
 *   否则又会拿截断样本冒充全量——那正是本轮要消灭的形状；
 * - 建订阅**必须带目的地**：后端 `destinations` 目前仍带默认值，空数组会建成一条
 *   永不复跑的订阅（比报错更坏），所以这里前端直接拒发并说明成因。
 */
export default function EvidenceAndTracking({
  enabled,
  refreshToken,
  nodes,
  evidenceTotal,
}: {
  enabled: boolean
  refreshToken: number
  nodes: DestinationGraphNode[]
  evidenceTotal: number
}) {
  const [destination, setDestination] = useState<string | null>(null)
  const [sourceType, setSourceType] = useState<string | null>(null)

  const load = useCallback(
    () =>
      fetchEvidences({
        destination: destination ?? undefined,
        source_type: sourceType ?? undefined,
      }),
    [destination, sourceType],
  )
  const ev = useResource(load, enabled, refreshToken)
  const subs = useResource(useCallback(() => fetchSubscriptions(), []), enabled, refreshToken)

  const items = ev.data?.items ?? []
  const facets = ev.data?.facets

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <VCard hover={false} className="lg:col-span-2">
        <div className="flex items-baseline gap-2">
          <h3 className="text-aux font-semibold text-ink">全局证据溯源库</h3>
          <span className="text-tag text-ink-3">
            当前 {items.length} 条 · 库内共 {evidenceTotal} 条
            {destination ? ` · 目的地「${destination}」` : ''}
            {sourceType ? ` · 信源 ${sourceType}` : ''}
          </span>
        </div>

        {ev.failed ? (
          <p className="mt-3 rounded-card border border-risk/50 bg-risk/10 px-3 py-2 text-tag text-ink-2">
            证据流取数失败（下方不是"没有证据"，是没取到）。
            <button onClick={ev.reload} className="ml-2 font-medium text-primary-deep underline">
              重试
            </button>
          </p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <FilterChip on={!destination} label="全部目的地" onClick={() => setDestination(null)} />
              {(facets ? Object.keys(facets.by_destination) : []).map((d) => (
                <FilterChip
                  key={d}
                  on={destination === d}
                  label={`${d} ${facets?.by_destination[d] ?? 0}`}
                  onClick={() => setDestination(destination === d ? null : d)}
                />
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(facets ? Object.entries(facets.by_type) : []).map(([t, n]) => (
                <FilterChip
                  key={t}
                  on={sourceType === t}
                  label={`${t} ${n}`}
                  tone="type"
                  onClick={() => setSourceType(sourceType === t ? null : t)}
                />
              ))}
            </div>

            <div className="mt-3 flex max-h-[360px] flex-col gap-2 overflow-auto">
              {ev.loading && <p className="text-tag text-ink-3">正在取证据……</p>}
              {!ev.loading && items.length === 0 && (
                <p className="text-tag text-ink-3">该筛选条件下没有证据行。</p>
              )}
              {items.map((it) => (
                <article key={it.evidence_id} className="rounded-card border border-line/70 bg-bg/60 p-3">
                  <div className="flex items-start gap-2">
                    <span className="truncate text-aux font-medium text-ink" title={it.title}>
                      {it.title}
                    </span>
                    <a
                      href={it.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto shrink-0 text-ink-3 hover:text-primary-deep"
                      aria-label="打开原始来源"
                    >
                      <ArrowUpRight size={14} />
                    </a>
                  </div>
                  <p className="mt-1 line-clamp-2 text-tag text-ink-3">{it.excerpt}</p>
                  <div className="mt-2 flex items-center gap-2 text-tag text-ink-3">
                    <span className="rounded-chip bg-card px-1.5 py-0.5">{it.source_type}</span>
                    <span className="truncate">{it.domain}</span>
                    {it.destination ? (
                      <span className="rounded-chip bg-card px-1.5 py-0.5">{it.destination}</span>
                    ) : (
                      <span className="rounded-chip bg-risk/10 px-1.5 py-0.5 text-risk">无目的地归属</span>
                    )}
                    <span className="ml-auto tabular-nums">可信度 {Math.round(it.credibility)}%</span>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </VCard>

      <VCard hover={false}>
        <div className="flex items-baseline gap-2">
          <h3 className="text-aux font-semibold text-ink">目的地持续追踪</h3>
          <span className="text-tag text-ink-3">订阅后一键复跑取最新动态</span>
        </div>
        <SubscriptionPanel
          resource={subs}
          nodes={nodes}
          onCreated={() => {
            subs.reload()
            ev.reload()
          }}
        />
      </VCard>
    </div>
  )
}

function FilterChip({
  label,
  on,
  tone = 'dest',
  onClick,
}: {
  label: string
  on: boolean
  tone?: 'dest' | 'type'
  onClick: () => void
}) {
  const base = tone === 'type' ? 'bg-card text-ink-2' : 'bg-bg text-ink-2'
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-chip px-2.5 py-1 text-tag transition-colors ${
        on ? 'bg-primary font-medium text-white' : `${base} hover:bg-primary-tint`
      }`}
    >
      {label}
    </button>
  )
}

function SubscriptionPanel({
  resource,
  nodes,
  onCreated,
}: {
  resource: Resource<Subscription[]>
  nodes: DestinationGraphNode[]
  onCreated: () => void
}) {
  const [query, setQuery] = useState('')
  const [destinations, setDestinations] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const list: Subscription[] = resource.data ?? []

  const submit = async () => {
    if (!query.trim()) {
      setError('先写清追踪主题（例如「三亚 亲子 攻略」）。')
      return
    }
    if (destinations.length === 0) {
      setError('不选目的地不会复跑：订阅按目的地增量抓取，空目的地只会建成一条永远不动的记录。')
      return
    }
    setError(null)
    setSaving(true)
    try {
      await createSubscription(query.trim(), destinations)
      setQuery('')
      setDestinations([])
      onCreated()
    } catch (e) {
      setError(`订阅失败：${e instanceof Error ? e.message : String(e)}（没有建成订阅，可重试）`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {resource.failed ? (
        <p className="mt-3 rounded-card border border-risk/50 bg-risk/10 px-3 py-2 text-tag text-ink-2">
          订阅列表取数失败（下面显示的"0 条"不代表你真的没有订阅）。
          <button onClick={resource.reload} className="ml-2 font-medium text-primary-deep underline">
            重试
          </button>
        </p>
      ) : (
        <p className="mt-2 text-tag text-ink-3">
          {resource.loading ? '正在取订阅……' : `已在追踪 ${list.length} 个主题。`}
        </p>
      )}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="如：三亚 亲子 攻略"
        aria-label="追踪主题"
        className="mt-3 h-9 w-full rounded-btn border border-line bg-bg/60 px-3 text-tag text-ink"
      />
      <div className="mt-2 flex max-h-24 flex-wrap gap-1.5 overflow-auto">
        {nodes.slice(0, 12).map((n) => {
          const on = destinations.includes(n.destination)
          return (
            <button
              key={n.destination}
              onClick={() =>
                setDestinations((d) =>
                  on ? d.filter((x) => x !== n.destination) : [...d, n.destination],
                )
              }
              aria-pressed={on}
              className={`rounded-chip px-2 py-0.5 text-tag ${
                on ? 'bg-primary text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
              }`}
            >
              {n.destination}
            </button>
          )
        })}
      </div>
      {error && (
        <p className="mt-2 rounded-card border border-warn/50 bg-warn/10 px-3 py-2 text-tag text-[#8A6420]">
          {error}
        </p>
      )}
      <button
        onClick={submit}
        disabled={saving}
        className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-btn bg-primary text-aux font-medium text-white hover:bg-primary-deep disabled:opacity-50"
      >
        <BellPlus size={15} /> {saving ? '订阅中…' : '订阅追踪'}
      </button>

      <ul className="mt-3 flex flex-col gap-2">
        {list.map((s) => (
          <li key={s.sub_id} className="rounded-card border border-line/70 bg-bg/60 px-3 py-2">
            <span className="flex items-center gap-1.5 text-tag font-medium text-ink">
              <Rss size={12} className="text-primary-deep" /> {s.query}
            </span>
            <span className="mt-1 block truncate text-tag text-ink-3">
              目的地：{s.destinations.length ? s.destinations.join(' / ') : '（空 · 不会复跑）'}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

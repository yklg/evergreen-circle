import type { SentimentResult } from '../types'
import { VChart } from './VChart'
import type { ChartSpec } from '../types'
import { Quote, ExternalLink, MessageSquareText } from 'lucide-react'

const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  xiaohongshu: '小红书',
  bilibili: 'B站',
  weibo: '微博',
  zhihu: '知乎',
}

// 各平台品牌色（用于原声墙的色卡识别）
const PLATFORM_STYLE: Record<string, { dot: string; chip: string }> = {
  douyin: { dot: 'bg-[#161823]', chip: 'bg-[#161823]/8 text-[#161823]' },
  xiaohongshu: { dot: 'bg-[#FF2442]', chip: 'bg-[#FF2442]/8 text-[#FF2442]' },
  bilibili: { dot: 'bg-[#00AEEC]', chip: 'bg-[#00AEEC]/10 text-[#0090c5]' },
  weibo: { dot: 'bg-[#E6162D]', chip: 'bg-[#E6162D]/8 text-[#E6162D]' },
  zhihu: { dot: 'bg-[#0084FF]', chip: 'bg-[#0084FF]/10 text-[#0084FF]' },
}

const SENT_STYLE: Record<string, { label: string; cls: string }> = {
  pos: { label: '正面', cls: 'bg-ok/15 text-ok' },
  neg: { label: '负面', cls: 'bg-risk/15 text-risk' },
  neu: { label: '中性', cls: 'bg-ink-3/10 text-ink-3' },
}

/** 舆情专章：整体情感条 + 平台分布 + 观点阵营。图表由 section.charts 渲染。 */
export function VSentimentPanel({
  sentiment,
  charts,
}: {
  sentiment: SentimentResult
  charts?: ChartSpec[]
}) {
  const { overall, by_platform, by_spot, camps, voices, highlights, sample_size } = sentiment
  const total = overall.pos + overall.neu + overall.neg || 1
  return (
    <div className="flex flex-col gap-5">
      <div className="text-tag text-ink-3">基于 {sample_size} 条全网评论（抖音优先采集）</div>

      {/* 全网金句墙：LLM 摘抄的真实原声短语，可溯源 */}
      {highlights && highlights.length > 0 && (
        <div className="rounded-card bg-gradient-to-br from-sun-soft to-card p-4 border border-sun/40">
          <div className="mb-3 flex items-center gap-2 text-aux font-semibold text-ink">
            <Quote size={15} className="text-warn" />
            全网舆情金句 · 真实用户原声
          </div>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {highlights.map((h, i) => {
              const ps = PLATFORM_STYLE[h.platform] ?? { dot: 'bg-ink-3', chip: 'bg-ink-3/10 text-ink-2' }
              const ss = SENT_STYLE[h.sentiment] ?? SENT_STYLE.neu
              return (
                <a
                  key={i}
                  href={h.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group flex items-start gap-2.5 rounded-card bg-card/80 p-3 border border-line/50 hover:border-primary/50 hover:shadow-card transition-all"
                >
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${ps.dot}`} />
                  <div className="min-w-0">
                    <p className="text-aux font-medium leading-relaxed text-ink">“{h.phrase}”</p>
                    <div className="mt-1.5 flex items-center gap-1.5">
                      <span className={`rounded-chip px-2 py-0.5 text-[11px] font-medium ${ps.chip}`}>
                        {h.platform_label}
                      </span>
                      <span className={`rounded-chip px-2 py-0.5 text-[11px] ${ss.cls}`}>{ss.label}</span>
                      <ExternalLink size={11} className="ml-auto text-ink-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </div>
                </a>
              )
            })}
          </div>
        </div>
      )}

      {/* 整体情感条 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-tag text-ink-2">
          <span>整体情感倾向</span>
          <span>
            正面 {Math.round((overall.pos / total) * 100)}% · 中性{' '}
            {Math.round((overall.neu / total) * 100)}% · 负面{' '}
            {Math.round((overall.neg / total) * 100)}%
          </span>
        </div>
        <div className="flex h-3 w-full overflow-hidden rounded-chip">
          <div className="bg-ok" style={{ width: `${(overall.pos / total) * 100}%` }} />
          <div className="bg-ink-3/40" style={{ width: `${(overall.neu / total) * 100}%` }} />
          <div className="bg-risk" style={{ width: `${(overall.neg / total) * 100}%` }} />
        </div>
      </div>

      {/* 图表 */}
      {charts && charts.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {charts.map((c) => (
            <VChart key={c.chart_id} spec={c} height={240} />
          ))}
        </div>
      )}

      {/* 平台分布 */}
      <div>
        <div className="mb-2 text-aux font-semibold text-ink">各平台口碑分布</div>
        <div className="flex flex-col gap-2">
          {Object.entries(by_platform).map(([plat, v]) => {
            const t = v.pos + v.neu + v.neg || 1
            return (
              <div key={plat} className="flex items-center gap-3">
                <span className="w-14 shrink-0 text-tag text-ink-2">{PLATFORM_LABEL[plat] ?? plat}</span>
                <div className="flex h-2.5 flex-1 overflow-hidden rounded-chip">
                  <div className="bg-ok" style={{ width: `${(v.pos / t) * 100}%` }} />
                  <div className="bg-ink-3/40" style={{ width: `${(v.neu / t) * 100}%` }} />
                  <div className="bg-risk" style={{ width: `${(v.neg / t) * 100}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 逐景点口碑分布（M2c：spot×platform 双维，spot_id 直引冻结实体） */}
      {by_spot && by_spot.length > 0 && (
        <div>
          <div className="mb-2 text-aux font-semibold text-ink">逐景点口碑分布</div>
          <div className="flex flex-col gap-2">
            {by_spot.map((s) => (
              <div key={s.spot_id} data-spot-id={s.spot_id} className="flex items-center gap-3">
                <span className="w-28 shrink-0 truncate text-tag text-ink-2" title={s.spot_name}>
                  {s.spot_name || s.spot_id}
                </span>
                <div className="flex h-2.5 flex-1 overflow-hidden rounded-chip">
                  <div className="bg-ok" style={{ width: `${s.pos}%` }} />
                  <div className="bg-ink-3/40" style={{ width: `${s.neu}%` }} />
                  <div className="bg-risk" style={{ width: `${s.neg}%` }} />
                </div>
                <span className="w-16 shrink-0 text-right text-tag text-ink-3">{s.sample} 条</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 观点阵营 */}
      {camps && camps.length > 0 && (
        <div>
          <div className="mb-2 text-aux font-semibold text-ink">观点阵营</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {camps.map((c, i) => (
              <div key={i} className="rounded-card border border-line/60 bg-bg p-4">
                <div className="flex items-center justify-between">
                  <span className="text-aux font-semibold text-ink">{c.title}</span>
                  <span className="rounded-chip bg-primary-tint px-2.5 h-6 text-tag font-medium text-primary-deep">
                    {Math.round(c.ratio)}%
                  </span>
                </div>
                <p className="mt-1.5 text-tag leading-relaxed text-ink-2">{c.summary}</p>
                {c.quotes?.slice(0, 1).map((q, qi) => (
                  <a
                    key={qi}
                    href={q.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 block rounded-btn bg-card px-3 py-2 text-tag italic text-ink-2 hover:text-primary-deep"
                  >
                    “{q.text}”
                  </a>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 平台原声墙：各平台真实评论，按品牌色卡分区，可溯源 */}
      {voices && voices.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-2 text-aux font-semibold text-ink">
            <MessageSquareText size={15} className="text-primary" />
            平台原声墙 · 逐条可溯源
          </div>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3">
            {voices.map((v, i) => {
              const ps = PLATFORM_STYLE[v.platform] ?? { dot: 'bg-ink-3', chip: 'bg-ink-3/10 text-ink-2' }
              const ss = SENT_STYLE[v.sentiment] ?? SENT_STYLE.neu
              return (
                <a
                  key={i}
                  href={v.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group flex flex-col rounded-card border border-line/60 bg-bg p-3 hover:border-primary/50 hover:shadow-card transition-all"
                >
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <span className={`rounded-chip px-2 py-0.5 text-[11px] font-medium ${ps.chip}`}>
                      {v.platform_label}
                    </span>
                    <span className={`rounded-chip px-2 py-0.5 text-[11px] ${ss.cls}`}>{ss.label}</span>
                    <ExternalLink size={11} className="ml-auto text-ink-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <p className="text-tag leading-relaxed text-ink-2 line-clamp-4">“{v.text}”</p>
                </a>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

import { useCallback } from 'react'
import {
  Activity,
  Clock,
  Database,
  Layers,
  ShieldCheck,
  Sparkles,
  Target,
  Zap,
} from 'lucide-react'
import { VCard, VStatCard } from '../../components/ui'
import { useIntelOverview } from '../../hooks/useIntelOverview'
import { useResource } from '../../hooks/useResource'
import { fetchWorkload } from '../../lib/api'
import { kindLabel } from '../../lib/sourceKindsClient'
import { useDataModeStore } from '../../store/dataModeStore'
import type { IntelOverview } from '../../types'
import type { DomainViewProps } from '../../lib/domainViews'
import { CardTitle } from './CardTitle'
import ExpertContributionBoard from './ExpertContributionBoard'
import EvidenceAndTracking from './EvidenceAndTracking'
import LoadFailure from './LoadFailure'
import ResearchOverviewCards from './ResearchOverviewCards'

/** 信源四类归并：计数出自后端 `platform_distribution`（全库），这里只做展示层归类。
 *
 *  「用户指定」单列成第四类，**不并进「权威一手」**：用户钉的文档可能是政府公报，也可能
 *  是一篇自媒体，并进权威桶会让"一手权威信源占 X%"这句研判被系统性夸大（计划 v3 §二 B6
 *  要求的是口径可见，不是口径美化）。 */
const SOURCE_CATEGORY: Record<string, '权威一手' | '媒体报道' | '社媒口碑' | '用户指定'> = {
  official: '权威一手',
  financial_report: '权威一手',
  news: '媒体报道',
  web: '媒体报道',
  review: '媒体报道',
  douyin: '社媒口碑',
  xiaohongshu: '社媒口碑',
  bilibili: '社媒口碑',
  weibo: '社媒口碑',
  zhihu: '社媒口碑',
  user_supplied: '用户指定',
}
const CATEGORY_CLASS = {
  权威一手: 'bg-primary',
  媒体报道: 'bg-[#4a89c8]',
  社媒口碑: 'bg-[#d9a441]',
  用户指定: 'bg-[#5f7d8c]',
} as const

/**
 * 目的地调研屏（步骤 0 拍定＝八块全做，形态见 `preview-intel-center.html`）。
 *
 * 与旧仪表盘的本质区别：图谱与统计**全部来自 `/api/intel` 的服务端聚合**，
 * 客户端一行聚合都不算 —— 旧形态是在 `limit=200` 的截断样本上现算，
 * 于是"覆盖目的地 20 个"其实是 110 行样本里的 20 个。
 *
 * 演示态（fixture）按 T3 拍定＝甲挂显式说明态并**禁用取数**：不是「暂无调研」空态，
 * 因为那是把模式问题伪装成数据缺失。
 */
export default function ResearchIntelView({ onDelete, refreshToken }: DomainViewProps) {
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')
  const { data, loading, failed, reload } = useIntelOverview(!isFixture, refreshToken)
  const workload = useResource(
    useCallback(() => fetchWorkload(), []),
    !isFixture,
    refreshToken,
  )

  if (isFixture) return <FixtureNotice />
  if (failed) return <LoadFailure detail="目的地调研情报取数失败" onRetry={reload} />
  if (loading || !data) {
    return <div className="mt-16 text-center text-aux text-ink-3">正在汇总调研情报……</div>
  }

  const graph = data.destination_graph
  const nodes = graph.nodes
  const maxCount = nodes.length ? nodes[0].count : 1

  return (
    <div className="mt-6 flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
        <VStatCard
          icon={Target}
          surface="vcard"
          countUp
          value={nodes.length}
          label="覆盖目的地"
          tip={`全库 ${graph.scanned} 行证据里归并出的目的地数`}
        />
        <VStatCard
          icon={Database}
          surface="vcard"
          countUp
          value={data.evidence_total}
          label="情报证据"
          tip={`库内证据行总数（全库口径）· 平均每篇报告 ${data.avg_evidence_per_report} 条`}
        />
        <VStatCard
          icon={Sparkles}
          surface="vcard"
          countUp
          value={data.claim_total}
          label="产出结论"
          tip="全部报告输出的分析结论总数"
        />
        <VStatCard
          icon={ShieldCheck}
          surface="vcard"
          countUp
          color="text-ok"
          value={data.fact_accuracy}
          unit="%"
          label="交叉验证率"
          tip="高置信结论 ÷ 全部结论"
        />
      </div>

      <VCard hover={false}>
        <CardTitle title="业务闭环价值" hint="公式来自各报告 metrics · 数据源 /api/intel" />
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <VStatCard
            icon={Clock}
            surface="flat"
            value={Math.round((data.minutes_saved / 60) * 10) / 10}
            unit="小时"
            label="累计节省人力"
            tip="∑(人工估时 − AI 实际耗时)"
          />
          <VStatCard
            icon={Zap}
            surface="flat"
            color="text-warn"
            value={data.avg_efficiency}
            unit="×"
            label="平均效率提升"
            tip="人工估时 ÷ 实际耗时 的平均倍数"
          />
          <VStatCard
            icon={Layers}
            surface="flat"
            color="text-ok"
            value={data.avg_coverage}
            unit="×"
            label="平均信源覆盖"
            tip="每份报告平均独立信源数"
          />
          <VStatCard
            icon={Activity}
            surface="flat"
            color="text-info"
            countUp
            value={Math.round(data.total_tokens / 1000)}
            unit="K"
            label="累计 Token 算力"
            tip="所有调研真实消耗的 LLM Token 总量（千）"
          />
        </div>
      </VCard>

      <ResearchOverviewCards intel={data} onDelete={onDelete} />

      <VCard hover={false}>
        <CardTitle
          title="目的地情报图谱"
          hint={`全库 ${graph.scanned} 行证据 · ${nodes.length} 个目的地`}
        />
        <div className="mt-2 flex flex-col gap-1">
          {nodes.slice(0, 12).map((n) => (
            <div
              key={n.destination}
              className="grid grid-cols-[150px_1fr_46px_190px] items-center gap-2 text-tag"
            >
              <span className="truncate" title={n.destination}>
                {n.destination}
              </span>
              <span className="block h-2.5 overflow-hidden rounded-full bg-line/60">
                <span
                  className="block h-full rounded-full bg-primary"
                  style={{ width: `${Math.max(4, (n.count / maxCount) * 100)}%` }}
                />
              </span>
              <span className="text-right tabular-nums text-ink-2">{n.count}</span>
              <span className="text-ink-3">
                {n.source_types.length} 类信源 · 平均可信度 {Math.round(n.avg_credibility)}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-tag text-ink-3">
          另有 <b>{graph.unattributed}</b> 行证据没有目的地归属（占 {pct(graph.unattributed, graph.scanned)}%）
          —— 它们不参与图谱，但必须显式报数，不能被"排除空值"这类写法静默抹掉。
        </p>
      </VCard>

      <SourceStructure intel={data} />

      <EvidenceAndTracking
        enabled={!isFixture}
        refreshToken={refreshToken}
        nodes={nodes}
        evidenceTotal={data.evidence_total}
      />

      <ExpertContributionBoard
        workload={workload.data ?? []}
        failed={workload.failed}
        onRetry={workload.reload}
      />
    </div>
  )
}

function SourceStructure({ intel }: { intel: IntelOverview }) {
  const cat: Record<'权威一手' | '媒体报道' | '社媒口碑' | '用户指定', number> = {
    权威一手: 0,
    媒体报道: 0,
    社媒口碑: 0,
    用户指定: 0,
  }
  const unmapped: string[] = []
  for (const [type, n] of Object.entries(intel.platform_distribution)) {
    const c = SOURCE_CATEGORY[type]
    if (!c) unmapped.push(type)
    cat[c ?? '媒体报道'] += n
  }
  const total = Object.values(intel.platform_distribution).reduce((a, b) => a + b, 0) || 1
  const segs = (['权威一手', '媒体报道', '社媒口碑', '用户指定'] as const).map((k) => ({
    label: k,
    n: cat[k],
    pct: Math.round((cat[k] / total) * 100),
  }))
  const firstHand = segs[0].pct
  const top = [...segs].sort((a, b) => b.n - a.n)[0]
  const insight =
    firstHand >= 40
      ? `一手权威信源占 ${firstHand}%，情报根基扎实，结论可信度高。`
      : firstHand >= 20
        ? `当前以「${top.label}」为主（${top.pct}%），一手信源占 ${firstHand}%，建议追加官方文旅站点/平台公告以加固关键结论。`
        : `情报偏向「${top.label}」（${top.pct}%），一手信源仅 ${firstHand}%，重要结论需补充官方文旅站点与平台公告佐证。`

  return (
    <VCard hover={false}>
      <CardTitle title="信源结构与研判" hint={`按全库 ${total} 行证据归类`} />
      <div className="mt-3 flex h-6 overflow-hidden rounded-btn text-tag text-white">
        {segs
          .filter((s) => s.n > 0)
          .map((s) => (
            <span
              key={s.label}
              className={`grid place-items-center whitespace-nowrap ${CATEGORY_CLASS[s.label]}`}
              style={{ width: `${s.pct}%` }}
            >
              {s.label} {s.pct}%
            </span>
          ))}
      </div>
      <p className="mt-2 text-aux text-ink">{insight}</p>
      {/* 口径变动必须可见（计划 v3 §二 B6）：新类别一进库就改变整张饼图（全表实时聚合、
          不重算历史），说明行只在后端确认分布里真含用户指定信源时才出现。 */}
      {intel.distribution_note && (
        <p className="mt-2 rounded-btn bg-bg px-3 py-1.5 text-tag leading-relaxed text-ink-2">
          {intel.distribution_note}
        </p>
      )}
      {unmapped.length > 0 && (
        <p className="mt-2 text-tag text-warn">
          未归类信源：{unmapped.map((k) => kindLabel(k)).join(' / ')}（计入「媒体报道」段，需要补进类别映射时在这里点名，而不是静默归类）
        </p>
      )}
    </VCard>
  )
}

function FixtureNotice() {
  return (
    <div className="mt-6 rounded-card border border-warn/50 bg-warn/10 p-6">
      <h2 className="text-h3 text-ink">演示模式不含实时调研情报</h2>
      <p className="mt-2 text-aux leading-relaxed text-ink-2">
        目的地调研屏的图谱、概览卡与证据流全部来自服务端聚合（<code>/api/intel</code>），
        内置快照里没有这部分数据。本页也不发这个请求 —— 用「暂无调研」空态会把
        "当前是演示模式"伪装成"你还没有调研记录"。
      </p>
      <p className="mt-3 text-aux text-ink-2">
        点左侧栏「数据模式 · 真实联调」即可看到完整八块。
      </p>
    </div>
  )
}

function pct(n: number, total: number): number {
  return total ? Math.round((n / total) * 100) : 0
}

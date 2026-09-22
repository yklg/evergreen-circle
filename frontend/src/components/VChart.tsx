import ReactECharts from 'echarts-for-react'
import type { ComponentType } from 'react'
import type { ChartSpec } from '../types'
import { VWordCloud } from './VWordCloud'

// type → DOM 渲染器注册表（E1）：命中项由前端自绘，其余默认走 ECharts 包装。
const DOM_RENDERERS: Record<string, ComponentType<{ spec: ChartSpec; height?: number }>> = {
  wordcloud: VWordCloud,
}

/** 图表卡片：统一标题/底卡/证据溯源按钮；按 type 分流 DOM 自绘或 ECharts option 渲染。 */
export function VChart({
  spec,
  height = 280,
  onCite,
}: {
  spec: ChartSpec
  height?: number
  onCite?: (ids: string[]) => void
}) {
  const ids = spec.evidence_ids ?? []
  const DomRenderer = DOM_RENDERERS[spec.type]
  return (
    <div className="rounded-card border border-line/60 bg-card p-4 shadow-card">
      {spec.title && (
        <div className="mb-2 text-aux font-semibold text-ink">{spec.title}</div>
      )}
      {DomRenderer ? (
        <DomRenderer spec={spec} height={height} />
      ) : (
        <ReactECharts
          option={spec.option ?? {}}
          style={{ height, width: '100%' }}
          opts={{ renderer: 'svg' }}
          notMerge
        />
      )}
      {ids.length > 0 && (
        <button
          onClick={() => onCite?.(ids)}
          className="mt-2 inline-flex items-center gap-1 text-tag text-primary-deep hover:underline"
          title="跳转到支撑该图表的证据"
        >
          数据来源：{ids.length} 条证据 →
        </button>
      )}
    </div>
  )
}

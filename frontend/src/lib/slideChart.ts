import type { ChartSpec, Report } from '../types'

/**
 * 幻灯片取图：按类型择优，**不按数组下标**。
 *
 * 旧写法是「第一个含图的章的 charts[0]」——而低样本口碑时情感环图与声量柱整体缺位，
 * 舆情章的 charts[0] 于是从环图变成词云：样本量一变，幻灯片内容就静默换图。
 * 词云在 200px 高的幻灯片里还常常排不下（螺旋兜底会溢出），本就不该上幻灯片。
 *
 * 单独成文而非放在 SlidesPage 里：组件文件导出函数会让 React Fast Refresh 失效
 * （eslint `react-refresh/only-export-components`），而这条判据需要被测试直接引用。
 */
const SLIDE_CHART_LAST_RESORT = 'wordcloud'

export function pickSlideChart(r: Report): ChartSpec | null {
  const all = r.sections.flatMap((s) => s.charts ?? [])
  return all.find((c) => c.type !== SLIDE_CHART_LAST_RESORT) ?? all[0] ?? null
}

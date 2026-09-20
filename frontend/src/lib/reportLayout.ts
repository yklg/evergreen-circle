/**
 * 报告页「左侧目录链接」样式的唯一来源（UI 约定隔离）。
 *
 * research（ReportPage）与生活圈（LifeCircleReportView）的左竖排章节目录共同消费，
 * 防止两份目录的字号/对齐/hover 各自漂移。字符串必须与 ReportPage 的既有 button
 * 样式保持字节级一致 —— 任何改动都会同时改变两个页面。
 *
 * @param active 当前章节是否为激活项
 */
export function tocLinkCls(active: boolean): string {
  return `flex w-full items-start gap-2.5 rounded-btn px-3 py-2 text-left text-aux transition-colors ${
    active ? 'bg-primary-tint font-medium text-primary-deep' : 'text-ink-2 hover:bg-primary-tint/50'
  }`
}
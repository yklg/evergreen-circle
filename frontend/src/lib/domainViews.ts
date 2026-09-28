import type { ComponentType } from 'react'
import LivingCircleView from '../pages/reports/LivingCircleView'
import ResearchIntelView from '../pages/reports/ResearchIntelView'
import { deleteLifeCircleReport, deleteReport } from './api'
import type { RecordDomain, ReportRecord } from './recordIndex'

export interface DomainViewProps {
  /** 删除请求交给外壳的统一确认框（两屏共用一份确认与错误处理） */
  onDelete: (record: ReportRecord) => void
  /** 删除成功后自增：让这一屏重取，而不是在本地伪造"已移除"的状态 */
  refreshToken: number
}

export interface DomainViewSpec {
  /** 这一域的屏长什么样：列表折叠 / 情报仪表盘，外壳不知道也不需要知道 */
  View: ComponentType<DomainViewProps>
  /** 删除走哪条端点。派生表清单按域不同，所以差异登记在这里，而不是散进外壳的 if/switch */
  remove: (id: string) => Promise<unknown>
  /** 删除确认文案：会连带清掉什么，只有这一域自己说得准 */
  deleteWarning: (record: ReportRecord) => string
}

/**
 * 域 → 视图形态的登记表，报告中心唯一允许出现"按域分叉"的地方。
 *
 * 为什么需要它：这页原先是"两域混排一条列表 + 客户端过滤"，于是域之间的差异
 * 只能是数据差异。目的地 tab 变成仪表盘之后，差异升成了一等概念 —— 没有这张表，
 * 分叉就会长回外壳的 if/switch 里。
 *
 * 类型是 `Record<RecordDomain, ...>`：新注册一个域族而没在这里登记视图，编译期就红，
 * 不靠运行时兜底。
 */
export const DOMAIN_VIEWS: Record<RecordDomain, DomainViewSpec> = {
  living_circle: {
    View: LivingCircleView,
    remove: deleteLifeCircleReport,
    deleteWarning: (r) =>
      `确定要删除《${r.title}》吗？该操作不可撤销，重新体检会再次消耗百度配额。`,
  },
  travel: {
    View: ResearchIntelView,
    remove: deleteReport,
    deleteWarning: (r) =>
      `确定要删除《${r.title}》吗？该操作不可撤销，关联的 ${r.evidence_count ?? 0} 条证据、决策链路与反馈也将一并清除。`,
  },
}

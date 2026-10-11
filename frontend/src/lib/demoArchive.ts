/**
 * 归档介质按数据模式解析的**唯一一处**。
 *
 * 为什么要有这一层：`lib/domainViews.ts` 是报告中心唯一允许"按域分叉"的登记处，
 * 而"演示态 / 真实态"是另一根轴（介质不同，不是域不同）。两根轴混在一个函数里，
 * 报告中心外壳就会长出 `if (isFixture) … if (domain === …)` 的分支 —— 那正是
 * `domainEnumSingleSource.test.ts` 在防的形状。所以：
 *   - 外壳与各域登记表都不判模式；
 *   - 模式只在下面这两个出口处判一次。
 *
 * 依赖方向：`domainViews → demoArchive →（api | demoArchiveStore）`。
 * `lib/api.ts` 不 import 本模块（否则会成 `api → demoArchive → api` 的环）。
 */
import type { RecordDomain, ReportRecord } from './recordIndex'
import { isFixtureMode } from '../store/dataModeStore'
import { demoTombstones, useDemoArchiveStore } from '../store/demoArchiveStore'

/**
 * 删除结局的三态契约。
 *
 * `removed` 只说"这台机器/这个库上它没了"；**没删掉必须带 `whyNot`**，
 * 让 UI 能说清成因而不是把失败渲染成成功。后端早就算好了 `deleted`
 * （`api.ts` 的注释写着「UI 靠它区分两种可观察结果」），此前在前端零消费者。
 */
export interface DeleteOutcome {
  removed: boolean
  whyNot?: string
}

/** 演示态：摘掉本机那一行。派生列表随即少一行，刷新也不会回来（tombstone 在 localStorage）。 */
function removeFromDemoArchive(record: ReportRecord): DeleteOutcome {
  const removed = useDemoArchiveStore.getState().drop(record)
  return removed
    ? { removed: true }
    : { removed: false, whyNot: '这台机器已经摘掉过这一份演示归档（不是没删成功，是重复操作）' }
}

/**
 * 报告中心登记表共用的删除出口。
 *
 * 分工要说清：**按域选哪条端点**留在 `domainViews` 的登记表里（那里是唯一允许按域分叉的地方，
 * `domainEnumSingleSource.test.ts` 盯着），本函数只判**按介质**这一根轴 —— 所以它不读
 * `record.domain`，真实态怎么删由调用方作为 `removeLive` 交进来。
 */
export const deleteArchiveRecord = (
  record: ReportRecord,
  removeLive: (id: string) => Promise<DeleteOutcome>,
): Promise<DeleteOutcome> | DeleteOutcome => (isFixtureMode() ? removeFromDemoArchive(record) : removeLive(record.id))

/**
 * 演示态列表的减法。真实态一行都不动（后端删了就是没了）。
 *
 * 订阅 `useDemoArchiveStore` 让已挂载的屏在摘除后立刻重取 —— 派生函数是纯的，
 * 不订阅就会停在"删了但界面不动"的老症状上。
 */
export function applyDemoTombstones<T extends { id: string }>(rows: T[], domain: RecordDomain): T[] {
  const table = demoTombstones(domain)
  if (!Object.keys(table).length) return rows
  return rows.filter((r) => !table[r.id])
}

/**
 * 删除确认文案：模式在这里判一次（与 `deleteArchiveRecord` 同一处），各域只交自己的真实态措辞。
 *
 * 演示行说「不可撤销 / 重新体检会再次消耗百度配额」是假话：它既没花配额，也能一键还原。
 */
export function archiveDeleteWarning(record: ReportRecord, liveWarning: string): string {
  if (!isFixtureMode()) return liveWarning
  return (
    `确定要把《${record.title}》从演示归档里摘掉吗？` +
    '只在这台机器上隐藏，随时可在本页下方一键还原；' +
    '演示行不调百度接口，不消耗体检配额。'
  )
}

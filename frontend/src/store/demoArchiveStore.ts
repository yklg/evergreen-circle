/**
 * 演示态归档的本机所有者：记录"哪些演示行被这台机器摘掉了"。
 *
 * 为什么需要它（实测出来的缺口）：演示态的报告行不是库里的真行，而是每次取数重新派生的
 * （`mocks/livingCircleReports.ts::getLifeCircleRecords` 是纯函数，`livingCircleMock.ts`
 * 头部写明「fixture 只读不写」）。删除请求打到真实端点后，后端对这种合成 id 返回
 * `deleted:false`，旧代码又不看返回值、直接重取 ⇒ 那一行必然长回来。
 * "演示归档状态"这个概念原先在系统里没有任何归属处，所以补在这里，而不是散进 `lib/api.ts`。
 *
 * 它**只拥有摘除记录，不拥有列表**：列表仍是派生函数，读本文件做减法（`applyDemoTombstones`）。
 * 因此派生列表的行数、顺序、可达性等既有判据都不必跟着改。
 *
 * 持久化刻意**不接 `lib/persist.ts`**：那层会上推 `/api/prefs` 并参与全局水合，
 * 会形成 `api → demoArchive → persist → api` 的环。同一条理由见 `store/dataModeStore.ts` 头部。
 */
import { create } from 'zustand'
import type { RecordDomain, ReportRecord } from '../lib/recordIndex'
import { LS_KEYS } from '../lib/lsKeys'

const LS_KEY = LS_KEYS.demoArchive
const SCHEMA = 'evergreen.demo-archive/v1'

/** 存可点名的字段而不是只存 id：还原条要说清"还原的是哪几份"，而派生列表是顺序敏感的。 */
export interface DemoTombstone {
  id: string
  title: string
  checked_at: string
  removed_at: string
}

export interface DemoArchiveDoc {
  schema: string
  removed: Partial<Record<RecordDomain, Record<string, DemoTombstone>>>
}

const EMPTY: DemoArchiveDoc = { schema: SCHEMA, removed: {} }

function load(): DemoArchiveDoc {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw) as Partial<DemoArchiveDoc>
    // 只认这套 schema：别的版本/脏数据一律当空，不静默带着旧形状往下跑
    if (parsed?.schema !== SCHEMA || typeof parsed.removed !== 'object' || parsed.removed === null) {
      return EMPTY
    }
    return { schema: SCHEMA, removed: parsed.removed as DemoArchiveDoc['removed'] }
  } catch {
    return EMPTY // 隐私模式 / JSON 损坏：回退空归档，绝不抛错
  }
}

function save(doc: DemoArchiveDoc): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(doc))
  } catch {
    /* 无存储能力时仅本次会话生效（与 dataModeStore 同一取舍） */
  }
}

/** 取某域的本机摘除表（纯读，不进 state —— 派生列表用它做减法）。 */
export function demoTombstones(domain: RecordDomain): Record<string, DemoTombstone> {
  return useDemoArchiveStore.getState().doc.removed[domain] ?? {}
}

export function countDemoTombstones(domain: RecordDomain): number {
  return Object.keys(demoTombstones(domain)).length
}

interface DemoArchiveState {
  doc: DemoArchiveDoc
  /** 摘掉一行。返回 false = 这台机器上它本来就被摘过（与后端 `deleted:false` 同形，让 UI 能区分） */
  drop: (record: ReportRecord) => boolean
  /** 一键还原：清掉该域全部 tombstone */
  restoreAll: (domain: RecordDomain) => number
  /** 只还原点名的一行 */
  restoreOne: (domain: RecordDomain, id: string) => boolean
}

export const useDemoArchiveStore = create<DemoArchiveState>((set, get) => ({
  doc: load(),

  drop: (record) => {
    const { domain, id } = record
    if (demoTombstones(domain)[id]) return false
    const removed = {
      ...get().doc.removed,
      [domain]: {
        ...(get().doc.removed[domain] ?? {}),
        [id]: {
          id,
          title: record.title,
          checked_at: record.checked_at,
          removed_at: new Date().toISOString(),
        },
      },
    }
    const doc = { schema: SCHEMA, removed }
    save(doc)
    set({ doc })
    return true
  },

  restoreAll: (domain) => {
    const n = countDemoTombstones(domain)
    if (!n) return 0
    const removed = { ...get().doc.removed }
    delete removed[domain]
    const doc = { schema: SCHEMA, removed }
    save(doc)
    set({ doc })
    return n
  },

  restoreOne: (domain, id) => {
    const table = { ...demoTombstones(domain) }
    if (!table[id]) return false
    delete table[id]
    const doc = { schema: SCHEMA, removed: { ...get().doc.removed, [domain]: table } }
    save(doc)
    set({ doc })
    return true
  },
}))

/**
 * 把本机归档清回空盘（内存 + localStorage 两处一起）。
 *
 * 必须两处一起清：store 是模块级单例，只清 localStorage 的话，同一测试文件里
 * 上一个用例摘掉的行会渗进下一个用例（第一红红在脚手架而不是红在产品逻辑）。
 */
export function resetDemoArchive(): void {
  useDemoArchiveStore.setState({ doc: EMPTY })
  try {
    localStorage.removeItem(LS_KEY)
  } catch {
    /* 无存储能力：内存已清即可 */
  }
}

/** 订阅版本号：tombstone 变化要让已挂载的列表重取（store 自身不碰取数，避免和屏互相拉） */
export function subscribeDemoArchive(cb: () => void): () => void {
  return useDemoArchiveStore.subscribe(cb)
}

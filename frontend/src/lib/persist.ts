/**
 * 统一持久化适配层 —— **用户态数据的唯一持久化属主**。
 *
 * ## 为什么存在（根因）
 * 修复前：每个 store 各自手写一份 `load()` / `save()`，把 localStorage 当作
 * **唯一真相源**。而 localStorage 按 origin 隔离、可被浏览器/宿主随时清空、
 * 不跨设备 —— 于是出现「重启就重置」（见《用户设置持久化架构修复计划》K1/K2/K4）。
 *
 * 修复后：**localStorage 降级为秒开缓存，服务端 `/api/prefs` 是真相源**。
 * 同一份偏好可在任意 origin / 任意浏览器 / 任意设备取回。
 *
 * ## 读写时序
 *
 * 读（启动 `hydrateAllPrefs()`）：
 *   ① 同步读 localStorage → 由 store 以 `initial` 立即填充（无闪屏、离线可用）
 *   ② 异步 `GET /api/prefs`，**逐字段**判定：
 *        · 该字段本地有未成功推送的改动（pending）→ 本地为准，并重推
 *        · 远端存过该字段                        → 远端为准，落回本地缓存
 *        · 远端没有该字段（新库 / 新增字段）      → 本地为准，并上推
 *          （= 存量本地资料自动迁移到服务端，不丢）
 *
 * 写（`persist(state)`）：
 *   ① 同步写 localStorage（即时落盘，防关页 / 崩溃丢失）
 *   ② 标记 pending → debounce PUT（合并高频写入）
 *   ③ PUT 成功且「已发送值 == pending 里记录的值」才清 pending
 *
 * ## 为什么 pending 标记是必要的（关键正确性设计，别删）
 * 若无 pending：改完昵称 → PUT 尚未送达 → 下次启动「远端为准」会把**旧昵称盖回**，
 * 用户看到的就是"改了又自己变回去"。有 pending 后，未送达的改动永远是本地为准
 * 并自动重推，且**不依赖 unload 时的网络**（不靠 sendBeacon 兜底）。
 *
 * ## 冲突策略
 * 单用户场景采用「远端为准，除非本地有未成功推送的改动」。跨设备同时编辑为
 * 后写覆盖（last-write-wins），不做合并 —— 见修复计划 §8 边界说明。
 */
import { fetchPrefs, savePrefs, getPrefsApiCapability, PrefsUnsupportedError } from './api'
import type { PrefValue } from '../types'

/** 可持久化的值类型：原子值 + **受控的字符串数组**（后端有真类型的清单键，如 `intel.defaultSources`）。
 *
 *  数组这一支不是"把对象塞进偏好层"：后端 `user_prefs.PREF_SCHEMA` 对 `list[str]` 键
 *  有条数与单条长度双重校验（计划 v3 §二 B7），它和标量键一样是**参与业务计算的结构化数据**。
 *  仍然禁止的是无 schema 的任意对象/blob —— 那类数据属于业务表，不属于偏好。 */
export type PrefShape = Record<string, PrefValue>

export interface PersistSpec<L extends PrefShape> {
  /** localStorage 键。沿用历史键名，避免老用户本地资料失联。 */
  localKey: string
  /** 本地字段名 → 服务端 pref key（命名空间化，如 `profile.name`）。单一真相源。 */
  prefs: Partial<Record<keyof L & string, string>>
  /** 本地默认值（同时用于远端值的类型归一） */
  defaults: L
  /** 可选语义规整：在「本地读」与「远端水合」两处统一生效，保证两条来源口径一致 */
  normalize?: (v: L) => L
}

export interface Persister<L extends PrefShape> {
  readonly localKey: string
  readonly defaults: L
  /** 同步读本地（首屏用）。损坏 / 缺字段一律回退默认，绝不抛错。 */
  readLocal(): L
  /** 写：本地即时 + 服务端 debounce 上推。可直接传整个 store state（内部按白名单裁剪）。 */
  persist(state: object): void
  /** 注册远端回填回调；`hydrateAllPrefs()` 时执行。 */
  register(onRemote: (remote: Partial<L>) => void): void
}

/* ── localStorage 容错读写 ─────────────────────────────── */

/** 读原始 JSON；损坏 / 隐私模式 / 配额异常一律回退 undefined。 */
function readRaw(localKey: string): unknown {
  try {
    const raw = localStorage.getItem(localKey)
    return raw ? JSON.parse(raw) : undefined
  } catch {
    return undefined
  }
}

/** 写原始 JSON；忽略配额 / 隐私模式异常（写失败不应让业务动作失败）。 */
function writeRaw(localKey: string, value: unknown): void {
  try {
    localStorage.setItem(localKey, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

/* ── pending 账本（未成功推送到服务端的字段）──────────── */

const PENDING_KEY = 'verda.prefs.pending.v1'

function readPending(): Record<string, PrefValue> {
  const v = readRaw(PENDING_KEY)
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, PrefValue>) : {}
}

function markPending(patch: Record<string, PrefValue>): void {
  if (!Object.keys(patch).length) return
  writeRaw(PENDING_KEY, { ...readPending(), ...patch })
}

/**
 * 仅清除「pending 里记录的值 == 本次实际发送的值」的键。
 *
 * 竞态场景：t=0 改 A → t=400 发送 A（在途）→ t=450 改 B（pending=A→B）→
 * t=500 发送 A 成功回包。若直接清空 pending 会把 B 的标记也清掉，
 * 于是 B 在下次启动时被远端旧值覆盖 —— 这正是本函数要防的。
 */
function clearPendingIfUnchanged(sent: Record<string, PrefValue>): void {
  const cur = readPending()
  let changed = false
  for (const [k, v] of Object.entries(sent)) {
    if (k in cur && sameValue(cur[k], v)) {
      delete cur[k]
      changed = true
    }
  }
  if (changed) writeRaw(PENDING_KEY, cur)
}

export function clearAllPending(): void {
  writeRaw(PENDING_KEY, {})
}

/* ── 类型归一 ─────────────────────────────────────────── */

/** 值比较：数组按**逐项**相等判，其余用 `===`。
 *
 *  pending 账本与「水合后是否变化」两处原本都是 `===`。对数组而言引用相等恒不成立，
 *  后果是：① `clearPendingIfUnchanged` 永远清不掉标记 ⇒ 该键每次启动都被判为"本地有未
 *  送达的改动"、永远本地为准 ⇒ 服务端真相源在这一个键上失效；② 每次水合都触发一次
 *  `onRemote` 回调（无谓重渲染）。这两条都不是理论问题，是数组上真会发生的失效。 */
export function sameValue(a: PrefValue | undefined, b: PrefValue | undefined): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => x === b[i])
  }
  if (Array.isArray(a) || Array.isArray(b)) return false
  return a === b
}

/**
 * 按默认值的类型归一化外来值（远端 JSON / 本地脏数据）。
 * 无法归一 → 返回 undefined（调用方回退默认值）。
 *
 * bool 特意不走 `Boolean(v)`：`Boolean("false") === true` 是经典陷阱。
 */
export function coerceLike(defaultValue: PrefValue | undefined, raw: unknown): PrefValue | undefined {
  if (raw === undefined || raw === null) return undefined
  if (Array.isArray(defaultValue)) {
    // 清单键：只收字符串数组，逐项 trim 后丢空/去重（与后端 normalize 同口径，
    // 避免"本地存了空串/重复项、远端没有"这种两边形状不一致的漂移）。
    if (!Array.isArray(raw)) return undefined
    const out: string[] = []
    for (const item of raw) {
      if (typeof item !== 'string') return undefined
      const v = item.trim()
      if (v && !out.includes(v)) out.push(v)
    }
    return out
  }
  if (typeof defaultValue === 'boolean') {
    if (typeof raw === 'boolean') return raw
    const s = String(raw).trim().toLowerCase()
    if (['1', 'true', 'yes', 'on'].includes(s)) return true
    if (['0', 'false', 'no', 'off'].includes(s)) return false
    return undefined
  }
  if (typeof defaultValue === 'number') {
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : undefined
    const n = Number(raw)
    return Number.isFinite(n) ? n : undefined
  }
  if (typeof defaultValue === 'string') return typeof raw === 'string' ? raw : String(raw)
  return undefined
}

/* ── 白名单裁剪 ───────────────────────────────────────── */

/**
 * 从任意对象（如 store 的整个 state，含动作函数）里只取本 spec 声明的字段。
 *
 * 形参用 `object` 而非 `Record<string, unknown>`：Store 的 state 多由 `interface`
 * 定义，而 **interface 没有隐式索引签名**，无法赋给 `Record`（type alias 可以）。
 * 用 `object` 接收再内部收窄，调用方无需为类型系统让路。
 */
function pick<L extends PrefShape>(spec: PersistSpec<L>, source: object): L {
  const rec = source as Record<string, unknown>
  const out = { ...spec.defaults } as Record<string, PrefValue>
  for (const field of Object.keys(spec.prefs)) {
    const coerced = coerceLike(spec.defaults[field], rec[field])
    if (coerced !== undefined) out[field] = coerced
  }
  return out as unknown as L
}

/** 本 spec 的「本地字段 → 服务端 pref key」条目（单一映射点，避免两处命名漂移）。 */
function prefEntries<L extends PrefShape>(spec: PersistSpec<L>): [keyof L & string, string][] {
  return Object.entries(spec.prefs) as unknown as [keyof L & string, string][]
}

/** 本地形状 → 服务端 pref patch（键名映射的唯一点）。 */
function toPrefPatch<L extends PrefShape>(spec: PersistSpec<L>, value: L): Record<string, PrefValue> {
  const patch: Record<string, PrefValue> = {}
  const src = value as unknown as Record<string, PrefValue>
  for (const [field, prefKey] of prefEntries(spec)) {
    const v = src[field]
    if (v !== undefined) patch[prefKey] = v
  }
  return patch
}

/* ── 上推（debounce + 逐键合并）──────────────────────────── */

/** 合并窗口：把连续 mutation 合成一次 PUT，避免"改一次发一次"。 */
const DEBOUNCE_MS = 400

interface Outbox {
  timer: ReturnType<typeof setTimeout> | null
  /** 待发送的最新快照（后写覆盖先写——远端最终拿到的是最后状态） */
  latest: Record<string, PrefValue> | null
}
const outboxes = new Map<string, Outbox>()

function schedulePush<L extends PrefShape>(spec: PersistSpec<L>, snapshot: L): void {
  const patch = toPrefPatch(spec, snapshot)
  if (!Object.keys(patch).length) return
  // 该部署没有 /api/prefs（如 Vercel 只读裁剪镜像）→ 已是纯本地模式，
  // 不必发注定 404 的请求，也不必逐次告警。
  if (getPrefsApiCapability() === 'unsupported') return

  let box = outboxes.get(spec.localKey)
  if (!box) {
    box = { timer: null, latest: null }
    outboxes.set(spec.localKey, box)
  }
  // 收窄成 const，避免闭包里持有可空引用（也免掉非空断言）
  const target = box
  target.latest = patch
  if (target.timer) clearTimeout(target.timer)
  target.timer = setTimeout(() => {
    target.timer = null
    const toSend = target.latest
    target.latest = null
    if (toSend) void flush(spec, toSend)
  }, DEBOUNCE_MS)
}

async function flush<L extends PrefShape>(
  spec: PersistSpec<L>,
  patch: Record<string, PrefValue>,
): Promise<void> {
  try {
    await savePrefs(patch)
    clearPendingIfUnchanged(patch)
  } catch (e) {
    // 该部署没有 /api/prefs → 常态降级，不算故障，静默返回
    // （能力已被 api 层latch 成 unsupported，后续 schedulePush 会直接跳过）。
    if (e instanceof PrefsUnsupportedError) return
    // 其余为真实故障。刻意「不吞异常、不静默忽略、不加自动 retry 遮盖失败」：
    // 保留 pending（下次启动 hydrate 会以本地为准并自动重推），并明确告警。
    console.warn(
      `[persist] ${spec.localKey} 偏好上推失败，已保留本地值并在下次启动自动重推：`,
      e,
    )
  }
}

/* ── 装配 ─────────────────────────────────────────────── */

export function createPersister<L extends PrefShape>(spec: PersistSpec<L>): Persister<L> {
  const applyNormalize = (v: L): L => (spec.normalize ? spec.normalize(v) : v)

  const persister: Persister<L> = {
    localKey: spec.localKey,
    defaults: spec.defaults,

    readLocal(): L {
      const source = readRaw(spec.localKey)
      const base: object = source && typeof source === 'object' && !Array.isArray(source)
        ? (source as object)
        : {}
      return applyNormalize(pick(spec, base))
    },

    persist(state: object): void {
      const snapshot = applyNormalize(pick(spec, state))
      // ① 本地即时落盘（不依赖网络）
      writeRaw(spec.localKey, snapshot)
      // ② 记账 + debounce 上推（远端成为真相源）
      const patch = toPrefPatch(spec, snapshot)
      markPending(patch)
      schedulePush(spec, snapshot)
    },

    register(onRemote: (remote: Partial<L>) => void): void {
      registry.push(() => hydrateOne(spec, persister, onRemote))
    },
  }

  async function hydrateOne(
    s: PersistSpec<L>,
    p: Persister<L>,
    onRemote: (remote: Partial<L>) => void,
  ): Promise<void> {
    const remote = await fetchPrefs()
    if (!remote) return // 后端不可用 → 保留本地值（绝不清空用户资料）

    const remoteValues = remote.values ?? {}
    const pending = readPending()
    const local = p.readLocal()
    const localRec = local as unknown as Record<string, PrefValue>

    const resolved: Record<string, PrefValue> = { ...localRec }
    const toPush: Record<string, PrefValue> = {}

    for (const [field, prefKey] of prefEntries(s)) {
      const hasRemote = Object.prototype.hasOwnProperty.call(remoteValues, prefKey)
      const isPending = prefKey in pending

      if (isPending) {
        // 本地有未送达的改动 → 本地为准，重推
        toPush[prefKey] = resolved[field]
      } else if (hasRemote) {
        // 远端为准；类型归一转回本地类型
        const coerced = coerceLike(s.defaults[field], remoteValues[prefKey])
        resolved[field] = coerced !== undefined ? coerced : s.defaults[field]
      } else {
        // 远端没有这一项 → 上推本地（存量资料自动迁移）
        toPush[prefKey] = resolved[field]
      }
    }

    const normalized = applyNormalize(resolved as unknown as L) as unknown as Record<string, PrefValue>
    // 落回本地缓存，保证下次「秒开」看到的就是最新真相
    writeRaw(s.localKey, pick(s, normalized))

    // 仅回调真正变化的字段，避免无谓的整树重渲染
    const changed: Record<string, PrefValue> = {}
    for (const field of Object.keys(s.prefs)) {
      if (!sameValue(normalized[field], localRec[field])) {
        changed[field] = normalized[field]
      }
    }
    if (Object.keys(changed).length) onRemote(changed as unknown as Partial<L>)

    if (Object.keys(toPush).length) {
      markPending(toPush)
      await flush(s, toPush)
    }
  }

  return persister
}

/* ── 全局水合编排 ─────────────────────────────────────── */

/** 已注册的 persister 水合任务（由各自 store 模块 `register()` 时登记）。 */
const registry: Array<() => Promise<void>> = []

/**
 * 启动期水合所有已注册的 persister（由 `App.tsx` 的 useEffect 调用一次）。
 *
 * 用注册表而非在 App 里逐个显式调用：新增 store 只需在自身模块 `register()`，
 * 无需改动 App —— 这正是「持久化能力单一属主」的收益。
 */
export async function hydrateAllPrefs(): Promise<void> {
  await Promise.allSettled(registry.map((run) => run()))
}

/**
 * 坐标契约（BD-09 经纬度）—— **前端唯一的值域校验实现**。
 *
 * ## 为什么需要它
 *
 * `LngLat = [number, number]` 在类型系统里**无法区分**三种东西：
 *   1. BD-09 经纬度（本域唯一的合法输入）；
 *   2. 百度墨卡托平面米（BMapGL 事件里的 `point` / `pixel`，量级 1e6~1e7）；
 *   3. WGS-84 经纬度（`navigator.geolocation` 返回，与 BD-09 相差约 600m）。
 *
 * TypeScript 拦不住任何一种——喂错坐标系是「类型正确」的。故契约只能落在**值域**上：
 * `|lng| <= 180` 且 `|lat| <= 90`。
 *
 * 历史事故（已 CDP 复现）：`LcMap` 的 `dragend` 读 `e.point`（墨卡托米
 * `(11440230.81, 2860409.52)`）当经纬度 → 中心被打到 `(150.81, 84.60)`（北极圈）
 * → 无瓦片 → 画布退化为纯色；该值还会经 API 落库，**之后每次打开都必现**。
 *
 * 后端同契约实现：`backend/app/living_circle/geo_utils.py::parse_bd_lnglat`
 * （值域常量与拒绝规则逐条对齐，改一处必须改两处）。
 */
import type { LngLat } from '../types'

/** BD-09 经纬度的合法值域（与后端 `BD_LNG_ABS_MAX` / `BD_LAT_ABS_MAX` 同源） */
export const BD_LNG_ABS_MAX = 180
export const BD_LAT_ABS_MAX = 90

/** 坐标系标签：BD-09 可直接使用；WGS-84 必须先转换（否则中心偏约 600m） */
export type CoordSys = 'bd09' | 'wgs84'

/**
 * 纯值域解析：合法返回 `LngLat`，非法返回 `null`（不抛、不打印）。
 *
 * 拒绝规则（四条同时满足才算合法）：
 *  1) 是长度恰为 2 的数组；
 *  2) 两项均为 number（`Array.isArray` 已排除 string/Map 等，此处再排除 NaN/Infinity）；
 *  3) 两项均有限（拒绝 NaN / ±Infinity）；
 *  4) `|lng| <= 180` 且 `|lat| <= 90`。
 */
export function parseBdLngLat(raw: unknown): LngLat | null {
  if (!Array.isArray(raw) || raw.length !== 2) return null
  const [lng, lat] = raw
  if (typeof lng !== 'number' || typeof lat !== 'number') return null
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null
  if (Math.abs(lng) > BD_LNG_ABS_MAX || Math.abs(lat) > BD_LAT_ABS_MAX) return null
  return [lng, lat]
}

/** 值域谓词（给需要「只问不取」的地方用，避免重复写四条规则）。 */
export function isBdLngLat(raw: unknown): raw is LngLat {
  return parseBdLngLat(raw) !== null
}

/** 统一的拒绝告警出口（保证「非法值」与「不可信来源」两种消息格式一致） */
function warnReject(where: string, what: string): void {
  // eslint-disable-next-line no-console
  console.warn(`[geo] ${where} ${what}`)
}

/**
 * **形状归一**：把 BMapGL 各种坐标形状统一成一个「可诊断的二元组」。
 *
 * BMapGL 的坐标至少有三种形状，散落到各调用点分别判断必然漏：
 *   - 数组 `[lng, lat]`（本项目内部唯一约定）
 *   - `{ lng, lat }`（BD-09 经纬度对象；**也可能是百度墨卡托米对象**）
 *   - `{ x, y }`（屏幕像素 Pixel）
 *
 * ⚠️ 本函数**只做形状归一、不做合法性判断**——`{x,y}` 归一后仍是像素值。
 * 因此它只用于「喂给 `describeCoordSys` 做诊断」；要**采纳**必须再走 `parseBdLngLat`。
 */
export function toDiagPair(raw: unknown): unknown {
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>
    if ('lng' in o || 'lat' in o) return [o.lng, o.lat]
    if ('x' in o || 'y' in o) return [o.x, o.y]
  }
  return raw
}

/** 诊断：这个值**看起来像**什么坐标系（用于报错与告警的可操作性）。 */
export function describeCoordSys(raw: unknown): string {
  if (!Array.isArray(raw) || raw.length !== 2) return '不是二元组'
  const [a, b] = raw as unknown[]
  if (typeof a !== 'number' || typeof b !== 'number') return '分量不是数字'
  if (!Number.isFinite(a) || !Number.isFinite(b)) return '含 NaN / Infinity'
  if (Math.abs(a) > BD_LNG_ABS_MAX || Math.abs(b) > BD_LAT_ABS_MAX) {
    // 墨卡托米在量级上与经纬度差 5 个数量级，据此给出可操作提示
    if (Math.abs(a) > 1e5 || Math.abs(b) > 1e5) {
      return '量级像「百度墨卡托平面米」（BMapGL 的 e.point / pixel）——请改用 e.latLng 或 marker.getPosition()'
    }
    return '超出 BD-09 值域（|lng|<=180, |lat|<=90）'
  }
  return '未知'
}

/**
 * 严格取用：非法即抛错。
 *
 * 用于**写入口**（提交体检任务）——宁可当场失败，也不要把错坐标系写进库
 * （写进去就是「一次写库、永久复现」的自我强化闭环）。
 *
 * @param where 生产者标识（写进报错信息，便于一眼定位是哪条链路漏了转换）
 */
export function asBdLngLat(raw: unknown, where: string): LngLat {
  const ok = parseBdLngLat(raw)
  if (ok) return ok
  const detail = `收到 ${JSON.stringify(raw)} —— ${describeCoordSys(raw)}`
  warnReject(where, `产出非法 BD-09 坐标：${detail}`)
  throw new Error(`${where} 产出的坐标不是合法 BD-09 经纬度：${detail}`)
}

/**
 * 宽松取用：非法返回 `null`（内部 `console.warn`，不抛）。
 *
 * 用于**交互回调**（地图拖拽/点击）——单次脏事件不该炸掉整个地图，
 * 但也绝不能采纳，否则坏中心会经由 UI 进入后续提交。
 */
export function asBdLngLatOrNull(raw: unknown, where: string): LngLat | null {
  const ok = parseBdLngLat(raw)
  if (ok) return ok
  warnReject(where, `产出非法 BD-09 坐标，已忽略：${JSON.stringify(raw)} —— ${describeCoordSys(raw)}`)
  return null
}

/**
 * **来源不可信**的拒绝：值本身可能完全合法，但**它的来源**不该被采信 → 一律 `null` + 告警。
 *
 * ## 为什么必须和 `asBdLngLatOrNull` 分开
 *
 * 值域闸有个无法回避的盲区：它只能判断「值长得对不对」，判断不了「值是从哪来的」。
 * BMapGL 拖拽事件里的 `e.point` 是**投影平面米**，一旦某个版本/某条链路把它先做过
 * 取模/包裹，落进 `|lng|<=180, |lat|<=90` 就成了「值域合法、语义全错」——值域闸查不出来。
 *
 * 历史事故现场：`e.point = (11440230.81, 2860409.52)`，取值域模后得到 `(150.81, ...)`，
 * 中心落到北极圈、无瓦片、画布退化为纯色，且该值经 API 落库**永久复现**。
 *
 * ⇒ 真正的防线是**来源纪律**（只采纳 `e.latLng` / `marker.getPosition()`），值域闸只是第二道。
 * 因此这里报的是「**来源**为什么不可信」，而不是含糊的「值不合法」——后者会把
 * 「事件只带了 e.point」误报成「值算错了」，排查方向直接跑偏。
 *
 * @param raw  实际收到的值（**务必传进来**：告警里要能看见墨卡托量级，否则诊断价值为零）
 * @param why  来源不可信的原因，需给出「应该改用哪个字段」这类可操作结论
 */
export function rejectBdLngLatSource(raw: unknown, where: string, why: string): null {
  warnReject(where, `拒绝该坐标来源，不予采纳：${why}｜收到 ${JSON.stringify(raw)} —— ${describeCoordSys(raw)}`)
  return null
}

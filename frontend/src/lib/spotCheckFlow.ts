/**
 * 地标体检的**单一发起口**（片 2）：把报告页里的一行景点，翻成体检台能接的一次发起意图。
 *
 * ## 为什么要单独一个模块（而不是在组件里 `navigate(...)`）
 *
 * 「点景点 → 起体检」这件事在报告页有**多个面**都要给（点位、评分榜行，将来还有行程站点、
 * 舆情面板）。若每个面各自手拼一次 `navigate('/life-circle/custom', { state: {...} })`，
 * 它们迟早会漂移成几份不同的载荷形状，而其中一份少了来源或坐标系，报告就直接错。
 * ⇒ 映射收在这里：**纯函数、零 router hook**（`useNavigate` 由页面注入），
 * 任何新面接入只是"把实体适配成 `SpotLaunchTarget` + 调一次 navigate"。
 *
 * ## 边界类型不借展示层的 `MapSpot`
 *
 * `MapSpot` 归 `components/BMapBlock.tsx` 所有（含 `score/area/matched` 这些纯展示字段）。
 * 拿它当跨模块边界类型，等于让"发起体检"依赖一张地图卡的数据形状 —— 行程站点
 * （只带 spot_id/name/lat/lng）与舆情面板（今天没有坐标）要接这个口时只能伪造地图行。
 * ⇒ 边界类型在这里自定义（`SpotLaunchTarget`），`MapSpot` 是它的一个来源，不是它的定义。
 *
 * ## 两道门的严格程度不同（刻意）
 *
 * - **够不够格发起** ⇒ 返回 `null`：缺坐标 / 位置未命中 / 缺冻结实体键 / 缺宿主报告 ——
 *   这些都是数据常态，UI 该做的是"不摆入口"，不是炸掉整张榜单。
 * - **坐标能不能采纳** ⇒ **抛错**（`asBdLngLat`）：它是写入口，坏坐标一旦进库就永久复现
 *   （`lib/geo.ts` 记的北极圈事故），宁可当场失败。
 */
import type { LngLat, SpotCheckOrigin } from '../types'
import type { CoordSys } from './geo'
import { asBdLngLat, parseBdLngLat } from './geo'

/** 跨模块边界类型：发起一次地标体检所必需的最小信息（与展示层形状解耦）。
 *
 * ⚠️ **四个字段都是必填**，这不是洁癖：上一版把坐标写成 `lnglat: LngLat`，而映射函数读的是
 * `lat`/`lng` ⇒ 两处形状不一致，编译器**一声不响**（当时的入参类型是全可选的 `SpotLike`，
 * 任何对象都能赋给它）⇒ 点按钮静默返回 `null`、什么都不发生、控制台也不报错。
 * 现在两侧同形且必填，谁再把数组塞进来就是编译错误。 */
export interface SpotLaunchTarget {
  spot_id: string
  name: string
  lat: number
  lng: number
}

/** 送到体检台的一次发起意图：坐标**与坐标系标签必须同行**（偏 600m 的那种错就出在这里）。
 *
 *  `hostTitle` 是**纯展示**的宿主报告标题（确认框里那句"来自《…》"）：它随路由状态走，
 *  **不进 `origin`** —— `origin` 是与后端的契约（`SpotOrigin` 是 `extra="forbid"` 子模型，
 *  多一个键就是 422），而标题对服务端没有用（快照由它按 id 自取）。
 *  另：客户端填的标题可能失真，所以它只配出现在"给人看"的位置，不可被任何判据采信。 */
export interface SpotCheckIntent {
  name: string
  lnglat: LngLat
  coordSys: CoordSys
  origin: SpotCheckOrigin
  hostTitle?: string
}

/** `navigate(path, { state })` 的 state 形状（唯一写入口，见 `toSpotLaunch`）。 */
export interface SpotCheckNavState {
  spotCheck: SpotCheckIntent
}

const FALLBACK_NAME = '生活圈体检'

/**
 * 景点行 → 体检台发起意图。
 *
 * ## 谁判"够不够格"
 *
 * **调用点判**（`VSpotAtlas` 的 `launchable`：坐标齐备且未命中失败才放行，否则按钮 `disabled`）
 * —— 那张门用的是报告行自己的可选字段，是"这行数据能不能发起"的唯一裁决处。
 * 本函数**不再重复判断**：重复判断必然漂移（上一版的静默 `null` 就是被重复字段名掩盖掉的），
 * 而且它一旦判错只会静默不动作。类型说必填，这里就按必填用。
 *
 * ## 剩下唯一的运行期门：坐标值域
 *
 * 值域是真实数据唯一还会出错的地方（墨卡托米、越界、NaN）⇒ 走 `asBdLngLat` **抛错**：
 * 宁可当场炸出一个可见的告警，也不要再来一次静默无动作。
 *
 * @param hostReportId 宿主报告 id（攻略页的 `r_xxx`）。它是溯源三元组的一半，
 *   缺了就不给入口 —— 一条查不到来源的关联等于没记。这一位仍返回 `null`
 *   （它不是"数据脏"，而是"这个入口本就不该出现"）。
 * @param hostTitle 宿主报告标题（可选，纯展示；见 `SpotCheckIntent.hostTitle`）。
 */
export function toSpotLaunch(spot: SpotLaunchTarget, hostReportId: string, hostTitle?: string): SpotCheckNavState | null {
  const hostId = String(hostReportId ?? '').trim()
  if (!hostId) return null

  const title = String(hostTitle ?? '').trim()
  return {
    spotCheck: {
      name: String(spot.name ?? '').trim() || FALLBACK_NAME,
      lnglat: asBdLngLat([spot.lng, spot.lat], 'spotCheckFlow.toSpotLaunch'),
      coordSys: 'bd09',
      origin: { host_kind: 'guide', host_report_id: hostId, spot_id: String(spot.spot_id) },
      ...(title ? { hostTitle: title } : {}),
    },
  }
}

/**
 * 体检台的入站读口：把 `location.state` 解成发起意图，**畸形一律返回 `null`**。
 *
 * 这里用**宽松**取值（`parseBdLngLat`，不抛）：入站状态不是"我们自己刚写下的写入口"，
 * 而是路由器带过来的一份不可信输入（刷新、深链、别的标签页都可能改它）。
 * 单份脏状态不该炸掉体检台 —— 丢掉它，用户看到的只是"没有待办"。
 */
export function readSpotCheckLaunch(state: unknown): SpotCheckIntent | null {
  const raw = (state as { spotCheck?: unknown } | null | undefined)?.spotCheck as
    | Partial<SpotCheckIntent>
    | undefined
  if (!raw || typeof raw !== 'object') return null
  const origin = raw.origin as Partial<SpotCheckOrigin> | undefined
  const lnglat = parseBdLngLat(raw.lnglat)
  if (!lnglat || !origin) return null
  const hostReportId = String(origin.host_report_id ?? '').trim()
  const spotId = String(origin.spot_id ?? '').trim()
  if (!hostReportId || !spotId) return null
  return {
    name: String(raw.name ?? '').trim() || FALLBACK_NAME,
    lnglat,
    coordSys: raw.coordSys === 'wgs84' ? 'wgs84' : 'bd09',
    origin: {
      host_kind: String(origin.host_kind ?? '').trim() || 'guide',
      host_report_id: hostReportId,
      spot_id: spotId,
    },
    ...(String(raw.hostTitle ?? '').trim() ? { hostTitle: String(raw.hostTitle).trim() } : {}),
  }
}

/**
 * 地标体检 · 单一发起口（`lib/spotCheckFlow`）的单元判据（测试覆盖评估 F-01 / F-02）。
 *
 * ## 这两条在钉什么
 *
 * 报告页的景点行 → 「以该景点发起体检」按钮 → 体检台的确认框，中间**只有一个**映射出口。
 * 它要回答两件不同的事，不能混成一件：
 *
 * - **够不够格发起**：没有坐标、`matched===false`、缺 `spot_id` ⇒ 返回 `null`（UI 不给入口）。
 *   这是"要不要摆按钮"的二值判断，**不抛错** —— 拿不到坐标是数据常态，不是事故。
 * - **坐标能不能采纳**：值域不在 BD-09 内（典型是 BMapGL 的墨卡托平面米，量级 1e6~1e7）
 *   ⇒ **抛错**。这是**写入口纪律**：宁可当场失败，也不要把坏坐标写进库 —— 一次写库、
 *   之后每次打开都复现（`lib/geo.ts` 记的北极圈事故就是这个形状）。
 *
 * ## 为什么带"正对照"
 *
 * 只断言"非法输入返回 null / 抛错"是**恒真判据**：`() => null` 与 `() => { throw }`
 * 都能让它绿。所以每条都配一个合法输入的正对照，证明这个出口真的会产出东西。
 *
 * ## 状态：片 2 已落地，两条均转正向
 *
 * 这两条先以 `it.fails` 登记（模块尚不存在时钉"必须长出来"），片 2 落地当天摘标转正向。
 * 摘标时暴露过一次"红钉的成因"问题：`it.fails` 期间它们失败于"模块找不到"，
 * 与"映射逻辑写错"两种成因不可区分 —— 所以摘标不是走过场，是把真判据摆上桌。
 */
import { describe, expect, it } from 'vitest'
import { toSpotLaunch } from '../lib/spotCheckFlow'

const HOST = 'r_9e9c35b2'
/** BMapGL 拖拽事件里那个真实的墨卡托平面米读数（`lib/geo.ts` 北极圈事故现场值） */
const MERCATOR = { lat: 2860409.52, lng: 11440230.81 }
const OK_SPOT = { spot_id: 'spot_甲秀楼', name: '甲秀楼', lat: 26.5786, lng: 106.7123 }

describe('toSpotLaunch · 够不够格发起（F-01）', () => {
  it('缺坐标 / 未匹配 / 缺 spot_id ⇒ null；合法输入 ⇒ 才产出（正对照）', async () => {
    expect(toSpotLaunch({ ...OK_SPOT, lat: null, lng: null }, HOST), '缺坐标不该给入口').toBeNull()
    expect(toSpotLaunch({ ...OK_SPOT, matched: false }, HOST), '位置未命中的实体不该给入口').toBeNull()
    expect(toSpotLaunch({ ...OK_SPOT, spot_id: '' }, HOST), '缺冻结实体键不该给入口').toBeNull()
    expect(toSpotLaunch(OK_SPOT, ''), '缺宿主报告 id 不该给入口').toBeNull()

    // 正对照：合法输入必须产出可提交的载荷（否则上面四条是恒真判据）
    const out = toSpotLaunch(OK_SPOT, HOST)
    expect(out, '合法输入却拿不到载荷 —— 上面四条断言在空转').not.toBeNull()
    expect(out!.spotCheck.lnglat).toEqual([106.7123, 26.5786])
    expect(out!.spotCheck.coordSys).toBe('bd09')
    expect(out!.spotCheck.name).toBe('甲秀楼')
    expect(out!.spotCheck.origin).toEqual({
      host_kind: 'guide', host_report_id: HOST, spot_id: 'spot_甲秀楼',
    })
  })
})

describe('toSpotLaunch · 坐标能不能采纳（F-02）', () => {
  it('墨卡托平面米量级 ⇒ 当场抛错；BD-09 值域内 ⇒ 不抛（正对照）', async () => {
    expect(
      () => toSpotLaunch({ ...OK_SPOT, ...MERCATOR }, HOST),
      '墨卡托米被当成经纬度采纳 ⇒ 会把报告中心打到北极圈，且落库后永久复现',
    ).toThrow()
    expect(
      () => toSpotLaunch({ ...OK_SPOT, lat: 91, lng: 106.7 }, HOST),
      '纬度越界未被拦',
    ).toThrow()

    // 正对照：值域内的合法坐标不得抛
    expect(() => toSpotLaunch(OK_SPOT, HOST)).not.toThrow()
  })
})

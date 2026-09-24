/** 目的地自动识别的提示文案。
 *
 * 澄清流（问卷载荷 `destinations_fallback`）与运行流（task SSE 的 `plan_fallback` 消息）
 * 分属两条流、两个页面，不会同屏并存，因此两个字段各自独立、不合并成同一个布尔；
 * 这里只共用措辞，避免同一件事日后在两处漂移出两种说法。
 */
export const DEST_FALLBACK_HINT_CANDIDATES = '以下目的地为自动识别候选，建议核对或手动补充。'
export const DEST_FALLBACK_HINT_NONE =
  '未能自动识别目的地，可在「补充」题说明你关注的城市/地区。'
export const PLAN_FALLBACK_HINT =
  '目的地由自动识别得出，建议核对后再采纳；如与实际不符，请在需求里写明城市名后重跑。'

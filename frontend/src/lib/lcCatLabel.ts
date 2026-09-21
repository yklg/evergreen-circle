/** 生活圈民生类别 → 可展示 label —— 前端唯一判表（rev3 §四I / 用例 26）。
 *
 * 必须镜像后端 `app/living_circle/category_rule.CATEGORY_RULES` 的类别键集合与 label：
 * 缺键（前端少一类）或多键（口径漂移）由 `lcCatLabel.contract.test.ts` 拦截，
 * 杜绝两端类别数不一致导致图例/统计错位。
 */
export const LC_CAT_LABEL: Record<string, string> = {
  market: '菜市场',
  medical: '医疗',
  education: '教育',
  shopping: '购物',
  elderly: '养老',
  finance: '金融',
  recreation: '文体',
  service: '政务',
}
/**
 * 用户指定信源的**读取态**词表与中文标签（计划 v3 §二 F1 · 唯一前端落点）。
 *
 * 为什么单独一个模块：状态词表后端只有一份（`db.USER_SOURCE_STATES`），前端若在每个
 * 组件里各写一遍 `'fetched' → '已读取'`，就会出现「工作台上叫已读取、报告上叫已入链」
 * 这类同义漂移 —— 与 `domainEnumSingleSource` 守的是同一类事故。
 * 键集合与后端逐字一致由后端测试 `test_user_source_state_vocabulary_matches_frontend.ts`
 * 的镜像判据钉住（`tests/test_user_source_stats_and_labels.py`）。
 *
 * 注意与「覆盖率桶」是**两套词**：`unread/blocked/gated_off_query/merged/fetched/pending`
 * 描述"读没读到"（collect 写），`cited/uncited` 描述"用没用上"（audit 派生）。
 * 两者混用会让一条 404 被读成"未引用"，把安全/网络问题冒充成写作问题。
 */

export const USER_SOURCE_STATES = [
  'pending',
  'fetched',
  'unread',
  'blocked',
  'gated_off_query',
  'merged',
] as const

/** 条数上限：与后端 `fetcher.MAX_SOURCE_URLS` 同值，是**前端预检/提示**用的同一口径。
 *  真正的裁决仍在后端（它会截断并在 `sourceUrls.truncated` 里回报），前端只是不让用户
 *  在毫不知情的情况下填第 11 条。两处若漂开，由后端镜像测试判红。 */
export const MAX_USER_SOURCE_URLS = 10

export type UserSourceState = (typeof USER_SOURCE_STATES)[number]

/** Record<union, string> ⇒ 少写一个态就编译不过（不是运行时才发现）。 */
export const USER_SOURCE_STATE_LABELS: Record<UserSourceState, string> = {
  pending: '待读取',
  fetched: '已读取入链',
  unread: '没读到',
  blocked: '内网/非法地址已拒绝',
  gated_off_query: '已读取 · 与本次主题相关性低',
  merged: '与既有信源同质 · 已归并',
}

/** 覆盖率桶（audit 派生）另成一张表，与上面的读取态并列而不是互相冒充。 */
export const USER_SOURCE_COVERAGE_LABELS: Record<string, string> = {
  cited: '已引用',
  uncited: '未引用',
  pending: '未开始',
  unread: '没读到',
  blocked: '已拒绝',
}

/** 未登记状态回落原值显示：宁可显示一个裸 key，也不把它折算成"成功"或"失败"。 */
export function userSourceStateLabel(state: string): string {
  return USER_SOURCE_STATE_LABELS[state as UserSourceState] ?? state
}

export function userSourceCoverageLabel(coverage: string): string {
  return USER_SOURCE_COVERAGE_LABELS[coverage] ?? coverage
}

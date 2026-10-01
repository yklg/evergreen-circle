/**
 * 分隔式清单输入的唯一解析层（计划 v3 §二 F1）。
 *
 * 为什么存在：ClarifyPage 的「自定义目的地」输入早已用一套分隔与去重口径
 * （逗号/顿号/空白分隔 + 已选项合并去重）。首页的「用户指定信源」是同一种输入形态，
 * 若再抄一份 split 规则，两处会在分隔符集合或去重语义上漂开 —— 那正是 G0 之后
 * 本项目不再允许的"第二份真相源"形状。
 *
 * `mergeListItems` 的 `limit` 是**可见截断**：超出的条目数回报给调用方去显示，
 * 绝不静默丢弃（用户填了 12 条却只跑 10 条而不被告知，等于界面在说谎）。
 */

/** 分隔符集合与 ClarifyPage 历史口径逐字一致（逗号/中文逗号/顿号/任意空白）。 */
const SEPARATORS = /[,，、\s]+/

/** 把一次输入拆成条目：分隔 → trim → 去空。URL 本身不含空格，故按空白切分是安全的。 */
export function splitListItems(raw: string): string[] {
  return raw.split(SEPARATORS).map((s) => s.trim()).filter(Boolean)
}

export interface MergeResult {
  items: string[]
  /** 本次真正新增的条数（重复项不计） */
  added: number
  /** 因超出 limit 而未收录的条数（0 = 没有截断发生） */
  dropped: number
}

/**
 * 合并进已有清单：按值去重、保持先来后到的顺序、`limit` 处截断并**回报** dropped。
 *
 * 不传 limit 即不截断（ClarifyPage 的目的地选择不受 10 条约束）。
 */
export function mergeListItems(existing: string[], raw: string, limit?: number): MergeResult {
  const items = [...existing]
  let added = 0
  let dropped = 0
  for (const it of splitListItems(raw)) {
    if (items.includes(it)) continue
    if (limit !== undefined && items.length >= limit) {
      dropped += 1
      continue
    }
    items.push(it)
    added += 1
  }
  return { items, added, dropped }
}

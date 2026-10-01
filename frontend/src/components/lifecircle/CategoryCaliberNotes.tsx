/**
 * 类别旁一句口径说明（片 1c-β C1 甲档）。
 *
 * 为什么是一个共享件而不是两页各写一遍：报告页与体检台同屏说同一件事，两页各拼一次字符串
 * 就是两份披露文案各自漂移的起点（旧版正是如此 —— 报告页写了、体检台没写）。
 * **措辞与判据都在 `lib/livingCircle.lcCategoryCaliberNote`**，这里只管"哪些类别该印 + 排版"。
 *
 * 缺席即不印：旧快照（`cov-1` 名单上线前冻结）没有 `scored_as` ⇒ 整块不出现，
 * 而不是退回前端硬编码名单 —— 那等于在展示侧重判一次子类。
 */
import type { LivingCircleReport } from '../../types'
import { lcCategoryCaliberNote } from '../../lib/livingCircle'

export function CategoryCaliberNotes({ lc, className = 'mt-2 border-t border-line/60 pt-2' }: {
  lc: LivingCircleReport
  className?: string
}) {
  const cats = lc.poi?.categories ?? []
  const notes = cats.map(lcCategoryCaliberNote).filter((s): s is string => !!s)
  if (!notes.length) return null
  // 兜底那句只在"这一份确实按门槛项计过分"时出现（notes 非空即成立）：
  // 旧载荷里全部 8 类的分子都是点数，说"其余 N 类仍按点数"会把"整份都是点数"说成例外。
  const untabled = cats.filter((c) => c.required_in_circle == null).length
  return (
    <div className={className}>
      {notes.map((n) => (
        <p key={n} className="mt-1 text-tag leading-relaxed text-ink-3 first:mt-0">
          {n}
        </p>
      ))}
      {untabled > 0 && (
        <p className="mt-1 text-tag leading-relaxed text-ink-3">
          其余 {untabled} 类：覆盖度仍按圈内点数计分
        </p>
      )}
    </div>
  )
}

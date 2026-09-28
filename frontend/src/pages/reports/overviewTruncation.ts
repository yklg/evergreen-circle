/**
 * 「每次调研概览」的截断口径：整屏唯一决定"这句话怎么说"的地方。
 *
 * 为什么单独成模块（而不是放在卡片组件文件里）：eslint 的 `react-refresh/only-export-components`
 * 要求组件文件不再导出常量与函数；更重要的是，这段判据是**纯逻辑**，
 * 直接 `import` 就能钉住整句话，不必为了测文案而渲染一屏。
 *
 * ⚠️ P0 约束（架构评审 v9）：**「展开全部 N 份」里的 N 必须是点下去真能出现的份数**。
 * 后端 `cards` 带 `LIMIT 60`（`app/core/db.py:1117`），一旦库超过 60 份，
 * `report_total=61` 而 `cards.length=60` —— 这时按钮若写"展开全部 61 份"，
 * 点开只出 60 张，那就是本轮刚消灭的"截断样本冒充全量"换了个位置复活。
 * 所以 `cards_truncated` 为真时，按钮名只报**已取回**的份数，库内总数只出现在说明里。
 *
 * 「最近」二字成立的前提是后端按 `created_at` 降序发 cards —— 该前提由
 * `backend/tests/test_dashboard_stats.py::test_intel_cards_sorted_by_created_at_desc` 钉住。
 */
import type { IntelOverview } from '../../types'

/** 概览卡默认画几份。文案与 `slice` 都读这一个常量，改这里就够（别在文案里再写一遍 9）。 */
export const VISIBLE_CARDS = 9

export interface OverviewTruncation {
  /** 挂在标题旁的说明 */
  note: string
  /** 展开按钮的名字 */
  expandLabel: string
}

export function overviewTruncation(intel: IntelOverview): OverviewTruncation | null {
  const total = intel.report_total
  const fetched = intel.cards.length
  if (intel.cards_truncated) {
    return {
      note: `仅列最近 ${Math.min(VISIBLE_CARDS, fetched)} 份（已取回 ${fetched} 份，库内共 ${total} 份）`,
      expandLabel: `展开这 ${fetched} 份`,
    }
  }
  if (fetched > VISIBLE_CARDS) {
    return {
      note: `仅列最近 ${VISIBLE_CARDS} 份（库内共 ${total} 份）`,
      expandLabel: `展开全部 ${total} 份`,
    }
  }
  return null
}

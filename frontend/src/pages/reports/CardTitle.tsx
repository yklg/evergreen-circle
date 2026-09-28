/** 报告中心各块的标题行（标题 + 口径提示）。
 *
 *  从 `ResearchIntelView.tsx` 的私有 `CardTitle` 原样搬来：概览卡与专家榜各自成件后
 *  都要用它，留在页面里就会长出第二、第三份同样的 h3。 */
export function CardTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <h3 className="text-aux font-semibold text-ink">
      {title}
      <span className="ml-2 text-tag font-normal text-ink-3">{hint}</span>
    </h3>
  )
}

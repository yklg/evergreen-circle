import { TriangleAlert } from 'lucide-react'

/**
 * 域屏的失败态（两屏共用一份实现）。
 *
 * 为什么单独成件：把"取数失败"渲染成「暂无报告」是这页反复踩过的坑 —— 用户去找
 * 记录的地方看不到成因，就永远分不清是真的没有还是没取到。判据见
 * `__tests__/reportsPageErrorVsEmpty.test.tsx`（每屏各自成立）。
 */
export default function LoadFailure({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mt-6 flex flex-col items-start gap-3 rounded-card border border-risk/60 bg-risk/10 p-5"
    >
      <span className="inline-flex items-center gap-2 text-aux font-semibold text-ink">
        <TriangleAlert size={16} className="text-risk" /> {detail}
      </span>
      <p className="text-tag text-ink-2">
        这里不显示「暂无」，因为无法区分是真的没有还是没取到。后端未就绪或无权限时，重试即可。
      </p>
      <button
        onClick={onRetry}
        className="inline-flex h-9 items-center rounded-btn bg-primary px-4 text-aux font-medium text-white hover:bg-primary-deep"
      >
        重试
      </button>
    </div>
  )
}

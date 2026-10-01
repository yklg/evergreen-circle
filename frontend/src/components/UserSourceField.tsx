import { useState } from 'react'
import { Link2, Plus, X } from 'lucide-react'
import { mergeListItems } from '../lib/listInput'

/**
 * 用户指定信源输入区（计划 v3 §二 F1）。
 *
 * 四条硬要求决定了这里的形状：
 * 1. **粘贴多条是主用法** ⇒ 输入框必须是 textarea：`<input type=text>` 的取值净化会
 *    剥掉换行符（HTML 规范），从文档里复制的换行列表会被粘成一整串超长网址；
 * 2. **超过上限必须可见**：`mergeListItems` 回报 dropped，界面立刻说"未收录 N 条"，
 *    而不是静默收下（用户填了 12 条、系统跑 10 条却不吭声，等于界面在说谎）；
 * 3. **后端回执原样上屏**：`rejected/truncated` 是入口卫生的结论，显示的是 `accepted`
 *    那份归一化清单，而不是用户输入的原样串；
 * 4. **演示态不可用要说明**：fixture/离线不联网，输入禁用并写明原因，
 *    而不是留一个填了也没用的框（静默失效是本项目点名禁止的形状）。
 *
 * 为什么整块是 `<details>` 而不是常开（首屏适配，见计划 fluid-mist-eel）：
 * 常开时它给主输入卡加 191px，把「试试这些示例」整排挤到屏幕外。
 * - **不随 `urls.length` 自动展开**：默认清单是服务端存的，自动展开等于对已有清单的
 *   用户永远收起，这一档就白做；收起态改由 summary 上的「已钉 N 条」报数。
 * - 收起态必须仍说真话：演示态下清单不会被读取，所以 summary 直接念这句，
 *   而不是留一个「已钉 4 条」让人以为它会生效。
 * - 选 `<details>` 而非「按钮 + 条件 class」：测试环境不注入 Tailwind 样式，
 *   `hidden` 类算不出 `display:none`，可见性判据会恒绿；而 jest-dom 的 `toBeVisible()`
 *   是照 `<details>` 的 `open` 属性判的，收起态能被真实测出来。
 */
export function UserSourceField({
  urls,
  onChange,
  acceptedEcho,
  rejected,
  truncated,
  limit,
  disabled,
  disabledReason,
  remember,
  onRememberChange,
}: {
  urls: string[]
  onChange: (next: string[]) => void
  /** 后端归一后的清单（与本地清单不一致时才提示，避免同一份内容说两遍） */
  acceptedEcho?: string[]
  rejected?: { url: string; reason: string }[]
  truncated?: number
  limit: number
  disabled?: boolean
  disabledReason?: string
  remember?: boolean
  onRememberChange?: (v: boolean) => void
}) {
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState('')

  function add() {
    const { items, dropped } = mergeListItems(urls, draft, limit)
    setDraft('')
    setNotice(
      dropped > 0 ? `最多 ${limit} 条，本次有 ${dropped} 条未收录（去重后仍然超出）。` : '',
    )
    onChange(items)
  }

  return (
    <details className="mt-3 rounded-btn border border-line/70 bg-bg/40">
      <summary className="flex cursor-pointer select-none list-none items-center gap-1.5 px-3 py-1.5 text-tag font-medium text-ink-2 [&::-webkit-details-marker]:hidden">
        <Link2 size={13} className="shrink-0 text-primary-deep" />
        <span className="shrink-0">用户指定信源（选填）</span>
        {disabled ? (
          <span className="truncate text-warn">演示/离线模式不会联网，下面这些网址不会被读取</span>
        ) : (
          <span className="truncate text-ink-3">调研时服务端直接读取这些网页，最多 {limit} 条</span>
        )}
        {urls.length > 0 && (
          <span className="ml-auto inline-flex h-6 shrink-0 items-center rounded-chip bg-primary-tint px-2 text-primary-deep">
            已钉 {urls.length} 条
          </span>
        )}
      </summary>

      <div className="px-3 pb-3 pt-1">
        <div className="flex gap-2">
          <textarea
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (!disabled) add()
              }
            }}
            disabled={disabled}
            placeholder="粘贴网址，支持一次多条（逗号 / 空格 / 换行分隔）"
            aria-label="用户指定信源网址"
            className="min-w-0 flex-1 resize-none rounded-btn border border-line bg-card px-3 py-1.5 text-tag text-ink outline-none placeholder:text-ink-3 focus:border-primary disabled:cursor-not-allowed disabled:opacity-60"
          />
          <button
            type="button"
            onClick={add}
            disabled={disabled || !draft.trim()}
            className="inline-flex h-9 shrink-0 items-center gap-1 self-start rounded-btn bg-primary-tint px-3 text-tag font-medium text-primary-deep hover:bg-primary-soft/40 disabled:opacity-40"
          >
            <Plus size={13} /> 添加
          </button>
        </div>

        {disabled && (
          <p className="mt-2 text-tag text-warn" role="status">
            {disabledReason ?? '当前为演示/离线模式，不会联网，填写的网址不会被读取。'}
          </p>
        )}

        {urls.length > 0 && (
          <ul className="mt-2 flex max-h-24 flex-wrap gap-1.5 overflow-y-auto">
            {urls.map((u) => (
              <li key={u}>
                <span className="inline-flex max-w-[420px] items-center gap-1 rounded-chip bg-primary-tint px-2 h-6 text-tag text-primary-deep">
                  <span className="truncate" title={u}>{u}</span>
                  {!disabled && (
                    <button
                      type="button"
                      aria-label={`移除 ${u}`}
                      onClick={() => onChange(urls.filter((x) => x !== u))}
                      className="shrink-0 rounded-full hover:bg-primary-soft/50"
                    >
                      <X size={12} />
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}

        {(notice || (rejected?.length ?? 0) > 0 || (truncated ?? 0) > 0) && (
          <p className="mt-2 rounded-btn bg-warn/10 px-2.5 py-1.5 text-tag text-[#8A6420]" role="alert">
            {notice}
            {truncated ? `后端按上限截断：未收录 ${truncated} 条。` : ''}
            {(rejected ?? []).map((r) => `${r.url}：${r.reason}`).join('；')}
          </p>
        )}

        {acceptedEcho && acceptedEcho.join('\n') !== urls.join('\n') && (
          <p className="mt-2 text-tag text-ink-3">
            已按服务端归一：{acceptedEcho.join('、')}
          </p>
        )}

        {!disabled && onRememberChange && (
          <label className="mt-2 inline-flex items-center gap-1.5 text-tag text-ink-2">
            <input
              type="checkbox"
              checked={!!remember}
              onChange={(e) => onRememberChange(e.target.checked)}
            />
            存为下次默认（保存到服务端偏好，换浏览器仍在）
          </label>
        )}
      </div>
    </details>
  )
}

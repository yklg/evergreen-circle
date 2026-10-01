/**
 * C4 · 逐格台账卡（计划 cells-ledger-judge-scale §5.2）。
 *
 * 这张卡补的是报告里一直缺的那一层：判盲以格为单位，产物却只到「四类计数 + 连续盲区环」。
 * 环面积能对上格数，但它 smeared 跨十几格 ⇒ **哪几格判盲、哪几格未定，指不出来**。
 * 用户连着三次问"这块为什么不算盲"，缺的就是这个。
 *
 * 两件事分开做：
 *  - **格阵**（上方小图）：一眼看完 n×n 全部格态，点一格即选中；
 *  - **读数**（下方表）：选中格的三类各「有据 / 命中 / 最近距离」。
 *
 * ⚠️ 本组件**只解码，不重算**：结论取自台账发下来的 `blind`/`verdict`/`capped` 三张位，
 * 不在这里判"缺哪类算盲" —— 那条不对称规则只许有 `_verdict_masks` 一处实现。
 * ⚠️ 四档无结论要说两句话：`未定`（有类没查全，是我们的取证缺口）与 `封顶`（接口能力到头）
 * 不是同一件事，合并成"没结论"就是把失职洗成天经地义。
 */
import { LC_JUDGE_SCALE_COLOR } from '../../lib/livingCircle'
import type { LedgerCellState, LedgerVerdict } from '../../lib/livingCircle'
import type { CellsLedgerRaw } from '../../types'

/** 五档配色。`outside` 不上色（可达区外语义上就不该判盲，画出来会像"这里没问题"）。 */
const FILL: Record<LedgerVerdict, string> = {
  outside: 'transparent',
  clear: LC_JUDGE_SCALE_COLOR,
  unknown: '#E0B775',
  capped: '#C9A87C',
  blind: '#6E6E6E',
}
const OPACITY: Record<LedgerVerdict, number> = {
  outside: 0, clear: 0.34, unknown: 0.55, capped: 0.55, blind: 0.8,
}
const WORD: Record<LedgerVerdict, string> = {
  outside: '可达区外 · 不判',
  clear: '确认不盲（三类皆有据且皆命中）',
  unknown: '未定（有类没查全 —— 我们的取证缺口）',
  capped: '判不动（接口能力封顶）',
  blind: '判盲（至少一类有据且 1km 内确实没有）',
}

const cellXy = (led: CellsLedgerRaw, i: number, j: number): [number, number] => [
  Math.round(-led.scan_m + j * led.step_m),
  Math.round(-led.scan_m + i * led.step_m),
]

export default function CellsLedgerCard({ led, verdictAt, selected, onPick }: {
  led: CellsLedgerRaw
  /** 取一格的读数。由页面用 `cellVerdict` 供给 —— 卡片不自己解字符。 */
  verdictAt: (i: number, j: number) => LedgerCellState | null
  selected: [number, number] | null
  onPick: (cell: [number, number] | null) => void
}) {
  const n = led.n
  const side = 240
  const unit = side / n
  const sel = selected ? verdictAt(selected[0], selected[1]) : null
  const counts: Record<LedgerVerdict, number> = { outside: 0, clear: 0, unknown: 0, capped: 0, blind: 0 }
  for (let i = 0; i < n; i += 1) for (let j = 0; j < n; j += 1) counts[verdictAt(i, j)!.verdict] += 1

  return (
    <div className="rounded-card border border-line bg-card p-4 shadow-card">
      <div className="flex items-baseline justify-between">
        <div className="text-aux font-semibold text-ink">逐格台账</div>
        <div className="text-tag text-ink-3">
          {n}×{n} 格 · 格距 {Math.round(led.step_m)}m · 尺 {Math.round(led.radius_m)}m
        </div>
      </div>

      <svg viewBox={`0 0 ${side} ${side}`} className="mt-2 w-full" role="img"
           aria-label="逐格判定台账格阵">
        {Array.from({ length: n * n }, (_, k) => {
          const i = Math.floor(k / n)
          const j = k % n
          const st = verdictAt(i, j)!
          const isSel = !!selected && selected[0] === i && selected[1] === j
          return (
            <rect
              key={`${i}-${j}`}
              data-cell={`${i}-${j}`}
              x={j * unit} y={side - (i + 1) * unit}
              width={unit} height={unit}
              fill={FILL[st.verdict]} fillOpacity={OPACITY[st.verdict]}
              stroke={isSel ? LC_JUDGE_SCALE_COLOR : '#E3E8E3'}
              strokeWidth={isSel ? 2 : 0.5}
              className="cursor-pointer"
              onClick={() => onPick(isSel ? null : [i, j])}
            >
              <title>{`(${i},${j}) ${WORD[st.verdict]}`}</title>
            </rect>
          )
        })}
      </svg>

      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-tag text-ink-3">
        {(['blind', 'clear', 'unknown', 'capped'] as const).map((k) => (
          <span key={k} className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ background: FILL[k], opacity: Math.max(OPACITY[k], 0.45) }} />
            {k === 'blind' && `判盲 ${counts.blind}`}
            {k === 'clear' && `不盲 ${counts.clear}`}
            {k === 'unknown' && `未定 ${counts.unknown}`}
            {k === 'capped' && `封顶 ${counts.capped}`}
          </span>
        ))}
      </div>

      {!sel && (
        <p className="mt-3 border-t border-line pt-2 text-tag text-ink-3">
          点上面任意一格看它的判定依据；开着「判定尺」时也可以直接在地图上点一块。
        </p>
      )}

      {sel && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="flex items-baseline justify-between">
            <div className="text-tag font-medium text-ink-2">
              格 ({sel.i},{sel.j}) · 相对中心 ({cellXy(led, sel.i, sel.j)[0]}, {cellXy(led, sel.i, sel.j)[1]})m
            </div>
            <button onClick={() => onPick(null)} className="text-tag text-ink-3 hover:text-ink">
              清除
            </button>
          </div>
          <div className="mt-1 text-aux font-semibold text-ink">{WORD[sel.verdict]}</div>
          <table className="mt-2 w-full border-collapse text-tag">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="pb-1 font-medium">必达类</th>
                <th className="pb-1 font-medium">有据？</th>
                <th className="pb-1 font-medium">1km 内命中？</th>
                <th className="pb-1 text-right font-medium">最近</th>
              </tr>
            </thead>
            <tbody>
              {sel.classes.map((c) => (
                <tr key={c.key} className="border-t border-line">
                  <td className="py-1 text-ink">{c.label}</td>
                  <td className="py-1 text-ink-2">{c.evidence ? '是' : '否'}</td>
                  <td className="py-1 text-ink-2">
                    {c.hit === null ? '无从知道' : c.hit ? '命中' : '没有'}
                  </td>
                  <td className="py-1 text-right text-ink-3">
                    {c.nearestM === null ? '—' : `${c.nearestM}m`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-tag text-ink-3">
            「有据」= 这格的 {Math.round(led.radius_m)}m 圆完整落在该类已证明查全的盘里；
            「无从知道」= 那一类没查全，<b>不是</b>"确认没有"。
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * 方位条形图（笔三 S15）：把一颗等时圈的 8 个方位最远可达半径摆成可点的一列。
 *
 * 为什么是条形而不是极坐标玫瑰图：玫瑰图与第一屏那张 **8 维设施雷达图**同为径向多边形，
 * 读者会把它当成"又一组评分维度" —— 而形状量按口径**不参与评分**（`AGENTS.md §7.4`）。
 * 换成带方位词的横条，形状上就不可能被读成分数。
 *
 * 三条纪律：
 *  1. 数值只从 `shapeOfZone` 这一颗出口取（出口返回 `null` ⇒ 本组件返回 `null`，
 *     整块不出现）。渲染面**不许**自己 `Math.min(...bins)/Math.max(...bins)` ——
 *     那会长出第二个生产者，守卫按特征扫 `src/` 会红。
 *  2. 方位词来自键里的 `bins_word`，前端不另抄词表。
 *  3. 措辞只指方向，不判好坏：圆度测的是各向均匀性（方差），"好不好"是水平（均值）。
 */
import type { LivingCircleReport } from '../../types'
import {
  shapeCaveatNote,
  shapeOfZone,
  shapeSentence,
  shapeSuspectNote,
  shapeWeakStrong,
} from '../../lib/livingCircle'

export interface DirectionBarsProps {
  lc: LivingCircleReport
  /** 读哪一档的形状（当前只有 15/20 发键） */
  minutes: number
  /** 选中方位下标（与地图扇区共用一个 state） */
  selected: number | null
  onPick: (index: number | null) => void
  className?: string
}

export default function DirectionBars({ lc, minutes, selected, onPick, className }: DirectionBarsProps) {
  const shape = shapeOfZone(lc, minutes)
  if (!shape) return null                       // 不发屏：缺键 / 口径不符 / 值非法
  const { weak, strong } = shapeWeakStrong(shape)
  const rMax = Math.max(...shape.bins_m)
  const sentence = shapeSentence(lc, minutes)
  const suspect = shapeSuspectNote(lc, minutes)
  const caveat = shapeCaveatNote(lc, minutes)

  return (
    <div className={'rounded-card border border-line bg-card p-4 shadow-card ' + (className ?? '')}>
      <div className="text-aux font-semibold text-ink">方位最远可达 · {minutes}min</div>
      <div className="mt-0.5 text-tag text-ink-3">
        原点 {shape.origin} · {shape.bin_deg}° 分箱 · 分相 {shape.bin_phase} · 单位 m
      </div>

      <div className="mt-2 flex flex-col gap-0.5">
        {shape.bins_m.map((m, i) => {
          const on = selected === i
          return (
            <button
              key={`${shape.bins_word[i]}-${i}`}
              type="button"
              aria-pressed={on}
              aria-label={`${shape.bins_word[i]}方向最远可达 ${Math.round(m)} 米`}
              onClick={() => onPick(on ? null : i)}
              className={
                'grid w-full grid-cols-[3.2rem_1fr_3rem] items-center gap-2 rounded-[10px] border px-1.5 py-1.5 text-left transition-colors '
                + (on ? 'border-risk/40 bg-risk/5' : 'border-transparent hover:bg-ink/5')
              }
            >
              <span className={'text-right text-tag ' + (on ? 'font-semibold text-[#A5625B]' : 'text-ink-2')}>
                {shape.bins_word[i]}
              </span>
              <span className="h-3.5 overflow-hidden rounded bg-ink/5">
                <span
                  className={'block h-3.5 rounded ' + (on ? 'bg-[#B9665E]' : 'bg-primary/70')}
                  style={{ width: `${(m / rMax) * 100}%` }}
                />
              </span>
              <span
                className={
                  'text-right text-tag tabular-nums '
                  + (i === weak ? 'font-semibold text-[#A5625B]' : 'text-ink')
                }
              >
                {Math.round(m)}
              </span>
            </button>
          )
        })}
      </div>

      {sentence && <p className="mt-2 text-tag leading-relaxed text-ink-3">{sentence}</p>}
      {suspect && <p className="mt-1 text-tag font-medium leading-relaxed text-warn">{suspect}</p>}
      {caveat && <p className="mt-1 text-tag leading-relaxed text-ink-3">{caveat}</p>}
      <p className="mt-1 text-tag leading-relaxed text-ink-3">
        同图仅标出最弱（{shape.bins_word[weak]}）与最强（{shape.bins_word[strong]}）两格；
        方位分布与设施布点是两回事，这里只说"这个方向走不远"，不指认原因。
      </p>
    </div>
  )
}

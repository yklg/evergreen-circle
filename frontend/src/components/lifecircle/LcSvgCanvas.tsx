/**
 * 生活圈静态画布的共享图层装配（§13 W1）。
 *
 * ## 它治的病
 * 同一张静态画布在仓里有两棵内联 JSX：报告页的打印替身 `IsochroneSnapshot` 与 `LcMap` 的降级分支。
 * 四族图元逐字相近，其中等时圈那一族**已经分叉过一次** —— 一边按原序 `zi % 色表长` 取色，
 * 一边 `findIndex(按 minutes)` 取色再倒序绘制。两份写法今天算得出同一组色（载荷恒 5/10/15/20 升序），
 * 但"哪天载荷多一档或换了序"就只有其中一张会变色 —— 这正是本仓反复在消灭的"同一口径两处实现"。
 *
 * ## 边界（写给下一个人，别把这些搬进来）
 * `data-lc-mode`、`data-lc-layers`、降级角标「地图降级 · 静态画布」与那 35 行反投影点击通道
 * **留在 `LcMap`**：它们表达的是"这里有一个 LcMap 实例、它落在哪一档、真的建出了哪些层"，
 * 分章静态图若也带上，报告页的实例计数（jsdom 数角标＝3、e2e 数体检单栏＝2）与逐层申报判据
 * 会同时错位。同理 **accessible name 由调用方传入** —— 降级画布与打印快照两颗既有名字必须逐字不变，
 * `findByRole('img', { name })` 多命中即抛，而"顺手统一个名字"一次能红四条既有判据。
 *
 * ## 没收进来的那一族
 * 盲区层是**判定后的保留**而非遗漏：两份的差异不是开关能表达的（一份带 `#N`·重度标注与补点 Marker，
 * 另一份带概略面积文字与判定尺参考圈），重合度按「复用 vs 复制判定」不足七成 ⇒ 各自实现，
 * 命名与结构对齐本文件。折算口径本来就同源（`coarseBlindFootprint`），那是值层而非 JSX 层的重复。
 */
import { LC_CANVAS, LC_ISO_COLORS, lcPolyPts, lcRightmost, lcToPx } from '../../lib/livingCircle'
import type { LcFrame, LcSnapshotPoiDot } from '../../lib/livingCircle'
import type { IsochroneZone, LngLat } from '../../types'

/**
 * 画布底 ＋ 5×5 参照网格。尺寸只从 `LC_CANVAS` 取（唯一真相源），调用点不再各抄一份宽高 ——
 * 那两个数一旦分叉，两张图的投影比例就不同，而它们共用同一个 `lcToPx`。
 *
 * `frame` 只用来**扩覆盖范围**（对照态降级画布按两侧内容并集取景时会超出整幅画布），
 * 网格间距仍是画布的 1/5 —— 那是比例尺本身，跟着画框走就成了"缩放改口径"。
 * 不传 ⇒ 逐字是今天那张（`-2..2` 恰好铺满 860×620）。
 */
export function LcCanvasBackdrop({ frame }: { frame?: LcFrame } = {}) {
  const { W, H } = LC_CANVAS
  const f = frame ?? { x: 0, y: 0, w: W, h: H }
  const colOf = (i: number) => W / 2 + (i * W) / 5
  const rowOf = (i: number) => H / 2 + (i * H) / 5
  const span = (half: number, step: number, from: number, to: number) => {
    const idx: number[] = []
    for (let i = Math.ceil((from - half) / step); i <= Math.floor((to - half) / step); i += 1) idx.push(i)
    return idx
  }
  return (
    <>
      <rect x={f.x} y={f.y} width={f.w} height={f.h} fill="#f9faf8" />
      {span(W / 2, W / 5, f.x, f.x + f.w).map((i) => (
        <line key={`v${i}`} x1={colOf(i)} y1={f.y} x2={colOf(i)} y2={f.y + f.h} stroke="#e7ebe7" strokeWidth={1} />
      ))}
      {span(H / 2, H / 5, f.y, f.y + f.h).map((i) => (
        <line key={`h${i}`} x1={f.x} y1={rowOf(i)} x2={f.x + f.w} y2={rowOf(i)} stroke="#e7ebe7" strokeWidth={1} />
      ))}
    </>
  )
}

/**
 * 等时圈族：多边形 ＋ 右端分钟标签。
 *
 * `drawOuterFirst` 是两档**唯一**的真实差异（打印快照先画外圈、让内圈的深色留在上面；
 * 降级画布按载荷原序画），它只改绘制顺序，不改取色 —— 取色恒按载荷原序取模，
 * 于是"5 分钟档永远是最深那一档"这条口径只有一份实现。
 */
export function LcIsochroneBands({ center, zones, drawOuterFirst = false }: {
  center: LngLat
  zones: IsochroneZone[]
  drawOuterFirst?: boolean
}) {
  const ordered = drawOuterFirst ? [...zones].sort((a, b) => b.minutes - a.minutes) : zones
  return (
    <>
      {ordered.map((z) => {
        const color = LC_ISO_COLORS[zones.indexOf(z) % LC_ISO_COLORS.length]
        const ring = z.geojson.coordinates[0] ?? []
        const [lx, ly] = lcRightmost(center, ring)
        return (
          <g key={z.minutes}>
            <polygon points={lcPolyPts(center, ring)} fill={color?.fill} stroke={color?.stroke} strokeWidth={1.5} strokeLinejoin="round" />
            <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>
              {z.minutes} min
            </text>
          </g>
        )
      })}
    </>
  )
}

/** 分章地图把非焦点类目压到这个不透明度（与预览包 `gen_preview.py` 同一档，肉眼读得出"在但次要"）。 */
export const LC_POI_DIM = 0.16

/**
 * POI 点位：点集**只从 `lcSnapshotPoiLayer` 取**（全仓唯一口径，`livingCircle.ts:397`），
 * 本装配只负责那圈 `<circle>`。`r`／`strokeWidth` 由调用方给是**既成分叉的如实登记**
 * （打印快照 6／1.5、降级画布 5／1.2）—— 统一它属于改形态，要单独判定，不在本笔顺手做。
 *
 * `focusCategories` 是 nar-3 分章地图的焦点：**只压淡、一个点都不删**（提纯成单类会显著提高
 * 那一类精确坐标的可辨识度，是新增泄漏面）。不传时全体 0.92，与收一之前逐字节同形。
 */
export function LcPoiDots({ dots, r, strokeWidth, focusCategories }: {
  dots: LcSnapshotPoiDot[]
  r: number
  strokeWidth: number
  focusCategories?: string[]
}) {
  const focus = focusCategories && focusCategories.length ? new Set(focusCategories) : null
  return (
    <>
      {dots.map((p) => (
        <circle
          key={p.key} cx={p.cx} cy={p.cy} r={r} fill={p.fill} stroke="#fff" strokeWidth={strokeWidth}
          opacity={focus ? (focus.has(p.category) ? 0.92 : LC_POI_DIM) : 0.92}
        >
          {p.title && <title>{p.cluster > 1 ? `${p.title}（该网格聚合 ${p.cluster} 点）` : p.title}</title>}
        </circle>
      ))}
    </>
  )
}

/** 场景中心：虚线参考圈 ＋ 实心点 ＋ 社区名。两档逐字相同，故不给尺寸参数。 */
export function LcSceneCenterMark({ center, name }: { center: LngLat; name: string }) {
  // 两档今天写的都是 `lcToPx(center, center[0], center[1])`（投影原点即地理中心），收成一处。
  const [x, y] = lcToPx(center, center[0], center[1])
  return (
    <g>
      <circle cx={x} cy={y} r={14} fill="rgba(124,152,133,0.18)" stroke="#5F7B69" strokeWidth={1.5} strokeDasharray="3 3" />
      <circle cx={x} cy={y} r={6} fill="#5F7B69" stroke="#fff" strokeWidth={2} />
      <text x={x} y={y - 20} fontSize={12} fill="#3f5042" textAnchor="middle" fontWeight={600}>
        {name}
      </text>
    </g>
  )
}

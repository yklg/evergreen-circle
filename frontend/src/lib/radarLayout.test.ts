import { describe, it, expect } from 'vitest'
import {
  layoutRadar,
  RADAR_DEFAULTS,
  RADAR_RING_LEVELS,
  type RadarDim,
  type RadarLayout,
} from './radarLayout'
import { LC_CAT_LABEL } from './lcCatLabel'

/* 雷达图布局不变量测试。
 *
 * 守的是同一条不变量的两面，缺一不可：
 *  ① **包含性**：标签字形盒必须整体落在派生 viewBox 内（旧实现上下两端出界）；
 *  ② **不互压**：标签不得压进外环（旧实现用 `text-anchor` 反向翻转把左右拉回视口，
 *     代价是 6/8 个标签盖在多边形上 —— 只测 ① 会放过它）。
 *
 * 为什么必须做成纯函数才能测：jsdom 30 里 `getBBox` / `getComputedTextLength` /
 * `getExtentOfChar` 全是 undefined，DOM 侧量不到真实字形盒。后来者若把几何"简化"
 * 回组件里，这两条不变量就同时失去可执行防线。
 *
 * 旧实现的对照值是 2026-09-25 用真实 Chrome 量出来的（见预览 shots/，font-size 11）：
 *   菜市场 上探 −7.37、养老 下探 −10.61；
 *   购物/金融 压入外环 −11.37，教育/文体 −9.69，医疗/政务 −4.32。
 *
 * 第二道闸（本文件测不到的那半）：估算器 vs Chrome 真实度量、以及卡片实际宽度会不会把
 * 1 单位压到 1 CSS px 以下，只能真浏览器量。复验出口
 * `frontend/src/dev/radarPortVerify.tsx` → `npx vite-node src/dev/radarPortVerify.tsx`
 * 生成可双击的单文件，页内 `getBBox()` 现量四档卡片 × 8 标签，判据「零裁切 + 净空 ≥ 0 +
 * 实际 CSS 字号 ≥ 10.7」。改 `textMetrics` 任何常量后必须重跑它，只跑本文件不算数。
 */

const REAL_DIMS: RadarDim[] = Object.values(LC_CAT_LABEL).map((dimension, i) => ({
  dimension,
  score: [88.9, 93, 88.6, 97, 0, 90.7, 89.3, 78.8][i] ?? 50,
}))

/** 字形盒四边到 viewBox 边界的最小余量（负值即被裁） */
function edgeMargin(l: RadarLayout['labels'][number], layout: RadarLayout): number {
  return Math.min(l.bbox[0], l.bbox[1], layout.width - l.bbox[2], layout.height - l.bbox[3])
}

/** 标签字形盒到外环描边外沿的净空（负值即盖在多边形上） */
function ringClearance(l: RadarLayout['labels'][number], layout: RadarLayout): number {
  const nx = Math.min(Math.max(layout.cx, l.bbox[0]), l.bbox[2])
  const ny = Math.min(Math.max(layout.cy, l.bbox[1]), l.bbox[3])
  return Math.hypot(layout.cx - nx, layout.cy - ny) - (layout.radius + RADAR_DEFAULTS.strokeHalf)
}

function synthetic(count: number, charLen = 2): RadarDim[] {
  const stem = '社区服务'
  return Array.from({ length: count }, (_, i) => ({
    dimension: stem.slice(0, charLen).padEnd(charLen, '点') + i,
    score: 40 + i,
  }))
}

describe('layoutRadar · 包含性不变量', () => {
  it('IT-01 任意维度数下标签都不出界（n=5..8，5 为契约地板）', () => {
    for (const n of [5, 6, 7, 8]) {
      const layout = layoutRadar(REAL_DIMS.slice(0, n))
      expect(layout.labels).toHaveLength(n)
      for (const l of layout.labels) {
        expect(edgeMargin(l, layout), `n=${n} ${l.text} 被裁`).toBeGreaterThanOrEqual(0)
      }
    }
  })

  it('IT-01b 余量达到设计值 pad（不是"刚好不为负"的侥幸）', () => {
    const layout = layoutRadar(REAL_DIMS)
    const worst = Math.min(...layout.labels.map((l) => edgeMargin(l, layout)))
    // pad=6，坐标 round2 + viewBox ceil → 允许 0.1 的舍入损耗
    expect(worst).toBeGreaterThanOrEqual(RADAR_DEFAULTS.pad - 0.1)
  })

  it('IT-01c 网格环与辐条顶点也全在画布内', () => {
    const layout = layoutRadar(REAL_DIMS)
    const pts = [...layout.rings, { points: layout.dataPoints }].flatMap((g) =>
      g.points.split(' ').filter(Boolean).map((p) => p.split(',').map(Number)),
    )
    for (const [x, y] of pts) {
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x).toBeLessThanOrEqual(layout.width)
      expect(y).toBeGreaterThanOrEqual(0)
      expect(y).toBeLessThanOrEqual(layout.height)
    }
  })
})

describe('layoutRadar · 真实标签集回归', () => {
  it('IT-02 锁住当前 8 类的派生画布；后端改类别时此条随 LC_CAT_LABEL 自动跟进', () => {
    const layout = layoutRadar(REAL_DIMS)
    // 2026-09-25 真实 Chrome 度量校准后的值（静态估算曾虚低为 229×200）
    expect(layout.viewBox).toBe('0 0 242 215')
  })

  it('IT-02b 具名封住两个历史症状：菜市场不顶出界、养老不底出界', () => {
    const layout = layoutRadar(REAL_DIMS)
    const top = layout.labels.find((l) => l.text === '菜市场')!
    const bottom = layout.labels.find((l) => l.text === '养老')!
    // 旧实现：top.bbox[1] = −7.37；bottom.bbox[3] = 182.07 > viewBox 高 172
    expect(top.bbox[1]).toBeGreaterThanOrEqual(0)
    expect(bottom.bbox[3]).toBeLessThanOrEqual(layout.height)
  })
})

describe('layoutRadar · 标签不压多边形', () => {
  it('IT-03 每个标签到外环描边外沿都有正净空', () => {
    const layout = layoutRadar(REAL_DIMS)
    for (const l of layout.labels) {
      expect(ringClearance(l, layout), `${l.text} 压进外环`).toBeGreaterThanOrEqual(0)
    }
  })

  it('IT-03b 净空达到设计值 ringPad（旧锚点翻转在这里是 −11.37）', () => {
    const layout = layoutRadar(REAL_DIMS)
    const worst = Math.min(...layout.labels.map((l) => ringClearance(l, layout)))
    expect(worst).toBeGreaterThanOrEqual(RADAR_DEFAULTS.ringPad - 0.1)
  })

  it('IT-03c 锚点朝外：右侧 start、左侧 end、正上下 middle', () => {
    const layout = layoutRadar(REAL_DIMS)
    const byText = (t: string) => layout.labels.find((l) => l.text === t)!
    // 与旧实现相反 —— 旧的翻转是为了在过小的画布里硬塞，画布派生后不再需要
    expect(byText('教育').anchor).toBe('start') // 正右
    expect(byText('文体').anchor).toBe('end') // 正左
    expect(byText('菜市场').anchor).toBe('middle') // 正上
    expect(byText('养老').anchor).toBe('middle') // 正下
  })
})

describe('layoutRadar · 对抗标签形状', () => {
  it('IT-04 超长中文名：画布随内容变宽，而不是裁切', () => {
    const dims: RadarDim[] = [
      { dimension: '社区卫生服务中心', score: 60 },
      { dimension: '养老', score: 30 },
      { dimension: '医疗', score: 80 },
      { dimension: '文体', score: 45 },
    ]
    const layout = layoutRadar(dims)
    for (const l of layout.labels) {
      expect(edgeMargin(l, layout), `${l.text} 被裁`).toBeGreaterThanOrEqual(0)
      expect(ringClearance(l, layout), `${l.text} 压外环`).toBeGreaterThanOrEqual(0)
    }
    // CJK 逐字 1em（Chrome 实测校准值）。若误用词云那套 0.95，8 字名会少估 4.4 单位，
    // 差额正好被 pad 吃掉 —— 表现为"暂时不裁"，换字体就复发。
    const long = layout.labels.find((l) => l.text === '社区卫生服务中心')!
    expect(long.bbox[2] - long.bbox[0]).toBeCloseTo(8 * RADAR_DEFAULTS.fontSize, 6)
  })

  it('IT-04b ASCII 键可达（后端 label 缺省会兜底成 category 英文名）', () => {
    const dims: RadarDim[] = [
      { dimension: 'recreation', score: 50 },
      { dimension: 'market', score: 70 },
      { dimension: 'elderly', score: 20 },
      { dimension: 'medical', score: 90 },
    ]
    const layout = layoutRadar(dims)
    for (const l of layout.labels) {
      expect(edgeMargin(l, layout), `${l.text} 被裁`).toBeGreaterThanOrEqual(0)
    }
  })

  it('IT-04c 维度数增减都重新派生', () => {
    for (const n of [3, 5, 9, 12]) {
      const layout = layoutRadar(synthetic(n))
      expect(layout.labels).toHaveLength(n)
      for (const l of layout.labels) {
        expect(edgeMargin(l, layout), `n=${n} ${l.text}`).toBeGreaterThanOrEqual(0)
        expect(ringClearance(l, layout), `n=${n} ${l.text}`).toBeGreaterThanOrEqual(0)
      }
    }
  })
})

describe('layoutRadar · 纯函数契约', () => {
  it('IT-05 确定性：同输入同输出，且不改动入参', () => {
    const input = REAL_DIMS.map((d) => ({ ...d }))
    const before = JSON.stringify(input)
    const a = layoutRadar(input)
    const b = layoutRadar(input)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
    expect(JSON.stringify(input)).toBe(before)
  })

  it('IT-05b 不吐 NaN / Infinity', () => {
    const layout = layoutRadar(REAL_DIMS)
    const nums = [
      layout.width, layout.height, layout.cx, layout.cy, layout.radius, layout.labelGap,
      ...layout.spokes.flatMap((s) => [s.x1, s.y1, s.x2, s.y2]),
      ...layout.labels.flatMap((l) => [l.x, l.y, ...l.bbox]),
    ]
    for (const v of nums) expect(Number.isFinite(v)).toBe(true)
    expect(layout.viewBox).toMatch(/^0 0 \d+ \d+$/)
  })

  it('IT-06 空维度仍返回有效画布（ComparePage 选到离线记录是线上路径）', () => {
    const layout = layoutRadar([])
    expect(layout.width).toBeGreaterThan(0)
    expect(layout.height).toBeGreaterThan(0)
    expect(layout.viewBox).toMatch(/^0 0 \d+ \d+$/)
    expect(layout.labels).toEqual([])
    expect(layout.spokes).toEqual([])
    expect(layout.dataPoints).toBe('')
    // 环数与 n 解耦：组件的 polygon 计数不变量依赖它
    expect(layout.rings).toHaveLength(RADAR_RING_LEVELS.length)
  })
})

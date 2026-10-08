// @vitest-environment jsdom
/**
 * 共享画布装配（§13 W1）的自带判据。
 *
 * ## 为什么这些判据必须存在
 * `IsochroneSnapshot` 收一之前**零判据**（全仓 grep 只命中定义行）——新能力若长在无人守的件上，
 * 下一次改动就只能靠真人看出来。本文件钉的四件事，每一条都对应一把会真的踩到的刀：
 *
 *  ① 四族的节点由载荷派生、POI 坐标逐位取自 `lcSnapshotPoiLayer`（装配不许重算点）；
 *  ② 取色只剩**一份**口径：`drawOuterFirst` 只改绘制顺序，不许改「哪一档配哪个色」；
 *  ③ 确定性：同一入参连渲染两次逐字相同（装配里若有墙钟/随机，两档会给出一张不同的图）；
 *  ④ 归属边界：实例申报（`data-lc-mode`／`data-lc-layers`／降级角标）与 accessible name
 *     **留在两档调用方**，装配不许搬 —— 搬进来报告页的实例计数与逐层申报判据会同时错位。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  LcCanvasBackdrop,
  LcIsochroneBands,
  LcPoiDots,
  LcSceneCenterMark,
} from '../components/lifecircle/LcSvgCanvas'
import { LC_CANVAS, LC_ISO_COLORS, lcSnapshotPoiLayer, poiRenderSet } from '../lib/livingCircle'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { LcSnapshotPoiDot } from '../lib/livingCircle'
import type { LngLat, LivingCircleReport } from '../types'

const lc = (getLivingCircleReportMock('lc-kaili-ev2') as unknown as { living_circle: LivingCircleReport })
  .living_circle
const CENTER = lc.scene.center as LngLat
const set = poiRenderSet(lc.poi.points)
const DOTS: LcSnapshotPoiDot[] = lcSnapshotPoiLayer(CENTER, set.reps, Number.POSITIVE_INFINITY, set.counts)

/** 装配只产 `<svg>` 以内的图元 ⇒ 测试也照这个契约，自己套一层**裸** svg（不带 role/aria-label，
 *  否则下面的归属断言会量到测试套自身）。 */
const draw = (node: React.ReactNode) => render(
  <svg viewBox={`0 0 ${LC_CANVAS.W} ${LC_CANVAS.H}`}>{node}</svg>,
).container

const allFour = (dots: LcSnapshotPoiDot[]) => draw(
  <>
    <LcCanvasBackdrop />
    <LcIsochroneBands center={CENTER} zones={lc.isochrones} />
    <LcPoiDots dots={dots} r={5} strokeWidth={1.2} />
    <LcSceneCenterMark center={CENTER} name={lc.scene.name} />
  </>,
)

/** 期望的「分钟档＝色」配对：取色按**载荷原序**取模，这正是收成一份之后唯一剩下的口径。 */
const MINUTE_BANDS = lc.isochrones.map((z, i) =>
  `${z.minutes} min=${LC_ISO_COLORS[i % LC_ISO_COLORS.length]?.fill}`)

afterEach(cleanup)

describe('LcSvgCanvas · 四族收成一份', () => {
  it('前置自证：样区有等时圈族与真实点位（否则下面的计数全是空过）', () => {
    expect(lc.isochrones.length).toBeGreaterThanOrEqual(2)
    expect(DOTS.length).toBeGreaterThan(0)
  })

  it('节点由载荷派生：底 1 格 ＋ 网格 10 线 ＋ 每圈一带 ＋ 每点一圆 ＋ 中心两圆', () => {
    const c = allFour(DOTS)
    expect(c.querySelectorAll('rect').length, '底 rect 应当恰一枚').toBe(1)
    expect(c.querySelectorAll('line').length, '5 竖 ＋ 5 横参照网格').toBe(10)
    expect(c.querySelectorAll('polygon').length).toBe(lc.isochrones.length)
    // 文本＝每圈一枚右端分钟标签 ＋ 中心那枚社区名
    expect([...c.querySelectorAll('text')].map((t) => t.textContent)).toEqual([
      ...lc.isochrones.map((z) => `${z.minutes} min`),
      lc.scene.name,
    ])
    expect(c.querySelectorAll('circle').length).toBe(DOTS.length + 2)
  })

  it('POI 坐标逐位取自 `lcSnapshotPoiLayer`，装配不重算点（第二套投影就是分叉的起点）', () => {
    const circles = [...allFour(DOTS).querySelectorAll('circle')]
    const dotCircles = circles.slice(0, DOTS.length)
    dotCircles.forEach((el, i) => {
      expect(el.getAttribute('cx'), `第 ${i} 个点位 x 应由共享投影层给`).toBe(String(DOTS[i].cx))
      expect(el.getAttribute('cy'), `第 ${i} 个点位 y 应由共享投影层给`).toBe(String(DOTS[i].cy))
      expect(el.getAttribute('fill')).toBe(DOTS[i].fill)
    })
    expect(dotCircles.length, '装配不许自己再补点').toBe(DOTS.length)
  })

  it('取色只剩一份口径：`drawOuterFirst` 只改绘制顺序，色-分钟配对逐位不变', () => {
    const asListed = [...allFour(DOTS).querySelectorAll('g')]
      .map((g) => `${g.querySelector('text')?.textContent}=${g.querySelector('polygon')?.getAttribute('fill')}`)
      .filter((s) => s.includes(' min='))
    const outerFirst = [...draw(
      <LcIsochroneBands center={CENTER} zones={lc.isochrones} drawOuterFirst />,
    ).querySelectorAll('g')]
      .map((g) => `${g.querySelector('text')?.textContent}=${g.querySelector('polygon')?.getAttribute('fill')}`)
      .filter((s) => s.includes(' min='))
    expect(MINUTE_BANDS.length).toBe(lc.isochrones.length)
    expect(asListed, '原序绘制应当按载荷原序配色').toEqual(MINUTE_BANDS)
    expect(outerFirst, '倒序绘制只该反转顺序，不该换色').toEqual([...MINUTE_BANDS].reverse())
  })

  it('空点集 ⇒ 只少 POI 那一族，其余三族一字不动（结构层的在场只由入参决定）', () => {
    const full = allFour(DOTS)
    const bare = allFour([])
    expect(bare.querySelectorAll('circle').length, '没有点位就不该画点').toBe(2)
    for (const sel of ['rect', 'line', 'polygon', 'text'] as const) {
      expect(bare.querySelectorAll(sel).length, `${sel} 这一族不该被点位带着变`)
        .toBe(full.querySelectorAll(sel).length)
    }
  })

  it('确定性：同一入参连渲染两次逐字相同（装配里不许有墙钟、随机或进程内可变态）', () => {
    const once = allFour(DOTS).innerHTML
    const twice = allFour(DOTS).innerHTML
    expect(twice, '两次渲染不同 ⇒ 分享链接、截图与审计对账会各自看到一张不同的图').toBe(once)
  })

  it('归属边界：装配不申报实例、不命名图片 —— 那些留在两档调用方', () => {
    const c = allFour(DOTS)
    expect(c.querySelector('[data-lc-mode]'), '模式申报属于"一个 LcMap 实例"，搬进来会抬高报告页的实例计数').toBeNull()
    expect(c.querySelector('[data-lc-layers]'), '逐层申报走 lcLayers 那一份名册，装配不自建第二份').toBeNull()
    expect(c.querySelectorAll('[role], [aria-label]').length, 'role 与 accessible name 挂在调用方的 svg 上')
      .toBe(0)
    expect(c.textContent, '降级角标是 LcMap 的申报，不是画布图元').not.toContain('地图降级')

    const src = readFileSync(join(process.cwd(), 'src', 'components', 'lifecircle', 'LcSvgCanvas.tsx'), 'utf8')
    for (const label of ['生活圈等时圈画布（降级）', '等时圈快照']) {
      expect(src, `装配硬编码了调用方的 accessible name：${label}`).not.toContain(label)
    }
  })
})

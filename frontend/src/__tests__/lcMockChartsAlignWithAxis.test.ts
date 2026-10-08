// @vitest-environment jsdom
/**
 * 演示态（mock）条形图的**值与行标签必须成对**（nar-3 发现并修掉的既有缺陷，留成永久闸）。
 *
 * 上一笔把后端 `_chart_coverage` 镜像到 `livingCircleReports.ts` 时，`data` 走正序、
 * `yAxis.data` 走逆序 —— 横向条形图是"从下往上"排的，两侧不同序就意味着每根条都挂到了
 * 错的类目行上：图上看着"医疗 100%"那一行，其实是政务那档的数。真实态（后端）两处都逆序，
 * 所以这个错只在演示态出现，也正是"两处实现"要付的税。
 *
 * 这条判据不比对后端（那是另一族镜像判据的事），只问一个更基本的事实：
 * **一张图自己的轴和自己的数据对不对得上**。它对任何一份载荷都必须成立。
 */
import { describe, it, expect } from 'vitest'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import { LC_CAT_COLOR } from '../lib/livingCircle'
import type { LivingCircleReport, Report } from '../types'

type Item = number | string | { value?: number, itemStyle?: { color?: string } }

const pairs = (option: { yAxis?: { data?: string[] }, series?: { data?: Item[] }[] }) => {
  const labels = option.yAxis?.data ?? []
  const data = option.series?.[0]?.data ?? []
  return labels.map((label, i) => {
    const raw = data[i]
    const value = typeof raw === 'object' && raw !== null ? raw.value : (raw as number)
    const color = typeof raw === 'object' && raw !== null ? raw.itemStyle?.color : undefined
    return { label, value, color }
  })
}

describe('演示态条形图：值与行标签同源', () => {
  for (const sceneId of ['lc-kaili', 'lc-kaili-ev2', 'lc-beijing-jinsong']) {
    it(`${sceneId}：覆盖度图每一行的值就是该类目的值（不同序即错配）`, () => {
      const report = getLivingCircleReportMock(sceneId) as unknown as Report
      const lc = (report as unknown as { living_circle: LivingCircleReport }).living_circle
      const bars = lc.scores.bars ?? []
      expect(bars.length, '这份样区没有八类序列 ⇒ 本条失去对象').toBeGreaterThan(2)

      const coverage = report.sections
        .flatMap((s) => s.charts ?? [])
        .find((c) => (c.title ?? '').includes('覆盖度'))
      expect(coverage, '找不到覆盖度图').toBeTruthy()

      const got = pairs(coverage!.option as never)
      // 横向条形图从下往上排 ⇒ 轴与数据都应是 bars 的逆序
      expect(got.map((p) => p.label)).toEqual(bars.map((b) => b.label).reverse())
      expect(got.map((p) => p.value)).toEqual(bars.map((b) => b.value).reverse())
      // 逐条取色只许来自那张表：色对不上就是拿颜色当类目的第二份权威
      expect(got.map((p) => p.color)).toEqual(bars.map((b) => LC_CAT_COLOR[b.category]).reverse())
    })

    it(`${sceneId}：专题章位置图的实色条，落在本章类目的那一行上`, () => {
      const report = getLivingCircleReportMock(sceneId) as unknown as Report
      const lc = (report as unknown as { living_circle: LivingCircleReport }).living_circle
      const bars = lc.scores.bars ?? []
      const labelsOf = (cats: string[]) => bars.filter((b) => cats.includes(b.category)).map((b) => b.label)
      let checked = 0
      for (const sid of ['medical', 'education', 'market', 'elderly']) {
        const chart = (report.sections.find((s) => s.id === sid)?.charts ?? [])
          .find((c) => c.chart_id === `chart-${sid}-coverage`)
        if (!chart) continue
        // `ChartSpec.option` 是无结构的 `Record<string, unknown>` ⇒ 这里按条形图的实际形状收窄一次，
        // 收窄只发生在判据侧（不改生产类型），读不到就该红而不是静默跳过。
        const opt = chart.option as unknown as {
          yAxis?: { data?: string[] }
          series?: { data?: Array<{ value?: number, itemStyle?: { opacity?: number } }> }[]
        }
        const rows = opt.yAxis?.data ?? []
        const data = opt.series?.[0]?.data ?? []
        expect(rows.length, `${sid} 章位置图读不到行标签 ⇒ 收窄失效，本条会空过`).toBeGreaterThan(0)
        const solid = rows.filter((_, i) => data[i]?.itemStyle?.opacity === 1)
        const chapter = sid === 'market' ? ['market', 'shopping'] : [sid]
        expect(solid.sort(), `${sid} 章的实色行应是本章类目的标签`).toEqual(labelsOf(chapter).sort())
        checked += 1
      }
      expect(checked, '四章位置图一张都没扫到 ⇒ 本条恒真').toBeGreaterThan(0)
    })
  }
})

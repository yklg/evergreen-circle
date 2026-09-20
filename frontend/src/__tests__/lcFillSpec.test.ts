/**
 * lcFillSpec 回归守卫：BMapGL 的 Polygon 忽略 fillColor 里的 alpha，
 * 只认 fillOpacity —— 若渲染层又把 rgba 直接塞回 fillColor/fillOpacity:1，
 * 灰区会变成实心 #787878、四级等时圈会压成一块实心绿（实测 2026-09-19 现场事故）。
 */
import { describe, expect, it } from 'vitest'
import { LC_CAT_COLOR, LC_ISO_COLORS, lcFillSpec } from '../lib/livingCircle'

describe('lcFillSpec（rgba 契约色 → BMapGL 实色 + fillOpacity）', () => {
  it('拆分 rgba：透明度交给 fillOpacity，颜色转实色 hex', () => {
    expect(lcFillSpec('rgba(120,120,120,0.16)')).toEqual({ color: '#787878', opacity: 0.16 })
  })

  it('等时圈四级色阶解析为 0.55 / 0.34 / 0.20 / 0.10（内深外浅）', () => {
    expect(LC_ISO_COLORS.map((c) => lcFillSpec(c.fill).opacity)).toEqual([0.55, 0.34, 0.2, 0.1])
  })

  it('无 alpha 的 rgb() 走 fallbackOpacity（不误判为 0 透明）', () => {
    expect(lcFillSpec('rgb(12,34,56)')).toEqual({ color: '#0c2238', opacity: 1 })
    expect(lcFillSpec('rgb(12,34,56)', 0.7)).toEqual({ color: '#0c2238', opacity: 0.7 })
  })

  it('已是 hex / 具名色时原样透传（兼容 LC_CAT_COLOR 等非 rgba 取值）', () => {
    expect(lcFillSpec('#1677ff')).toEqual({ color: '#1677ff', opacity: 1 })
    expect(LC_CAT_COLOR.market === undefined || lcFillSpec(LC_CAT_COLOR.market).color).toBeTruthy()
  })

  it('透明度必须真落到 fillOpacity（BMapGL 不认 fillColor 的 alpha）', () => {
    for (const c of LC_ISO_COLORS) {
      const spec = lcFillSpec(c.fill)
      expect(spec.color).toMatch(/^#[0-9a-f]{6}$/)
      expect(spec.opacity).toBeLessThan(1)
    }
  })
})

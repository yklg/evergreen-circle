/** N6 分布图投影（纯函数，可单测）：真实经纬度 → 海报画布坐标。
 *
 * 分层约定：本文件只做几何投影，不含任何目的地模板/装饰（那属数据资产层
 * spotSketchTemplates.ts）；组件内不得散落 per-destination 硬编码。
 * 退化判据（评审④）：点数<2 / 经纬零方差 → 居中散点回退；输出永不含 NaN。 */

export type GeoPoint = { id: string; lat: number; lng: number }
export type ProjectedPoint = { id: string; x: number; y: number }

/** 只保留坐标为有限数值的点（未 matched 的 None 坐标在此之前已被过滤）。 */
export function finitePoints(points: readonly GeoPoint[]): GeoPoint[] {
  return (points || []).filter(
    (p) => p && p.id && Number.isFinite(p.lat) && Number.isFinite(p.lng),
  )
}

export function projectPoints(
  points: readonly GeoPoint[],
  width: number,
  height: number,
  pad = 48,
): ProjectedPoint[] {
  const pts = finitePoints(points)
  if (pts.length === 0) return []
  const cx = width / 2
  const cy = height / 2
  if (pts.length === 1) return [{ id: pts[0].id, x: cx, y: cy }]

  const lngs = pts.map((p) => p.lng)
  const lats = pts.map((p) => p.lat)
  const [lngMin, lngMax] = [Math.min(...lngs), Math.max(...lngs)]
  const [latMin, latMax] = [Math.min(...lats), Math.max(...lats)]
  const spanLng = lngMax - lngMin
  const spanLat = latMax - latMin
  const inside = spanLng > 0 && spanLat > 0

  // 退化轴/全退化：居中圆周散点（确定性，索引定角度）；未退化的轴仍按真实值线性投影
  if (!inside) {
    const r = Math.min(width, height) / 4
    return pts.map((p, i) => {
      const a = (2 * Math.PI * i) / pts.length - Math.PI / 2
      let x = cx + r * Math.cos(a)
      let y = cy + r * Math.sin(a)
      if (spanLng > 0) x = pad + ((p.lng - lngMin) / spanLng) * (width - 2 * pad)
      if (spanLat > 0) y = height - pad - ((p.lat - latMin) / spanLat) * (height - 2 * pad)
      return { id: p.id, x, y }
    })
  }

  return pts.map((p) => ({
    id: p.id,
    x: pad + ((p.lng - lngMin) / spanLng) * (width - 2 * pad),
    y: height - pad - ((p.lat - latMin) / spanLat) * (height - 2 * pad),
  }))
}

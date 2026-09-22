import { useEffect, useMemo, useRef, useState } from 'react'

/** 地图上可展示的景点行（引用 spots 阶段冻结实体；仅坐标齐且 matched!==false 才上图）。 */
export type MapSpot = {
  spot_id: string
  name: string
  area?: string
  score?: number
  matched?: boolean
  lat?: number | null
  lng?: number | null
}

type BMapNS = any

declare global {
  interface Window {
    BMapGL?: BMapNS
    __verdaBMapPromise?: Promise<BMapNS>
    __verdaBMapReady?: () => void
  }
}

/** JSAPI 单例加载（GL 版）：已就绪直接复用；失败 resolve(null)，由调用方出占位。 */
export function loadBMap(ak: string): Promise<BMapNS | null> {
  if (typeof window === 'undefined') return Promise.resolve(null)
  if (window.BMapGL) return Promise.resolve(window.BMapGL)
  if (!window.__verdaBMapPromise) {
    window.__verdaBMapPromise = new Promise((resolve) => {
      window.__verdaBMapReady = () => resolve(window.BMapGL ?? null)
      const s = document.createElement('script')
      s.src = `https://api.map.baidu.com/api?v=1.0&type=webgl&ak=${encodeURIComponent(ak)}&callback=__verdaBMapReady`
      s.onerror = () => resolve(null)
      document.head.appendChild(s)
    })
  }
  return window.__verdaBMapPromise
}

const PLACEHOLDER = '数据源暂不可用：地图需要配置 VITE_BAIDU_AK（百度服务端 AK，并配 referer 白名单）'
const NO_COORD = '榜单景点暂无可用坐标（位置解析未命中），仅保留评分表'

/** AK 是否已配置：外层组合件据此决定「地图整块缺位（仅时间线/条图）」还是「出地图」。 */
export function hasBMapAk(): boolean {
  return !!((import.meta.env.VITE_BAIDU_AK as string | undefined) ?? '')
}

/** 景点位置分布图：marker 弹窗小卡 + 与评分榜双向联动（selected spot_id 由父组件托管）。
 * trail=true 时按传入顺序把已定位景点串成 polyline（N4 行程折线模式）。 */
export function BMapBlock({
  spots,
  selectedId,
  onSelect,
  height = 380,
  trail = false,
  caption,
}: {
  spots: MapSpot[]
  selectedId?: string | null
  onSelect?: (spotId: string | null) => void
  height?: number
  trail?: boolean
  caption?: string
}) {
  const ak = (import.meta.env.VITE_BAIDU_AK as string | undefined) ?? ''
  const holderRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<any>(null)
  const markersRef = useRef<Map<string, any>>(new Map())
  const [state, setState] = useState<'idle' | 'ready' | 'unavailable'>('idle')

  const mappable = useMemo(
    () => spots.filter((s) => s.spot_id && s.matched !== false && typeof s.lat === 'number' && typeof s.lng === 'number'),
    [spots],
  )
  // 同一批实体只初始化一次（坐标集变化视为新地图任务）
  const entityKey = useMemo(() => mappable.map((s) => s.spot_id).join('|'), [mappable])
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect

  useEffect(() => {
    if (!ak || !mappable.length) return
    let disposed = false
    loadBMap(ak).then((B) => {
      if (disposed || !B || !holderRef.current) {
        if (!disposed) setState('unavailable')
        return
      }
      try {
        const first = mappable[0]
        const center = new B.Point(first.lng as number, first.lat as number)
        const map = new B.Map(holderRef.current)
        map.centerAndZoom(center, 12)
        map.enableScrollWheelZoom?.()
        const markers = new Map<string, any>()
        for (const s of mappable) {
          const pt = new B.Point(s.lng as number, s.lat as number)
          const mk = new B.Marker(pt, { title: s.name })
          mk.addEventListener('click', () => {
            selectRef.current?.(s.spot_id)
            try {
              const info = new B.InfoWindow(
                `<div style="font-size:12px;line-height:1.6"><b>${s.name}</b><br/>` +
                `${s.area ? `${s.area}<br/>` : ''}${s.score != null ? `综合分 ${s.score}` : ''}</div>`,
              )
              map.openInfoWindow(info, pt)
            } catch { /* 弹窗失败不影响选中与打点 */ }
          })
          map.addOverlay(mk)
          markers.set(s.spot_id, mk)
        }
        if (trail && mappable.length > 1) {
          try {
            const line = new B.Polyline(
              mappable.map((s) => new B.Point(s.lng as number, s.lat as number)),
              { strokeColor: '#7C9885', strokeWeight: 4, strokeOpacity: 0.85 },
            )
            map.addOverlay(line)
          } catch { /* 折线失败不影响打点与联动 */ }
        }
        mapRef.current = map
        markersRef.current = markers
        setState('ready')
      } catch {
        if (!disposed) setState('unavailable')
      }
    })
    return () => {
      disposed = true
      mapRef.current = null
      markersRef.current = new Map()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ak, entityKey])

  // 表→图：选中景点平移定位（未匹配实体无 marker，自然不高亮）
  useEffect(() => {
    if (state !== 'ready' || !selectedId) return
    const map = mapRef.current
    const mk = markersRef.current.get(selectedId)
    if (map && mk) map.panTo(mk.getPosition())
  }, [selectedId, state])

  if (!ak || !mappable.length) {
    return (
      <div
        className="grid place-items-center rounded-card border border-dashed border-line/70 bg-bg text-tag text-ink-3"
        style={{ height: 120 }}
        data-map-placeholder
      >
        {ak ? NO_COORD : PLACEHOLDER}
      </div>
    )
  }
  return (
    <div className="rounded-card border border-line/60 bg-white p-2 shadow-card">
      <div className="px-1 pb-1.5 text-tag text-ink-3">
        {caption ?? `景点位置分布 · ${mappable.length} 个已定位（与评分榜行联动）`}
      </div>
      {state === 'unavailable' ? (
        <div className="grid place-items-center rounded-card bg-bg text-tag text-ink-3" style={{ height }} data-map-placeholder>
          地图数据源暂不可用（JSAPI 加载失败）
        </div>
      ) : (
        <div ref={holderRef} style={{ height }} data-bmap-holder />
      )}
    </div>
  )
}

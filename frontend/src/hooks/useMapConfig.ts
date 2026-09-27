/**
 * 地图配置（浏览器 AK + 底图 styleId）的组件侧唯一入口。
 *
 * 为什么要有这一层：AK 的真值源在后端 `map-config`（`BAIDU_BROWSER_AK`），地图页 `LcMap`
 * 一直走它；报告侧的 `BMapBlock` 曾各读一份构建期 `VITE_BAIDU_AK`（全项目无人配置），
 * 于是同一份数据在地图页有图、在报告里只有占位灰框。现在两侧同源。
 *
 * 缓存只记「拿到的那一次」：后端不可达时不固化失败结果，侧边栏从「演示」切回「真实联调」后，
 * 下一次挂载仍能取到 AK。
 */
import { useEffect, useState } from 'react'
import { getMapConfig, type LcMapConfig } from '../lib/bmap'

export type MapConfigState = {
  /** pending=配置在途（不挂载、不闪空框）；absent=拿不到 AK（调用方出降级位） */
  status: 'pending' | 'ready' | 'absent'
  ak: string
  styleId: string
}

let cached: LcMapConfig | null = null

function toState(cfg: LcMapConfig): MapConfigState {
  return cfg.browserAk
    ? { status: 'ready', ak: cfg.browserAk, styleId: cfg.mapStyleId }
    : { status: 'absent', ak: '', styleId: cfg.mapStyleId }
}

export function useMapConfig(): MapConfigState {
  const [state, setState] = useState<MapConfigState>(() =>
    cached ? toState(cached) : { status: 'pending', ak: '', styleId: '' },
  )
  useEffect(() => {
    if (cached) return
    let disposed = false
    getMapConfig().then((cfg) => {
      if (disposed) return
      if (cfg.browserAk) cached = cfg
      setState(toState(cfg))
    })
    return () => {
      disposed = true
    }
  }, [])
  return state
}

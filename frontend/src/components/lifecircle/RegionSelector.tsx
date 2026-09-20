/**
 * 省市区三级联动选择器（D1/T6）——工作台与地图页共用。
 *
 * 数据：GET /api/life-circle/regions（内置全国区划树，无 AK 依赖）。
 * 行为：省 → 市 → 区 逐级联动（未选择上级时下级禁用），
 *       详细地址可选；任一变化即回填「省+市+区+详细」到输入位。
 * 契约：只拼名称，坐标由后端统一解析（live geocoding → 离线区划），前端不携带。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { MapPin, X } from 'lucide-react'
import type { RegionProvince } from '../../types'
import { fetchLifeCircleRegions } from '../../lib/api'

export interface RegionSelectorProps {
  /** 回填拼好的地址串（省+市+区+详细） */
  onPick: (assembled: string) => void
  /** 收起选择器 */
  onClose: () => void
  /** 是否可见（懒加载：首次展开才拉区划树） */
  visible: boolean
}

const SELECT_CLS =
  'h-9 flex-1 min-w-0 rounded-btn border border-line bg-card px-2.5 text-aux text-ink outline-none focus:border-primary disabled:opacity-45'

export default function RegionSelector({ onPick, onClose, visible }: RegionSelectorProps) {
  const [tree, setTree] = useState<RegionProvince[]>([])
  const [err, setErr] = useState('')
  const [prov, setProv] = useState('')
  const [city, setCity] = useState('')
  const [dist, setDist] = useState('')
  const [detail, setDetail] = useState('')
  const fetched = useRef(false)

  useEffect(() => {
    if (!visible || fetched.current) return
    fetched.current = true
    fetchLifeCircleRegions()
      .then((r) => {
        setTree(r)
        if (r.length) setProv(r[0].province)
      })
      .catch(() => setErr('区划数据加载失败，可继续使用自由输入'))
  }, [visible])

  const cityList = useMemo(
    () => tree.find((p) => p.province === prov)?.cities ?? [],
    [tree, prov],
  )
  // 直辖市（市名=省名）自动视同已选市，无需状态回写（避免 effect 级联渲染）
  const effectiveCity = city || (cityList.length === 1 && cityList[0].name === prov ? cityList[0].name : '')
  const distList = useMemo(
    () => cityList.find((c) => c.name === effectiveCity)?.districts ?? [],
    [cityList, effectiveCity],
  )

  // 联动回填：区已选（或直辖市/无区县直接上市名）时拼串
  useEffect(() => {
    if (!prov) return
    const parts = [prov]
    if (effectiveCity && effectiveCity !== prov) parts.push(effectiveCity) // 直辖市下市名=省名，避免重复
    if (dist) parts.push(dist)
    if (detail.trim()) parts.push(detail.trim())
    if (parts.length > 1) onPick(parts.join(''))
  }, [prov, effectiveCity, dist, detail]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-2 rounded-btn border border-line bg-bg/80 p-2.5">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1 text-tag text-ink-2">
          <MapPin size={13} className="text-primary" /> 从行政区划选择（离线可定位）
        </span>
        <button
          onClick={onClose}
          title="收起区划选择"
          className="grid h-6 w-6 place-items-center rounded-chip text-ink-3 hover:bg-primary-tint"
        >
          <X size={13} />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={prov}
          onChange={(e) => {
            setProv(e.target.value)
            setCity('')
            setDist('')
          }}
          className={SELECT_CLS}
          aria-label="选择省"
        >
          {tree.map((p) => (
            <option key={p.province} value={p.province}>
              {p.province}
            </option>
          ))}
        </select>
        <select
          value={effectiveCity}
          onChange={(e) => {
            setCity(e.target.value)
            setDist('')
          }}
          disabled={!cityList.length}
          className={SELECT_CLS}
          aria-label="选择市"
        >
          {!cityList.length ? (
            <option value="">（无下级）</option>
          ) : (
            <>
              <option value="">请选择市</option>
              {cityList.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </>
          )}
        </select>
        <select
          value={dist}
          onChange={(e) => setDist(e.target.value)}
          disabled={!distList.length}
          className={SELECT_CLS}
          aria-label="选择区县"
        >
          {!distList.length ? (
            <option value="">（无下级）</option>
          ) : (
            <>
              <option value="">请选择区县</option>
              {distList.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </>
          )}
        </select>
        <input
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          placeholder="详细地址（可选，如：陆家嘴街道）"
          className="h-9 min-w-[180px] flex-1 rounded-btn border border-line bg-card px-2.5 text-aux text-ink outline-none placeholder:text-ink-3 focus:border-primary"
        />
      </div>
      {err && <div className="text-tag text-risk">{err}</div>}
    </div>
  )
}

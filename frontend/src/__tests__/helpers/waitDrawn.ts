import { waitFor } from '@testing-library/react'
import { expect } from 'vitest'

import { instances } from './bmapGLFake'

/**
 * live 侧「这一帧画完了没有」的唯一等待出口（task 23）。
 *
 * 为什么需要它：`LcMap` 的 live 分支是先建地图、再由后续 effect 逐个 `new bmap.Polygon/Circle/Marker`
 * 挂覆盖物。各测试文件以前各抄一份等待，深浅还不一致 —— 只等 `maps.length > 0` 的那些，在 CPU 被抢时
 * 会按下标取到还没建出来的数组位置（`Cannot read properties of undefined`），或对着还没挂上监听的
 * 容器 `fireEvent`（红相是"状态没变"，看着像产品坏了）。10-07 台架实测：干净树三路并发全量 ×5，
 * 15 遍里红 6 遍，成员含 `lcHeatField`（`expected 'none' to be 'block'`）。
 *
 * 用法：把**用例真正要消费的数量**传进来（与它的下标同源），别传"大概几个"。
 * 预算沿用 RTL 的 `asyncUtilTimeout`（8s），它必须小于 `testTimeout`（30s）—— 见 `vitest.setup.ts`。
 */
export interface DrawnCounts {
  maps?: number
  markers?: number
  polys?: number
  polylines?: number
  circles?: number
}

type DrawnLists = { [K in keyof DrawnCounts]: unknown[] }

export async function waitDrawn(want: DrawnCounts, lists: Partial<DrawnLists> = instances): Promise<void> {
  await waitFor(() => {
    for (const [key, min] of Object.entries(want) as [keyof DrawnCounts, number][]) {
      const list = lists[key]
      expect(
        list?.length,
        `live 侧 ${key} 还没建够 ${min} 个（当前 ${list?.length ?? '该账本没接入'}）⇒ 现在下标或 fireEvent 会读到半成品`,
      ).toBeGreaterThanOrEqual(min)
    }
  })
}

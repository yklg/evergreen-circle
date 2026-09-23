/**
 * Canvas 2D 上下文计数 mock（延迟优化 C 的测试基建，G3 自研、零依赖）。
 *
 * jsdom 的 `canvas.getContext('2d')` 返回 null（无 canvas 引擎）→
 * `HeatFieldOverlay.draw()` 的防御性空检会让绘制路径永远不执行、fill 计数恒 0 ——
 * 测试无法区分「画了」与「没画」。本 mock 让 `getContext('2d')` 返回一个 Proxy：
 * 所有绘制方法调用（beginPath/arc/fill/clearRect/…）都被计数，属性写入（globalAlpha/
 * fillStyle/…）被透传存储。测试据此断言「draw() 真的把每个可达点画了出来」。
 *
 * 用法：`const calls = mockCanvasContext()`；`afterEach` 由测试文件 `vi.restoreAllMocks()` 还原。
 */
import { vi } from 'vitest'

export interface CanvasCallCounts {
  [method: string]: number
}

export function mockCanvasContext(): CanvasCallCounts {
  const calls: CanvasCallCounts = {}
  const ctx = new Proxy({} as Record<string, unknown>, {
    get(_target, prop) {
      if (prop === 'calls') return calls
      const key = String(prop)
      return (..._args: unknown[]) => {
        calls[key] = (calls[key] ?? 0) + 1
      }
    },
    set(target, prop, value) {
      target[String(prop)] = value
      return true
    },
  })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as unknown as CanvasRenderingContext2D)
  return calls
}

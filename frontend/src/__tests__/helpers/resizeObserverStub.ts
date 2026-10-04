/**
 * ResizeObserver 的**可触发**替身。
 *
 * ## 为什么替身要长这样
 *
 * jsdom 有意不做布局模拟 ⇒ 没有 ResizeObserver。`vitest.setup.ts:57-68` 原先装的是一个
 * 纯 no-op 桩（只为 `VWordCloud` 构造时不抛 ReferenceError）。no-op 的代价是隐蔽的：
 * 任何「容器尺寸变化 ⇒ 做某事」的真链路在测试里都会**安静地什么都不做**，
 * 而套件照样全绿 —— `LcMap` 的 resize 通道正是这条形状（`LcMap.tsx:516-525`）。
 *
 * 所以这里保持与旧桩**同样的无害语义**（observe/unobserve/disconnect 不自动回调），
 * 只多两件事：① 记账谁观察了哪个元素；② 让测试自己 `fireResize(el)` 决定何时回调。
 * 尺寸变化在浏览器里是环境事件，不由被测代码触发 —— 手动 fire 才是正确的注入点。
 *
 * ## 效力上限（防"测试全绿＝全对"）
 *
 * 本替身只回答「订阅装上了吗、回调进来后代码做了什么」。
 * 它答不了「浏览器到底会不会以这个尺寸回调、SDK 重算后中心是否仍对」——
 * 那只有真浏览器一层能答（见 生活圈-布局改动测试覆盖评估-v1.md 的 TC-21/TC-22）。
 */

type ResizeObserverEntryish = { target: Element; contentRect: DOMRectReadOnly }
type ResizeCallback = (entries: ResizeObserverEntryish[], observer: ResizeObserverStub) => void

/** 存活的观察器；`disconnect()` 或不再生效时移出，避免跨用例串台。 */
const live = new Set<ResizeObserverStub>()

/** 构造次数 —— 用来钉「降级路径不该装这条通道」这类反向判据。 */
export const roStats = { created: 0 }

export class ResizeObserverStub {
  readonly targets = new Set<Element>()
  readonly cb: ResizeCallback

  constructor(cb: ResizeCallback) {
    this.cb = cb
    live.add(this)
    roStats.created += 1
  }

  observe(target: Element): void {
    this.targets.add(target)
  }

  unobserve(target: Element): void {
    this.targets.delete(target)
  }

  disconnect(): void {
    this.targets.clear()
    live.delete(this)
  }
}

/** 被观察过的元素总数（含已 disconnect 的），用于反向判据。 */
export function observedElements(): Element[] {
  return [...live].flatMap((o) => [...o.targets])
}

/** 模拟一次容器尺寸变化：只对正在观察该元素的存活观察器派发回调。 */
export function fireResize(target: Element): number {
  let fired = 0
  for (const o of [...live]) {
    if (!o.targets.has(target)) continue
    o.cb([{ target, contentRect: {} as DOMRectReadOnly }], o)
    fired += 1
  }
  return fired
}

/** 用例在 `beforeEach` 清空，防上一支的观察器漏进这一支。 */
export function resetResizeObservers(): void {
  for (const o of [...live]) o.disconnect()
  live.clear()
  roStats.created = 0
}

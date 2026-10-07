// vitest.setup.ts — jsdom 环境下 localStorage 确定性补水
//
// 背景：Node ≥22.4 引入实验性全局 Web Storage（启动时未提供 --localstorage-file 时
// 全局 localStorage 为 undefined）；vitest 2.1.x 的 jsdom environment 经 populateGlobal
// 将这一 undefined 快照进 window（'localStorage' in window === true 但取值 undefined），
// jsdom ≥26 的惰性 getter 又不会自动补值，导致 jsdom 测试访问 localStorage 抛
// TypeError: Cannot read properties of undefined (reading 'clear')。
//
// 这是第三方依赖组合（Node/jsdom/vitest）的环境缺陷，非被测代码缺陷。
// 在测试边界注入符合 Web Storage 语义的内存实现，使所有 jsdom 测试获得确定的
// localStorage（setItem/getItem/removeItem/clear/key/length），不修改任何生产代码。

import { configure } from '@testing-library/react'
import { ResizeObserverStub } from './src/__tests__/helpers/resizeObserverStub'

function createMemoryStorage(): Storage {
  const store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear(): void {
      store.clear()
    },
    getItem(key: string): string | null {
      return store.has(key) ? (store.get(key) as string) : null
    },
    key(index: number): string | null {
      return [...store.keys()][index] ?? null
    },
    removeItem(key: string): void {
      store.delete(key)
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value))
    },
    // Storage 接口要求的未用项
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    [Symbol.toStringTag]: 'Storage' as any,
  } as Storage
}

if (
  typeof window !== 'undefined' &&
  typeof (window as { localStorage?: unknown }).localStorage === 'undefined'
) {
  const storage = createMemoryStorage()
  try {
    Object.defineProperty(window, 'localStorage', {
      value: storage,
      writable: true,
      configurable: true,
    })
  } catch {
    // jsdom 若以不可重配置 getter 暴露，则退回全局兜底
  }
  ;(globalThis as { localStorage?: unknown }).localStorage = storage
}

// jsdom 未实现 ResizeObserver（浏览器专有 API，jsdom 有意不做布局模拟）。
// VWordCloud 用 ResizeObserver 测容器宽（组件侧对宽度已有 640 回退），但构造函数
// 本身在 jsdom 缺失会抛 ReferenceError。此处补最小桩使测试环境不炸，不改生产代码。
//
// 桩从「纯 no-op」升级为「记账 + 可由测试触发」：no-op 会让任何
// 「容器尺寸变化 ⇒ 做某事」的链路在测试里安静空转（套件照绿却什么都没验）。
// 语义保持不变 —— 不自动回调，何时回调由用例 `fireResize(el)` 决定。
// 手法与本文件顶部的 localStorage 补水同源：补的是环境缺口，不是被测行为。
if (typeof window !== 'undefined' && typeof window.ResizeObserver === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).ResizeObserver = ResizeObserverStub
}

// jsdom 未实现 Element.prototype.scrollIntoView（W3C 规范外的浏览器专有滚动 API，
// jsdom 有意不做布局/滚动模拟）。生产代码在滚动到底部时调用它（VAgentStream、
// VTracePanel），调用点已有 ?. 兜底但拿不到方法本身就会抛 TypeError。
// 这同样是 jsdom 环境缺口而非被测代码缺陷：注入 no-op 桩，不修改生产代码。
if (typeof window !== 'undefined' && typeof window.HTMLElement !== 'undefined') {
  if (typeof window.HTMLElement.prototype.scrollIntoView !== 'function') {
    window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
  }
}

// RTL 的 `waitFor` 默认只等 **1 秒**，而它等的是"异步 effect 把事实做出来"：一次 BMapGL 替身的
// boot 链（取 AK 的 promise + 若干次 setState 重渲染）在多 worker 并发、核数少的机器上真的可能超过 1s。
// 10-07 实测：同一份**干净树**并发跑两个全量，HEAD 与远端基线**各自红在同一条**
// （`lcIsoInteract` 的 live 族用例）—— 那条红量的是"谁恰好抢到 CPU"，不是被测代码。
//
// 这里放宽的是**等待上限**（多久之内必须出现），不是**断言强度**（出现的东西对不对）：
// 一条断言都没松。写在 setup 里是为了单点生效——live 族有十几个文件用 waitFor，逐文件加超时
// 就是给同一个环境问题造十几处副本。
//
// ⚠️ 8s 是刻意**小于** `vitest.config.ts` 的 `testTimeout`（30s）的：两个数相等时先被杀的是整个 test，
// 报出来只剩一句 `Test timed out in 5000ms`，RTL 那句「找不到 / 命中多个 + 当前 DOM」永远印不出来 ——
// 10-07 我第一版把两边都写成 5000 就踩了这个坑（8 路并发逼出的那次红完全看不出病因）。
// ⇒ 不变式：**asyncUtilTimeout < testTimeout**，让"等待超时"始终由 RTL 先报、带着 DOM 报。
configure({ asyncUtilTimeout: 8000 })
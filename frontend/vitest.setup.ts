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
if (typeof window !== 'undefined' && typeof window.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).ResizeObserver = ResizeObserverStub
}
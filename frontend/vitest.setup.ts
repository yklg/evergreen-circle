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

// jsdom 未实现 Element.prototype.scrollIntoView（W3C 规范外的浏览器专有滚动 API，
// jsdom 有意不做布局/滚动模拟）。生产代码在滚动到底部时调用它（VAgentStream、
// VTracePanel），调用点已有 ?. 兜底但拿不到方法本身就会抛 TypeError。
// 这同样是 jsdom 环境缺口而非被测代码缺陷：注入 no-op 桩，不修改生产代码。
if (typeof window !== 'undefined' && typeof window.HTMLElement !== 'undefined') {
  if (typeof window.HTMLElement.prototype.scrollIntoView !== 'function') {
    window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
  }
}

// jsdom 无 canvas 后端：getContext('2d') 返回 null。历史成因（echarts-wordcloud import 期
// 探测 2d 上下文）已随 E1 词云 DOM 化移除该依赖而消失；此处保留最小 2d 桩作为兜底——
// 任何第三方图表/图像库在测试内触碰 canvas 时不至于整批 import 崩。
// 仅补环境缺口：canvas 真实绘制不在 jsdom 内验证（浏览器实机验收项）。
if (typeof window !== 'undefined' && typeof window.HTMLCanvasElement !== 'undefined') {
  const origGetContext = window.HTMLCanvasElement.prototype.getContext
  window.HTMLCanvasElement.prototype.getContext = function (
    this: HTMLCanvasElement, type: string, ...rest: unknown[]
  ) {
    if (type !== '2d') {
      return (origGetContext as Function)?.apply(this, [type, ...rest]) ?? null
    }
    const canvas = this as unknown as { width: number; height: number }
    const noop = () => {}
    const makeImage = (w: number, h: number) => ({
      width: w, height: h, colorSpace: 'srgb',
      data: new Uint8ClampedArray(Math.max(4, w * h * 4)),
    })
    const ctx: Record<string, unknown> = {
      canvas,
      font: '16px sans-serif', fillStyle: '#000', strokeStyle: '#000',
      textAlign: 'start', textBaseline: 'alphabetic',
      globalAlpha: 1, globalCompositeOperation: 'source-over', imageSmoothingEnabled: true,
      measureText: (t: unknown) => ({ width: String(t ?? '').length * 8, actualBoundingBoxAscent: 8, actualBoundingBoxDescent: 2 }),
      getImageData: (_x: number, _y: number, w: number, h: number) => makeImage(w, h),
      createImageData: (a: unknown, b?: number) =>
        typeof a === 'object' && a !== null
          ? makeImage((a as { width: number }).width, (a as { height: number }).height)
          : makeImage(Number(a), Number(b)),
      putImageData: noop, fillText: noop, strokeText: noop, clearRect: noop,
      fillRect: noop, strokeRect: noop, beginPath: noop, closePath: noop,
      moveTo: noop, lineTo: noop, arc: noop, rect: noop, stroke: noop, fill: noop,
      save: noop, restore: noop, translate: noop, rotate: noop, scale: noop,
      setTransform: noop, transform: noop, drawImage: noop, clip: noop,
    }
    return ctx
  } as typeof window.HTMLCanvasElement.prototype.getContext
}
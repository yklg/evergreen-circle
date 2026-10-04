import { defineConfig } from '@playwright/test'

/**
 * 排版层的自动回归（评审 #10 的结案件）
 *
 * ## 为什么必须有真浏览器
 *
 * 本仓的单元/集成套件跑在 jsdom 上，而 jsdom **没有排版引擎**：`getBoundingClientRect`
 * 恒为 0×0，百分比高度、`grid` 的 stretch、滚动容器全都不成立。内置浏览器面板更糟一次——
 * 实测它 `requestAnimationFrame` 3.6 秒 0 帧（渲染步被停掉），那时"画布没跟随容器变高"
 * 这类观察**既不能证实也不能证伪**。所以像素层的主张只能在真浏览器里钉，这里就是那一层。
 *
 * ## 分工（别让两层互相冒充）
 *
 *  - `src/__tests__/lcStageStructure.test.tsx`：树形等式 —— 抽件有没有多包一层 DOM；
 *  - 本目录：真实几何 —— 滚不滚、图例在不在、点得到点不到、容器变了跟不跟。
 *
 * ## CI 注意
 *
 * `webServer` 会自己起 vite（本地复用已开的 5199）。地图那条跟随用例需要 AK/网络走 live 分支，
 * 拿不到时会自动落降级画布 —— 用例里显式 skip 并写明原因，不让网络状况伪装成功能回归。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5199',
    trace: 'off',
    video: 'off',
  },
  projects: [
    { name: 'desktop 1440×900', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'laptop 1280×720', use: { viewport: { width: 1280, height: 720 } } },
  ],
  webServer: {
    command: 'npm run dev -- --port 5199 --strictPort',
    url: 'http://localhost:5199',
    reuseExistingServer: true,
    timeout: 90_000,
  },
})

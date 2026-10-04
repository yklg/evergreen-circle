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
    { name: 'desktop 1440×900', use: { viewport: { width: 1440, height: 900 } }, testIgnore: /lifeCircleRunning/ },
    { name: 'laptop 1280×720', use: { viewport: { width: 1280, height: 720 } }, testIgnore: /lifeCircleRunning/ },
    /**
     * 真实模式（体检进行中）单独一个 project：它连的不是 5199，而是**代理指向 e2e mock 后端**
     * 的第二个 dev server（5200）。理由见 `e2e/support/lcRunningApi.mjs` —— 横幅要求任务
     * 停在 `running`，那需要一个真会保持打开的 SSE，`page.route` 一次性 fulfill 做不到。
     * 视口只取 1280×720：那条主张（无界横幅不许压塌舞台）在矮屏才可能成立不了。
     */
    {
      name: 'running 1280×720（真 SSE）',
      use: { viewport: { width: 1280, height: 720 }, baseURL: 'http://localhost:5200' },
      testMatch: /lifeCircleRunning/,
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --port 5199 --strictPort',
      url: 'http://localhost:5199',
      reuseExistingServer: true,
      timeout: 90_000,
    },
    {
      command: 'node e2e/support/lcRunningApi.mjs',
      url: 'http://127.0.0.1:8799/api/life-circle',
      reuseExistingServer: true,
      timeout: 30_000,
      stdout: 'pipe',
    },
    {
      command: 'npm run dev -- --port 5200 --strictPort',
      url: 'http://localhost:5200',
      reuseExistingServer: true,
      timeout: 90_000,
      // 只改代理目标，不改任何前端码：`/api` 落到上面那个 mock
      env: { ...process.env, VITE_PROXY_TARGET: 'http://127.0.0.1:8799' },
    },
  ],
})

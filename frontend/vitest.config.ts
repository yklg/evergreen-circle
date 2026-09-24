// 纯函数单测用 node 环境（无需 jsdom / React Testing Library）。
// 若后续补组件测试（T4），可在此切到 jsdom 并加 @testing-library/react。
// 用纯对象导出（不 import vitest/config），保证「项目内 npm test」与
// 「隔离 workspace 跑」两种场景都能加载，避免 ESM 解析依赖 vitest 安装位置。
export default {
  // 组件测试通过 @vitest-environment jsdom 逐文件切换；
  // 全局默认仍用 node 跑纯函数单测（modelResolution 等）。
  // 组件测试依赖 @testing-library/react + jsdom（见 clarifyAsync.test.tsx 头注释），
  // 安装后 frontend 内为单一 react 实例，无需额外 alias 配置。
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // M1 三跳合并：改造侧旅游前端组件/页面为 ours 旧版，gaizao 的 18 个旅游测试
    // 依赖 flip 后的新契约（13 结构化块/类型卡/C1 版式等），P2/M3 随组件移回。
    exclude: ['**/node_modules/**', '**/dist/**', 'src/**/_travel_pending/**'],
    globals: false,
    // jsdom 环境 localStorage 补水（Node 26 实验性全局 Web Storage 与
    // vitest 2.x / jsdom 30 组合的兼容适配，见 vitest.setup.ts）
    setupFiles: ['./vitest.setup.ts'],
  },
}

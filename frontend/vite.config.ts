import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 端口真值源在仓库根 .dev-ports.env（start.sh/restart.sh source 后以环境变量传入）。
// 直接 `npx vite`（不经脚本）时回落同一组默认值，保证两条启动路径不分裂。
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT ?? 3400)
const BACKEND_PORT = Number(process.env.BACKEND_PORT ?? 8010)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 本项目独立端口（与同机其它副本项目隔离）
    port: FRONTEND_PORT,
    strictPort: true,
    // 同时监听 IPv4/IPv6，规避 macOS 上 localhost→IPv6 解析导致 127.0.0.1 访问 502 的问题
    host: true,
    proxy: {
      '/api': {
        // docker-compose 预览用 VITE_PROXY_TARGET 注入服务名（最优先）；
        // 本地按 BACKEND_PORT 直达后端，缺省与 .dev-ports.env 同值。
        target: process.env.VITE_PROXY_TARGET ?? `http://127.0.0.1:${BACKEND_PORT}`,
        changeOrigin: true,
      },
    },
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 本项目独立端口（与同机其它副本项目隔离）
    port: 3400,
    strictPort: true,
    // 同时监听 IPv4/IPv6，规避 macOS 上 localhost→IPv6 解析导致 127.0.0.1 访问 502 的问题
    host: true,
    proxy: {
      '/api': {
        // 本地默认直达后端；docker-compose 预览用 VITE_PROXY_TARGET 注入服务名
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 本项目独立端口（与同机其它副本项目隔离）
    port: 3500,
    strictPort: true,
    // 同时监听 IPv4/IPv6，规避 macOS 上 localhost→IPv6 解析导致 127.0.0.1 访问 502 的问题
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8020',
        changeOrigin: true,
      },
    },
  },
})

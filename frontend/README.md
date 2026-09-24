# 青野 Verda · 前端

React 19 + TypeScript + Vite 单页应用，是青野 Verda AI 竞品情报工作台的前端。

完整项目介绍、架构与启动方式见仓库根目录 [README.md](../README.md)。

## 本地开发

```bash
npm install
npm run dev      # http://localhost:3500
```

开发服务器通过 Vite 代理把 `/api` 转发到后端（见 [vite.config.ts](./vite.config.ts)，默认 `http://127.0.0.1:8020`）。

## 常用脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | 启动开发服务器（端口 3500） |
| `npm run build` | 类型检查 + 生产构建（输出 `dist/`） |
| `npm run preview` | 预览生产构建 |
| `npm run lint` | ESLint 检查 |

## 目录结构

```
src/
├── pages/        # 页面（首页/工作台/报告/图谱/Trace/专家/仪表盘…）
├── components/   # 通用组件（V 前缀）
├── layout/       # AppLayout / VSidebar
├── store/        # Zustand 状态
├── hooks/        # useTaskStream（SSE 订阅）
├── lib/          # api.ts（REST + SSE 封装）
└── types.ts      # 契约类型
```

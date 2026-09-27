# 常青圈 EvergreenCircle · 前端

React 19 + TypeScript + Vite 单页应用：15 分钟生活圈智能体检与规划助手的界面层。

品牌称谓的唯一真源是 [`src/lib/brand.ts`](./src/lib/brand.ts)（改品牌只改那一处，
`src/lib/brand.test.ts` 会守住 `index.html` 的 `<title>` 不漂移）。
完整项目介绍与启动方式见仓库根 [README.md](../README.md)。

## 本地开发

```bash
npm install
npm run dev      # http://localhost:3400
```

端口真值源在仓库根的 `.dev-ports.env`（`BACKEND_PORT=8010` / `FRONTEND_PORT=3400`）：
`start.sh` / `restart.sh` / `stop.sh` source 它，直接 `npx vite` 时
[vite.config.ts](./vite.config.ts) 回落到同一组默认值，保证两条启动路径不分裂。

开发服务器通过 Vite 代理把 `/api` 转发到后端 `http://127.0.0.1:8010`。
**容器内后端监听 8000**，与宿主端口不是一回事（见 [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)）。

## 常用脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | 启动开发服务器（3400） |
| `npm run build` | 类型检查 + 生产构建（输出 `dist/`） |
| `npm run typecheck` | 仅 `tsc --noEmit` |
| `npm run lint` | ESLint 检查 |
| `npm run test` | Vitest 全量（jsdom，无 coverage 配置） |
| `npm run test:watch` | Vitest watch |
| `npm run preview` | 预览生产构建 |

## 目录结构

```
src/
├── pages/        # 16 个页面（见下）
├── components/   # 通用组件（V 前缀）；lifecircle/ 放生活圈地图与体检视图
├── layout/       # AppLayout / VSidebar
├── store/        # Zustand 状态（数据模式、批注、偏好、任务名册…）
├── hooks/        # useTaskStream（SSE 订阅）· useMapConfig（地图 AK/styleId）
├── lib/          # api.ts（REST + SSE）· bmap.ts（JSAPI 加载）· bmapStyle.ts（底图纪律）
├── __tests__/    # Vitest 套件；helpers/bmapGLFake.ts 是全套件唯一的 BMapGL 替身出口
└── dev/          # 取证探针页逻辑（不被应用入口引用 ⇒ 不进生产包，但进 tsc 与 eslint）
```

## 路由

带侧边栏框架：`/`（首页向导）· `/life-circle/:sceneId`（生活圈地图）· `/compare`（双样例对比）
· `/reports`（报告中心）· `/experts` 与 `/experts/:id`（专家团）· `/dashboard`（历史）· `/settings`。

全屏沉浸页：`/clarify/:taskId` · `/workspace/:taskId` · `/report/:reportId`
· `/report/:reportId/slides` · `/graph/:reportId` · `/trace/:reportId`。

`/library`（我的调研）与 `/knowledge` 已从主导航移除，但深链路由保留（旧页不回归既有测试）。
未知路径由 `*` 兜底回首页。

## 数据模式

侧边栏「数据模式」可即时切换真实联调 / 演示（选择记在 localStorage）；
`VITE_USE_MOCK` 只是首次打开的默认值，不是开关的唯一入口。见 `src/store/dataModeStore.ts`。

## 改动预览与取证页

根目录 `preview-*.html` + `src/dev/*Probe.ts` 是本仓既有的取证约定：Vite dev 直接按 URL 提供，
页面挂**真实模块**（同一份 AK、样式、算子），用于肉眼核对与截图留档。
这类文件不被应用入口引用，因此不进生产包。

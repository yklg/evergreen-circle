# GitHub 仓库文件架构

> 最后更新：2026-10-14
> 分支：`merge/travel-upgrade`
> 最新提交：截至本日 `73fc8b5`（2026-10-14，含合并 Gitee 侧网页编辑那一笔）。这一行天生会腐烂，核对一律以 `git log -1 --oneline` 现场为准

---

## 📁 仓库根目录结构

```
evergreen-circle/
├── 📄 核心文档
│   ├── README.md                    # 项目说明与快速开始 ⭐
│   ├── CONTRIBUTING.md              # 贡献指南(含评审方复现步骤)
│   ├── LICENSE                      # AGPL-3.0 许可证
│   └── NOTICE                       # 第三方组件署名
│
├── 🔧 启动脚本
│   ├── start.sh                     # 一键启动(新设备自动建环境)
│   ├── restart.sh                   # 日常重启
│   └── stop.sh                      # 停止服务
│
├── 🐳 Docker 配置
│   ├── Dockerfile                   # 后端镜像构建
│   └── docker-compose.yml           # 本地一键预览
│
├── ☁️ 云端部署清单
│   ├── vercel.json                  # Vercel 部署配置
│   ├── render.yaml                  # Render 部署配置
│   └── railway.json                 # Railway 部署配置
│
├── 📦 包管理
│   └── package.json                 # Vercel 构建入口(前端构建)
│
├── 🛠️ 工具脚本
│   ├── make_brand_icon.py           # 品牌图标生成脚本
│   └── scripts/
│       ├── run-demo.sh              # 一键演示脚本(零 Key 启动) ⭐
│       ├── check_app_mirror.sh      # API 镜像一致性检查
│       ├── make_delivery_pdf.py     # 交付文档 md → PDF(改 md 必重出同名 PDF)
│       ├── lc_healthcheck.py        # 生活圈体检件健康巡检(口径/形状/证据面)
│       └── lc_healthcheck_selftest.py # 上条判据的自证
│
├── 📂 主要目录
│   ├── backend/                     # FastAPI 后端
│   ├── frontend/                    # React 19 前端
│   ├── docs/                        # 技术文档
│   ├── deploy/                      # 自管云部署配置
│   └── cookie-export-helper/        # 浏览器扩展(Cookie 导出)
│
└── 🗑️ 临时/内部目录(gitignore)
    ├── .git/                        # Git 版本控制
    ├── node_modules/                # 前端依赖
    ├── __pycache__/                 # Python 缓存
    ├── .run-logs/                   # 运行日志
    ├── tmp/                         # 临时文件
    └── 预览与计划/                   # 设计草稿
```

---

## 📂 后端目录 (`backend/`)

```
backend/
├── app/                             # 应用代码
│   ├── core/                        # 共享底座
│   │   ├── runner.py                # 任务调度引擎(SSE)
│   │   ├── orchestrator.py          # 多 Agent 编排器
│   │   ├── models.py                # 数据模型
│   │   ├── db.py                    # 数据库层
│   │   ├── credibility.py           # 可信度计算
│   │   └── pipeline/                # 流水线
│   │       ├── living_circle.py     # 生活圈体检流水线 ⭐
│   │       ├── diagnosis_templates.py # 诊断模板
│   │       └── research/            # 目的地调研流水线
│   │
│   ├── living_circle/               # 生活圈域(独立子域) ⭐
│   │   ├── isochrone.py             # 等时圈计算(渔网采样+IDW)
│   │   ├── poi.py                   # POI 采集与清洗
│   │   ├── blindspot.py             # 服务盲区识别
│   │   ├── scoring.py               # 综合评分
│   │   ├── data_source.py           # 数据源抽象(Live/Fixture)
│   │   ├── baidu_client.py          # 百度地图客户端
│   │   ├── request_guard.py         # QPS 限流与退避
│   │   ├── geo_utils.py             # 地理工具
│   │   ├── geo_index/               # 地理索引(目录,含 china_regions.json 全国区划)
│   │   ├── category_rule.py         # 类别规则
│   │   ├── judgement.py             # 判定逻辑
│   │   ├── scope.py                 # 作用域与载荷
│   │   ├── caliber.py               # 口径定义
│   │   ├── anchors.py               # 锚点常量
│   │   ├── seat_registry.py         # 席位注册表
│   │   └── fixtures/                # 内置演示数据
│   │
│   ├── data/                        # 静态数据
│   │   ├── experts.json             # 专家名册(目的地调研)
│   │   └── experts_living_circle.json # 专家名册(生活圈)
│   │
│   ├── services/                    # 外部服务封装(baidu.py)
│   │
│   └── main.py                      # FastAPI 入口(REST + SSE)
│
├── tests/                           # pytest 测试套件
│   ├── test_baidu_client.py         # 百度客户端测试
│   ├── test_isochrone.py            # 等时圈算法测试
│   ├── test_poi.py                  # POI 采集测试
│   ├── test_blindspot.py            # 盲区识别测试
│   ├── test_scoring.py              # 评分模型测试
│   ├── test_living_circle_api.py    # 生活圈 API 测试
│   └── ...                          # 其他测试(收集 2852 项 / 2026-10-14 实测通过 2825 项)
│
├── scripts/                         # 后端工具脚本
│   ├── probe_baidu.py               # 百度 API 探针
│   ├── bake_lc_demo_reports.py      # 烘焙演示报告
│   ├── normalize_report_signatures.py # 规范化报告署名
│   ├── backfill_*.py                # 数据回填脚本
│   └── mutation_check.py            # 变异测试
│
├── requirements.txt                 # Python 依赖
├── requirements-dev.txt             # 开发依赖
├── .env.example                     # 环境变量模板 ⭐
└── .env                             # 本地环境变量(gitignore)
```

---

## 📂 前端目录 (`frontend/`)

```
frontend/
├── src/                             # 源代码
│   ├── pages/                       # 路由页面
│   │   ├── HomePage.tsx             # 工作台(体检入口)
│   │   ├── LifeCirclePage.tsx       # 体检地图页 ⭐
│   │   ├── ComparePage.tsx          # 对比页
│   │   ├── ReportPage.tsx           # 单份报告页(/report/:reportId)
│   │   ├── ReportsPage.tsx          # 报告列表页(/reports)
│   │   ├── ExpertsPage.tsx          # 专家团页
│   │   └── ...
│   │
│   ├── components/                  # 组件
│   │   ├── lifecircle/              # 生活圈专用组件 ⭐
│   │   │   ├── LcStage.tsx          # 体检舞台分栏契约(地图/图例/右栏)
│   │   │   ├── LcMap.tsx            # 真地图渲染层(BMapGL v3.0)
│   │   │   ├── LcSvgCanvas.tsx      # 降级静态画布的图层装配
│   │   │   ├── HeatFieldOverlay.ts  # 热力采样点 Canvas 覆盖层
│   │   │   ├── CellsLedgerCard.tsx  # 逐格台账卡
│   │   │   ├── LifeCircleReportView.tsx # 报告体检单视图
│   │   │   └── ...
│   │   ├── VChart.tsx               # 图表组件(ECharts)
│   │   ├── VDataGrid.tsx            # 数据表格
│   │   └── ...
│   │
│   ├── lib/                         # 工具库
│   │   ├── api.ts                   # API 客户端
│   │   ├── bmap.ts                  # 百度地图加载器
│   │   ├── livingCircle.ts          # 生活圈渲染器(单一出口) ⭐
│   │   ├── geo.ts                   # 地理工具
│   │   └── ...
│   │
│   ├── store/                       # Zustand 状态管理
│   │   ├── taskStore.ts             # 任务流状态
│   │   ├── dataModeStore.ts         # 数据模式(live/fixture)
│   │   ├── annotationStore.ts       # 划词批注
│   │   └── ...
│   │
│   ├── hooks/                       # 自定义 Hooks
│   │   ├── useTaskStream.ts         # SSE 订阅
│   │   └── ...
│   │
│   ├── mocks/                       # Mock 数据 ⭐
│   │   └── fixtures/
│   │       └── livingCircleReports/ # 生活圈演示报告
│   │           ├── kaili.report.json
│   │           ├── beijing-jinsong.report.json
│   │           ├── shanghai-wujiaochang.report.json
│   │           └── ...
│   │
│   ├── layout/                      # 布局组件
│   │   ├── AppLayout.tsx
│   │   └── VSidebar.tsx
│   │
│   ├── types.ts                     # TypeScript 类型定义 ⭐
│   └── main.tsx                     # React 挂载入口(App + Router)
│
├── public/                          # 静态资源
│   ├── favicon.svg                  # 品牌图标
│   └── apple-touch-icon.png         # iOS 图标
│
├── index.html                       # HTML 入口(vite 根)
├── e2e/                             # Playwright E2E 测试(8 个 spec × 3 个 project)
├── scripts/                         # 代码生成脚本(演示夹具/类型)
├── preview-*.html                   # 11 个 dev 探针入口页(改动前后同框对照,已入库)
│
├── tailwind.config.js               # Tailwind CSS 配置
├── vite.config.ts                   # Vite 构建配置(含 /api 代理目标)
├── playwright.config.ts             # 排版 e2e 配置(3 个 project·自起 5199/5200)
├── vitest.config.ts                 # jsdom 套件配置
├── eslint.config.js                 # lint 规则(阻断权在 src/__tests__ 的棘轮账本)
├── tsconfig.json                    # TypeScript 配置
├── package.json                     # NPM 依赖
├── .env.example                     # 前端环境变量模板(VITE_API_BASE)
└── README.md                        # 前端说明
```

---

## 📂 文档目录 (`docs/`)

```
docs/
├── 📘 核心架构文档
│   ├── ARCHITECTURE.md              # 系统架构(两产品域/地图链路/降级) ⭐
│   ├── AGENTS.md                    # Agent 体系(专家分层/协议/术语表) ⭐
│   └── DEPLOYMENT.md                # 部署指南(本地/云端/端口真值源) ⭐
│
├── 📊 赛题技术文档(三篇核心)
│   ├── 地图API调用策略与等时圈算法设计.md  # 调用策略/IDW 插值/实测边界 ⭐
│   ├── 多源POI数据清洗与服务盲区识别算法.md # 类别表/去重/判盲/评分 ⭐
│   └── 真实社区对比测试报告.md           # 凯里 vs 北京劲松实跑对比 ⭐
│
├── 🆕 赛题交付物文档
│   ├── 赛题交付物检查清单.md             # 自查清单 ⭐🆕
│   ├── 演示脚本验证报告.md               # 完整验证记录 ⭐🆕
│   └── 赛题交付物补充总结.md             # 工作总结 ⭐🆕
│
├── 📄 对外介绍文档
│   └── 常青圈_作品介绍.md               # 赛题要求的「作品介绍」正文:§2.1 十条能力表 + §9 完成度声明 ⭐
│
└── 📝 其他文档
    ├── 系统升级实施方案.md               # fork 前的完整设计演进
    ├── 雷达图遮挡修复-落地记录与后续项.md  # Bug 修复记录
    └── GITHUB_FILE_STRUCTURE.md         # 本文件(仓库架构说明) 🆕
```

---

## 📂 CI/CD 配置

```
.github/
└── workflows/
    └── ci.yml                         # GitHub Actions CI(唯一真源) ⭐

.workflow/
└── ci.yml                             # Gitee Go 流水线(子集)
```

**CI 流程**:
1. Backend: γ 静态守卫 → pytest（收集 2852 项；2026-10-14 实测 2825 passed / 4 skipped / 23 xfailed）
2. Frontend: typecheck → vitest（1429 项；159 个测试文件，实测 1428 passed / 1 todo）→ build（lint 为非阻断诊断）
3. 排版 e2e: Playwright（80 项运行实例 ＝ 8 个 spec × 3 个 project：1440×900、1280×720、连真 mock 后端的 running 档；2026-10-14 以 `npx playwright test --list` 静态枚举复核 `Total: 80 tests in 8 files`）
4. API 镜像运行时校验（frontend job 内的 step，`api/` 缺失时自我 SKIP）
5. Docker 构建（**仅 main/master 触发** ⇒ 本分支从不跑它，不能算作本分支的防线）

---

## 📂 部署配置 (`deploy/`)

```
deploy/
├── docker-compose.yml                 # 生产环境 Docker Compose
├── .env.worker.example                # worker 侧环境变量模板
├── nginx/
│   └── evergreen.conf                 # Nginx 站点配置
├── systemd/
│   └── evergreen-worker.service       # Systemd 服务单元
├── setup-vm.sh                        # VM 初始化脚本
└── README.md                          # 自管云部署说明
```

---

## 🆕 本次新增文件(2026-10-11)

| 文件 | 用途 | 重要性 |
|---|---|---|
| `scripts/run-demo.sh` | 一键演示脚本(零 Key 启动) | ⭐⭐⭐ |
| `docs/赛题交付物检查清单.md` | 赛题交付物自查清单 | ⭐⭐ |
| `docs/演示脚本验证报告.md` | 演示脚本完整验证记录 | ⭐⭐ |
| `docs/赛题交付物补充总结.md` | 本次工作总结 | ⭐ |
| `docs/GITHUB_FILE_STRUCTURE.md` | 本文件(仓库架构说明) | ⭐ |

〔勘误 2026-10-12〕本表原先还列过一行 `docker-compose.test.yml`「测试环境配置」—— 该文件从未入库、磁盘上也不存在，属虚构条目，已删。

**修改的文件**:
- `backend/.env.example` - 增强百度 AK 配置注释(Referer 白名单详细说明)
- `CONTRIBUTING.md` - 新增"复现实测结果(评审方指南)"章节
- `README.md` - 新增"评审方无 Key 演示指南"章节

---

## 🔑 关键文件说明

### 启动相关
- **`start.sh`** - 新设备从零建环境 → 拉起前后端 → 打开浏览器
- **`scripts/run-demo.sh`** - 🆕 一键演示模式(零 Key/零网络依赖)
- **`restart.sh`** - 日常纯重启(更快,不查依赖)
- **`stop.sh`** - 关闭服务

### 配置相关
- **`backend/.env.example`** - 后端环境变量模板(LLM/百度 AK/博查 API)
- **`frontend/.env.example`** - 前端环境变量模板(API 基址)
- **`.dev-ports.env`** - 端口真值源(后端 8010 / 前端 3400)

### 文档相关
- **`README.md`** - 项目主说明(快速开始/AK 配置/算法简述/演示指南)
- **`docs/ARCHITECTURE.md`** - 系统架构详解(两产品域/数据模式/降级链路)
- **`docs/AGENTS.md`** - Agent 体系(专家分层/消息协议/四条铁律/术语表)
- **`docs/DEPLOYMENT.md`** - 部署指南(本地/云端/Python 解释器约束)

### 测试相关
- **`backend/tests/`** - pytest 套件(收集 2852 项;2026-10-14 实测 2825 passed / 4 skipped / 23 xfailed)
- **`frontend/src/__tests__/`** - vitest 套件(1429 项;159 个测试文件,实测 1428 passed / 1 todo)
- **`frontend/e2e/`** - Playwright E2E 测试(80 项运行实例 = 8 个 spec × 3 个 project)

---

## 📊 仓库统计

- **总文件数**(git 跟踪,不含依赖/缓存): 798 个（截至 2026-10-14；核对用 `git ls-files | wc -l`，本行会随提交漂移）
- **代码行数**: `backend/app/**/*.py` **32,413 行 / 82 个文件** ＋ `frontend/src` 全部 `ts/tsx` **64,319 行 / 312 个文件**（含 `__tests__` 与 dev 探针）＝ **96,732 行**；只算应用代码（前端剥掉 `__tests__` 与 `src/dev/`）则 32,413 ＋ 32,004 ＝ **64,417 行**（2026-10-14 实测，与作品介绍 §1 同一命令口径；旧版这行写的"不含 tests"却按含的方式测，两半口径不一致，已按同一命令重取）
- **测试用例**: 收集口径 4361 项(pytest 2852 ＋ vitest 1429 ＋ Playwright e2e 80);通过口径 4333 项(2825 ＋ 1428 ＋ 80;e2e 那 80 项今日只做了 `--list` 静态枚举核对项数，通过数以 CI #56 全绿读数为准)
- **文档数量**: `docs/` 下 14 份 git 跟踪(13 份 Markdown ＋ 1 份 PDF〔作品介绍〕,截至 2026-10-14)
- **CI Job 数量**: 4 个(backend / frontend / e2e / docker;docker 仅 main/master 触发)
- **最新提交**: 截至 2026-10-14 为 `73fc8b5`(本行会腐烂,核对以 `git log -1 --oneline` 为准)
- **分支**: `merge/travel-upgrade`(远端唯一分支,亦即默认分支;已包含 `upstream/main` 的全部提交)

---

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/yklg/evergreen-circle （**截至 2026-10-14 已转公开**：匿名 `api.github.com/repos/yklg/evergreen-circle` 返回 `visibility=public`，默认分支 `merge/travel-upgrade`；此前 2026-10-12 的读数是"私有、匿名 clone 404"，那一行已过期）
- **Gitee 镜像**: https://gitee.com/a-triumphant-journey-ahead/evergreen-circle （2026-10-14 接上，与 GitHub **逐位一致**：两侧 HEAD 同一笔、`git ls-tree -r` 逐文件 blob 对账 798 条零差异、匿名 API 返回 `public=true`；具体 sha 会随每次推送漂移，核对用 `git ls-remote --heads submit gitee`；`.workflow/ci.yml` 仍是**惰性配置**——远端已接、分支白名单已对上 `merge/travel-upgrade`，但 Gitee Go 未在网页启用（那一步只能他本人在控制台点），GitHub Actions 为唯一防线；启用后若首次 push 未触发，排查顺序写在该文件头部）
- **在线 Demo**: 公开实例未部署；评审入口按他的决定＝**演示视频**（[哔哩哔哩](https://www.bilibili.com/video/BV1QJpB6pE6T) ｜ [抖音](https://v.douyin.com/nExkJft30tg)）。零 Key 本地演示走 `./scripts/run-demo.sh`（自动开 http://127.0.0.1:3400），与线上实例同一条链路
- **问题反馈**: https://github.com/yklg/evergreen-circle/issues

---

**维护者**: Qoder AI Assistant + 开发团队
**许可证**: AGPL-3.0
**最后更新**: 2026-10-12（完结核查：逐条对 `git ls-files` 回源，修掉与云端不符的条目）

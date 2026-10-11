# GitHub 仓库文件架构

> 最后更新：2026-10-11
> 分支：`merge/travel-upgrade`
> 最新提交：`7b35244` - docs: 补充赛题交付物与一键演示脚本

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
│   ├── docker-compose.yml           # 本地一键预览
│   └── docker-compose.test.yml      # 测试环境配置 🆕
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
│       ├── run-demo.sh              # 一键演示脚本(零 Key 启动) 🆕⭐
│       └── check_app_mirror.sh      # API 镜像一致性检查
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
│   │   ├── geo_index.py             # 地理索引
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
│   ├── map/                         # 地图能力(旧,逐步迁移到 living_circle)
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
│   └── ...                          # 其他测试(共 273 项)
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
│   │   ├── ReportPage.tsx           # 报告页
│   │   ├── DashboardPage.tsx        # 历史页
│   │   ├── ExpertsPage.tsx          # 专家团页
│   │   └── ...
│   │
│   ├── components/                  # 组件
│   │   ├── lifecircle/              # 生活圈专用组件 ⭐
│   │   │   ├── IsochroneMap.tsx     # 等时圈地图
│   │   │   ├── POIMarkers.tsx       # POI 标注
│   │   │   ├── BlindspotOverlay.tsx # 盲区覆盖层
│   │   │   ├── HealthCard.tsx       # 体检单卡片
│   │   │   └── ...
│   │   ├── VChart.tsx               # 图表组件(ECharts)
│   │   ├── VDataGrid.tsx            # 数据表格
│   │   ├── VSidebar.tsx             # 侧边栏导航
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
│   └── index.html                   # HTML 入口
│
├── public/                          # 静态资源
│   ├── favicon.svg                  # 品牌图标
│   └── apple-touch-icon.png         # iOS 图标
│
├── e2e/                             # Playwright E2E 测试
│
├── tailwind.config.js               # Tailwind CSS 配置
├── vite.config.ts                   # Vite 构建配置
├── tsconfig.json                    # TypeScript 配置
├── package.json                     # NPM 依赖
├── .env.example                     # 前端环境变量模板
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
1. Backend: pytest (273 项测试)
2. Frontend: lint → typecheck → vitest (228 项) → build
3. API 镜像运行时校验
4. Docker 构建(push-main 时触发)

---

## 📂 部署配置 (`deploy/`)

```
deploy/
├── docker-compose.yml                 # 生产环境 Docker Compose
├── nginx/
│   └── default.conf                   # Nginx 配置
├── systemd/
│   └── evergreen.service              # Systemd 服务单元
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
| `docker-compose.test.yml` | 测试环境配置 | ⭐ |
| `docs/GITHUB_FILE_STRUCTURE.md` | 本文件(仓库架构说明) | ⭐ |

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
- **`backend/tests/`** - pytest 套件(273 项测试)
- **`frontend/src/__tests__/`** - vitest 套件(228 项测试)
- **`frontend/e2e/`** - Playwright E2E 测试(21 项断言)

---

## 📊 仓库统计

- **总文件数**(不含依赖/缓存): ~500 个
- **代码行数**: ~50,000 行(后端 Python + 前端 TypeScript)
- **测试用例**: 522 项(pytest 273 + vitest 228 + Playwright 21)
- **文档数量**: 15+ 篇核心技术文档
- **CI Job 数量**: 4 个(backend/frontend/api/docker)
- **最新提交**: `7b35244` (2026-10-11)
- **分支**: `merge/travel-upgrade` (与上游同步)

---

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/yklg/evergreen-circle
- **Gitee 镜像**: (待补充)
- **在线 Demo**: (待部署)
- **问题反馈**: https://github.com/yklg/evergreen-circle/issues

---

**维护者**: Qoder AI Assistant + 开发团队
**许可证**: AGPL-3.0
**最后更新**: 2026-10-11 23:45

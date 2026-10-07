# 贡献指南 · Contributing

感谢你对常青圈 EvergreenCircle 的关注！本文档说明如何参与贡献、提交规范与分支管理约定。

---

## 行为准则

请保持友善、专业、建设性的沟通。我们欢迎任何形式的贡献：报告 Bug、提交功能、完善文档、优化体验。

---

## 开发流程

1. **Fork** 本仓库并克隆到本地。
2. 按 [README](./README.md) 配置环境与密钥（**切勿提交真实密钥**）。
3. 从 `main` 切出特性分支：

   ```bash
   git checkout -b feat/your-feature
   ```

4. 完成修改，确保本地能跑通且通过检查（见下方「提交前检查」）。
5. 按约定式提交（Conventional Commits）提交。
6. 推送分支并发起 Pull Request，在描述中说明动机与改动点。

---

## 分支管理

| 分支 | 用途 |
|---|---|
| `main` | 稳定主分支，始终可运行 |
| `feat/*` | 新功能 |
| `fix/*` | Bug 修复 |
| `docs/*` | 文档 |
| `refactor/*` | 重构（不改变外部行为） |
| `chore/*` | 构建 / 配置 / 杂务 |

请保持单个 PR 聚焦一件事，便于审查。

---

## 提交规范（Conventional Commits）

提交信息格式：

```
<type>(<scope>): <subject>
```

常用 `type`：

| type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复 Bug |
| `docs` | 文档变更 |
| `style` | 格式（不影响逻辑） |
| `refactor` | 重构 |
| `perf` | 性能优化 |
| `test` | 测试 |
| `chore` | 构建 / 工具 / 杂务 |

示例：

```
feat(orchestrator): 写作阶段改为多章节并行以提速
fix(credibility): 修正时效性评分边界条件
docs(readme): 补充 Vercel 部署说明
```

---

## 代码风格

### 前端（TypeScript / React）

- 遵循项目 ESLint 配置：

  ```bash
  cd frontend
  npm run lint
  ```

- 组件以 `V` 前缀命名（如 `VTracePanel`），与现有约定保持一致。
- 优先函数组件 + Hooks；全局状态用 Zustand。

### 后端（Python / FastAPI）

- Python 3.9 兼容：使用 `typing.Optional` / `List`，避免运行期解析 `X | None` 的问题。
- 关键模块保留中文 docstring 说明「为什么这么做」。
- 密钥一律从环境变量读取，禁止硬编码。

---

## 提交前检查

- [ ] 前端 `npm run lint` 与 `npm run build` 通过
- [ ] 后端可正常启动，`/health` 与 `/api/llm/ping` 正常
- [ ] **没有任何真实 API Key / Token / Cookie 被提交**（检查 `.env` 未被纳入）
- [ ] 没有提交本地数据库 `*.db` / 日志 / `.DS_Store` 等产物
- [ ] 提交信息符合 Conventional Commits

---

## 推送前检查（CI 的每个 job 都要在**干净树**上验过）

「提交前检查」答的是"我的改动对不对"；CI 跑的是**每一个 job**（api 运行时校验 / 后端 pytest /
前端 vitest / Playwright 排版回归 / docker）。本地那棵树里躺着他未提交的在制品时，
"我这边全绿"和"远端在干净树上跑出来的结果"不是一回事 —— 所以这一段单开。

- [ ] `git fetch <远端>` 后 `git rev-list --count HEAD..<远端>/<分支>` **为 0** 才推。
      非 fast-forward 就先查远端多出来的是谁的什么（`git log 远端 ^本地`），绝不 `--force`。
- [ ] `git diff --name-only <远端>..HEAD` 枚举待推文件：扫一遍密钥样式
      （`api_key|secret|password|token|access_key|PRIVATE`），确认没有 `.env` / `*.db` / 日志产物。
- [ ] **在 pristine worktree 上跑**：`git worktree add --detach /tmp/x HEAD`
      + 软链 `frontend/node_modules`，然后把 `.github/workflows/ci.yml` 里**每个 job 的命令**
      各跑一遍（typecheck、vitest、`npx playwright test`、后端 pytest、变异台架）。
      ⚠️ 只跑了 vitest ≠ e2e 会绿；只跑了后端 ≠ 台架锚点还在。
- [ ] 任何红先做**归属判定**：把同一条在**远端基线**（`git worktree add` 到 `<远端>/<分支>`）再跑一次。
      基线也红 ⇒ 不是这批引入的：把成因与修法写进报告、交给对应的人，**别顺手修别人的账**；
      只有本批引入的才当场修。
- [ ] 跑不到的部分（要真 AK、真网络、真实视口）**写成未验证项并标缺口类型**（环境不可达 / 无入口 /
      未实测），不许用"机制上应该没问题"顶替实测。
- [ ] e2e 分档约定：live 与降级/CI-mock 验的**不是同一组命题**（降级画布走 SVG viewBox，压根没有
      `canvas`）。加判据前先回答"这条在哪些可得环境里会跑到"；要 skip 就写明原因，
      **恒 skip 比红更坏** —— 它让套件看起来被处理过了。

> 实测代价（2026-10-07）：推 11 笔前只验了 typecheck + vitest + 后端全量，没跑 Playwright job
> ⇒ 推上去 6 条 e2e 红 + 1 条 tailwind 悬空类棘轮红。事后逐条归属：都是**基线缺陷**
> （那份 e2e 缺"按渲染模式分支"的判据；点名账上记着一个尚未跟踪的探针页），不是那批笔次引入的。

## 关于 AI 协作

本项目在开发中深度使用 [TRAE](https://www.trae.ai/) 等 AI 编程工具协作完成。欢迎在 PR 中说明你的 AI 协作过程（如设计决策、迭代方案），这有助于其他贡献者理解改动背景。完整的设计与演进方案见 [docs/系统升级实施方案.md](./docs/系统升级实施方案.md)。

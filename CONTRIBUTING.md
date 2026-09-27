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

## 关于 AI 协作

本项目在开发中深度使用 [TRAE](https://www.trae.ai/) 等 AI 编程工具协作完成。欢迎在 PR 中说明你的 AI 协作过程（如设计决策、迭代方案），这有助于其他贡献者理解改动背景。完整的设计与演进方案见 [docs/系统升级实施方案.md](./docs/系统升级实施方案.md)。

# travel_pending —— M1 休眠期暂不收集的旅游域测试

这些测试随 gaizao-travel 分支在 **M1 树合并**时进入仓库，但被测对象（改造侧旅游引擎
`pipeline/research` 包、gaizao 版 orchestrator 外壳、brands→destinations 迁移）
在 M1 处于**休眠/未启用**状态：

- M1：本目录被 `tests/conftest.py::collect_ignore` 排除，pytest 不收集；
- M2-flip：引擎切换、外壳 v2、db 迁移启用后，文件**移回 tests/** 并按
  import 路径改写（外壳符号留 orchestrator、引擎符号改 `app.core.pipeline.research.*`）；
- 被剥除的特例：`test_semantic_residue.py` 移回时删除末尾 api/backend 镜像集合断言
  （serverless 已废弃），仅保留 brand 语义残留白名单；
  `test_serverless_terminal.py` 随 serverless 废弃直接删除不移回。

勿在本目录新增测试；旅游域新测试直接写到 flip 后的 tests/。

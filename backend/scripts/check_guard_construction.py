#!/usr/bin/env python
"""γ 静态守卫（2026-09-22 · 批次 3）：把「进程级治理不得被绕过」从约定变成**机器可校验**。

背景（β）：治理曾是 **opt-in** —— `BaiduClient(guard=…)` 会整条跳过 `_default_guard`，
于是「显式传一个 guard」成了一条**静默脱离**共享闸/共享日预算的后门。β 已在
**构造期**把绑定做成不变量；本脚本在**编辑期 / CI 期**再拦一道，让**新的**绕过写不进来。

规则（**全部用 AST，绝不用正则**）
--------------------------------
正则会把「docstring / 字符串字面量 / 注释里的**引用字样**」误判成违例 ——
而本仓恰好有 4 处这种**合法引用**（`baidu_client.py` 模块 docstring 与 :145 的日志文案里
写着 `allow_ungated=True`；`request_guard.py:364` 的用法示例里写着 `CallGuard(`；
`tests/test_rate_limiter_shared.py:394` 的 assert 消息里写着 `date.today()`）。
⇒ 用正则的守卫**一接上就把本仓判红**，只能被迫加例外，最后沦为噪声。

| 号 | 规则 | 理由 |
|---|---|---|
| **G-1** | `tests/**` **之外**出现**直接构造** `CallGuard(...)` ⇒ 违例（白名单见下） | 生产代码只能经**唯一工厂**拿闸；自造 = 私有闸 = 静默脱离治理 |
| **G-2** | `tests/**` **之外**出现 `allow_ungated=` **关键字实参** ⇒ 违例 | 进程级闸豁免只许测试用（K10 裁决） |
| **G-3** | `tests/**` 的 **assert 被测表达式**内读挂钟（`date.today()` / `datetime.now()` / `datetime.today()`）⇒ 违例 | 断言不得依赖宿主机时钟（K3「口径不随宿主机漂移」同族） |
| **G-4** | `tests/**` 之外出现 `SpatialScope.from_iso(...)` 调用 ⇒ **只允许 1 处**（在 `data_source.scope_or_degrade` 内） | 空等时圈时必须**先分流降级**再选环；任何新入口直接调它 ⇒ 降级代码不可达（根因 B 复发的机器判据） |
| **G-5** | `app/core/pipeline/**` 任何模块 import `app.core.orchestrator` 或 `app.core.runner` ⇒ 违例 | 流水线是被调度的内层；反向握住外壳/调度器即成环，M3 提取的单向依赖被击穿 |
| **G-6** | `app/core/orchestrator.py` 的 pipeline 导入**只能**打在 `app.core.pipeline.research.engine` 公共面 | 外壳不许伸手进 research 子模块/living_circle 内部（内部重提取会被它锁死）；需要的符号经 engine re-export |
| **G-7** | research 包内除 `__init__.py`/`engine.py` 外，任何模块 import `engine`（绝对或相对回边）⇒ 违例 | engine 是编排顶层 + 兼容 re-export 面；子模块回握 engine 即环形依赖，子模块不再可独立测试 |
| **G-8** | `app/**` 里出现**结构化块键字面量**（`spot_ranking` / `persp_checklist` / …），且不在**模块顶层声明表**内 ⇒ 违例 | 块键的归属是注册表。键名散进函数体 = 该函数按块名分叉，加一个块类型就得改一片编排/图表/规整代码（Part A 刚拆掉的那 5 处硬编码正是这条规则的成因） |
| **G-9** | `app/**` 里调用**取证步骤原语**（`scope_or_degrade` / `load_poi` / `bind_evidence` / `degrade_if_incomplete` / `assemble_living_circle`）⇒ **每个原语只允许 1 处**，且必须在 `data_source.live_forensic_steps` 函数体内 | 取证编排（等时圈→口径→采集→绑证据→残缺判定→组装）此前抄了三份，而线上只跑 pipeline 那一份 ⇒ 顺序/降级/`partial` 的修正永远到不了另外两份（第六轮复审 P0-6）。回合循环（计划阶段 5）要接的是**这一份**：任何新入口自己调原语 = 第四份编排，且它不会出现在任何一条现有事件序列用例里 |
| **G-10** | `app/**` 里调用**判定原语**（`judge_once` / `_verdict_masks` / `cover_matrix` / `find_blindspots_with_stats` / `find_blindspots`）⇒ 调用点必须落在登记表内，且**每个名字的总调用数必须等于实测期望**；`cover_matrix` 与两个 `find_blindspots*` 的期望是 **0**（生产侧不许调用） | 片 1a：判定产物 `Judgement` 要穿过组装层边界给取证回合复用。留着「第二处逐格判定」就等于允许「两次判定吃的证据区域是不是同一块」无人能证 —— 那正是收拢前 `assemble` 自己判一遍、`undecided_mask` 再判一遍的形状。旧报告视图只留给测试，生产侧调用者必须为 0。**名字匹配前先过一层别名归一**（`import judge_once as probe` ⇒ 归回 `judge_once`，G-1 同享），`getattr(obj, "原语名")` 一律判红；残留看不见的是 `globals()["…"]`/`eval`/赋值别名（`probe = judge_once` 再调），见 `_getattr_literals` 的效力上限说明 |
| **G-11** | `app/**` 里**任何函数默认值**不许是口径常量。认得的形状：`Name`、`模块.常量`（`Attribute` 末段）、`import … as` 别名、**模块级赋值别名**（`R = BLIND_RADIUS_M` 后再 `def f(r=R)`）、以及剥掉取值不变包装后的 `float(X)/int(X)/round(X,…)`/`-X`/`X * 1.0`；含 `*` 之后的 kwonly、含 `Lambda`。逐名实测期望：`BLIND_RADIUS_M` **0**（15 处已改成哨兵 `None` + 调用时经 `scope.blind_radius_or` 决议）、`BLIND_GRID_M` **6**（`blindspot.py` 里的格距默认值，它的"住所"属于 D5 规格导出，本片登记为已知存量、棘轮不许增） | 函数默认值在 **def 期求值**、被捕获进函数对象 ⇒ 把判定半径搬进口径对象 `ReachCaliber.blind_radius_m` 之后，残留的 `= BLIND_RADIUS_M` 会让那 15 条默认路径**继续吃 1000.0**：改了源头、行为没改、测试全绿，是本仓最难发现的一类形状。第十五轮复审 P1-4 指出：只认顶层 `Name/Attribute` 时，`float(BLIND_RADIUS_M)` 与一条模块级赋值别名（本仓真有过 `EVIDENCE_MARGIN_M = BLIND_RADIUS_M`）同样能焊死口径值却出闸 ⇒ 这几形一起认。这条闸把"21 条取值途径"收成机器可证的数 |

白名单（**仅 G-1**，两处，都必须存在）
------------------------------------
- `app/living_circle/request_guard.py` —— 闸的**定义模块**（整文件放行）；
- `app/living_circle/baidu_client.py` —— **唯一工厂**，但**只放行 `_default_guard` 函数体内**。
  ⚠️ 在该文件的**其它函数**里构造 ⇒ **照红**：否则「唯一工厂」会退化成「整文件豁免」，
  守卫随之失去意义。文件被改名 / 函数被改名 ⇒ 白名单失配 ⇒ **响亮报错**（这是正确的失效方向）。

⚠️ 四处刻意的不对称（都是实测踩出来的，别「修」掉）
--------------------------------------------------
1. **G-3 只扫 `Assert.test`，不扫 `Assert.msg`**：`msg` 是**给人看的解释文案**，
   「若实现退回宿主机本地 `date.today()`，此处必红」这种**引用**正是它该出现的地方
   （本仓 `tests/test_rate_limiter_shared.py:394` 即活实例）。扫 `msg` 会把它误判成违例。
2. **G-1 的作用域是「`tests/**` 之外」而不是方案原文的「`app/**`」**：本仓生产侧还有
   `scripts/**`（`make_fixture_points.py` 就在那里真实构造 `BaiduClient`），
   而「新绕过写不进来」要求覆盖**未来新增的顶层目录**。作用域取严（零当前代价）。
3. **G-8 的作用域反过来是「只有 `app/**`」，且带一份 38 处的棘轮基线**（不像 G-1/G-2 零基线）：
   ① 测试与一次性脚本**点名块名是它们的本职**（夹具、断言、迁移脚本各只处理一个键），
   扫它们只会逼人放宽断言或加 `# noqa`；② 落地时实测现网 **38 处**（不是方案写的 5 处），
   全量重构要吃掉 `engine.py`（churn 第一）这一整轮回归面，与本轮「单份报告增量=0、
   改动面有界」的代价承诺冲突 ⇒ 记成**只许变短**的棘轮，而不是文件白名单：
   白名单豁免整个文件且永远为真，棘轮精确到「文件::函数::键×次数」，
   新增一处即红、修掉一处不删条目也红。
   ⚠️ **效力上限**（别把它读成"再没有视角分支了"）：G-8 管的是**块名字面量**与「在通用代码里
   按块名分叉」，管不到 `if persp_sid == "persp_family"` 这类按**视角 id** 写的分支 —— 视角 id
   出现在编排层本身是合法登记，不该由门顺带接管。那条由 `tests/test_perspective_family.py`
   的注册表元测试守，不靠静态扫描。
4. **G-9 的作用域也是「只有 `app/**`」，但理由与 G-8 不同**：`scripts/make_fixture_points.py`
   确实调了 `load_poi` + `bind_evidence`（:60/:68），而那是**夹具生成** —— 它的本职就是把原始
   步骤跑一遍再落盘成测试用的「事实」，不是一条体检入口（它连事件都没有）。把 `scripts/**`
   扫进 G-9 只会逼人给夹具脚本加豁免，而豁免一旦按文件开，「唯一编排」就退化成套壳。

G-4 白名单（函数级，与 G-1 同纪律）
--------------------------------
- `app/living_circle/data_source.py` —— **只放行 `scope_or_degrade` 函数体内**（线上唯一选环出口）；
- `scripts/make_fixture_points.py` —— **只放行 `augment_one`**（夹具脚本，抛错才是正确行为）；
  两处合计**必须恰为 2**。
  ⚠️ 判据是 `SpatialScope.from_iso` 的 **AST Call 节点**，不是正则 `from_iso(` ——
  后者会连 `scope.py:98` 的 `def from_iso(` 一起命中（实测 4 处 vs 真调用 3 处），照字面执行**恒红**。

用法
----
    python scripts/check_guard_construction.py                 # root 默认 = 本文件上一级（backend/）
    python scripts/check_guard_construction.py --root DIR      # 供测试注入夹具树
退出码：0 = 通过；1 = 有违例。输出逐条：`相对路径:行号: 规则号 说明`。
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

# 扫描时**在遍历中就剪掉**的目录：`.venv` 有上万文件，`rglob` 会先枚举再过滤 ⇒ 必须用 os.walk 剪枝
SKIP_DIRS = frozenset({
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

# ⚠️ 用**哨兵**而不是 `dict.get(rel)` 的默认 `None`：本表里 `None` 是**合法值**（= 整文件放行），
# 与「键不存在」混为一谈会让**未白名单的文件被静默放行**（哨兵陷阱，见 verification-claim-discipline）。
_ABSENT = object()

# 相对路径 → 允许出现 `CallGuard(...)` 的函数名集合；None = 整文件放行
CALLGUARD_ALLOWLIST: dict[str, frozenset[str] | None] = {
    "app/living_circle/request_guard.py": None,
    "app/living_circle/baidu_client.py": frozenset({"_default_guard"}),
}

# G-3：(对象名, 方法名) —— `datetime.today()` 与 `date.today()` 同族，一并禁（同族要同批）
CLOCK_READS = frozenset({
    ("date", "today"),
    ("datetime", "now"),
    ("datetime", "today"),
})


# G-4：`SpatialScope.from_iso` 的许可调用点（文件 → 允许的函数名集合）
#
# ⚠️ **刻意的 2 处**（与 G-1/G-3 的不对称同族，别「顺手统一」成 1）：
#   ① `data_source.scope_or_degrade` —— **线上唯一选环出口**：空等时圈时先分流降级再选环；
#   ② `scripts/make_fixture_points.augment_one` —— **夹具生成脚本**：这里
#      `from_iso` 抛错是**正确行为**（宁可响亮失败，也不要把空壳夹具写进仓里 ——
#      夹具是测试的「事实」，写坏了会污染所有下游断言）。
#      ⇒ 它不是「漏网之鱼」，是**显式登记的例外**，理由写在这里，改的人看得见。
FROM_ISO_ALLOWLIST: dict[str, set[str]] = {
    "app/living_circle/data_source.py": {"scope_or_degrade"},
    "scripts/make_fixture_points.py": {"augment_one"},
}
# 许可调用点总数（函数级收口 ⇒ 必须恰为白名单条目数；多一处 = 又有人在别处选环）
FROM_ISO_EXPECTED_CALLS = 2

# G-9：取证编排的唯一入口（计划 v6.1 片 0）
#
# 这五个原语**合起来**就是「一次取证」：口径绑定 → 采集 → 绑实测证据 → 残缺判定 → 组装。
# 过去它们被抄了三遍（pipeline live 分支 / `LiveDataSource.compute` /
# `refine_live_with_profile`），三份的顺序逐字同构 —— 于是「改一份、漏两份」成为本仓
# 最稳定的缺陷来源（第六轮复审 P0-6）。收拢后唯一出口是 `live_forensic_steps`；
# 本道门的职责是**拦住第四份**：谁再自己调这些原语，就是在别处重启那条漂移。
# ⚠️ 期望值按**原语个数**算且逐个数：某个原语计数从 1 掉到 0，意味着生成器不再走它
#   —— 那是「静默少做一步」，与「多做一份」同样危险，不能只报多了。
FORENSIC_ALLOWLIST: dict[str, set[str]] = {
    "app/living_circle/data_source.py": {"live_forensic_steps"},
}
FORENSIC_PRIMITIVES = (
    "scope_or_degrade",        # 内含 `SpatialScope.from_iso`（G-4 守的那一步）
    "load_poi",                # 8 类 + 三要素采集
    "bind_evidence",           # 绑定实测证据边界（判盲/落库同源的上游）
    "degrade_if_incomplete",   # 采集后残缺判定
    "assemble_living_circle",  # 组装（评分/盲区/契约）
    # 片 4 追加：扩容回合的采集原语。加进这张表的理由是双向的 ——
    # 多了 ⇒ 有人在编排外开第二条取证回路；掉了 ⇒ 生成器不再走回合，静默退回"只采一轮"。
    # ⚠️ `plan_expansion` **不进**这张表：它在 `_plan_cat` 这个私有壳里被调两趟（量需求 +
    # 按份额砍），owner 名与 `live_forensic_steps` 不同；把它登记进来就是把"恰一处在编排内"
    # 这条门改成给自家形状让路。它的唯一性由 `anchors.py` 的文件级主张
    # （「取证强度规划的唯一出口」）与 `test_forensic_rounds.py` 那条跨轮串联用例管。
    "collect_triad_evidence",
)
FORENSIC_EXPECTED_CALLS_PER_PRIMITIVE = 1

# G-10：判定原语的唯一入口（计划 v6.5 片 1a）
#
# 与 G-9 同族但**期望值不再是统一标量** —— 判定这一头有两种合法形状：
# 「生产侧恰一处」（`judge_once` 只许编排层调）与「生产侧零处」
# （`cover_matrix` / `find_blindspots*` 是留给测试的旧报告视图壳）。
# ⚠️ 「零调用」不能靠计数表达：计数只在**落在登记表内**时累加，所以任何未登记的调用
#   会先被逐点判红；`expected=0` 的那几名真正起作用的是前半条。把它们写成
#   「owner 集合为空」而不是「owner 存在但函数名换掉」，是为了让**新壳也一并拦住**。
# 期望值全部按**改后实测**填（第九轮 P0-2 点名的就是"预留未来的计数"）：
#   judge_once 3 = 编排层 1 + 两个壳各 1；
#   _verdict_masks 3 = 报告视图壳 `cover_matrix` 1 + 唯一入口 `judge_once` 1
#                      + 规划视图壳 `undecided_mask` 1（它比 `cover_matrix` 多一张 `verdict`，
#                        取证判据读的是它；产物已收成 `JudgeMasks.undecided`，公式不再两处写）。
# ⚠️ 「视图壳」是三个还是两个不是重点，重点是**它们在 `app/**` 里的生产调用者必须为 0**：
#    掩码由它们各自调 `_verdict_masks` 生成，但一次真实体检只走 `judge_once` 那一条
#    （由 `JUDGE_EXPECTED_CALLS` 里 `cover_matrix`/`undecided_mask`/`find_blindspots*` 全为 0
#     钉住）。这条分工是行为事实，另有 `test_p1a_*_only_once_per_checkup` 从运行期钉。
JUDGE_ALLOWLIST: dict[str, set[str]] = {
    "app/living_circle/data_source.py": {"live_forensic_steps"},
    "app/living_circle/blindspot.py": {
        "cover_matrix", "judge_once", "undecided_mask",
        "find_blindspots_with_stats", "find_blindspots",
    },
}
JUDGE_EXPECTED_CALLS: dict[str, int] = {
    "judge_once": 3,
    "_verdict_masks": 3,
    "cover_matrix": 0,
    "undecided_mask": 0,
    "find_blindspots_with_stats": 0,
    "find_blindspots": 0,
}

# G-11：口径值不许当**函数默认值**（计划 v6.9 片 1b）
#
# 为什么单独立一道门：函数默认值在 **def 期求值**，值被捕获进函数对象。所以"改源头常量"
# 永远改不到这些默认路径 —— 生活圈片 1b 之前，判定半径有 15 条这样的途径（另有 5 处体内
# 硬用、1 处发射进产物）。半径搬进口径对象 `ReachCaliber.blind_radius_m` 之后，若这里
# 还留一个 `= BLIND_RADIUS_M`，分档就静默失效，而全量测试一字不差。
#
# ⚠️ 两把尺**期望值不同**，不是漏配：
#   `BLIND_RADIUS_M` = **0**（本片已把 15 处全部改成哨兵 `None` + 调用时决议）；
#   `BLIND_GRID_M`   = **6**（`blindspot.py` 里的格距默认值，它的"住所"属于 D5 规格导出那一步，
#                        本片不动 ⇒ 登记为**已知存量**，棘轮不许增。写 0 会当场红，
#                        写"下次再说"等于留一间没人看着的房间）。
CONSTANT_DEFAULT_EXPECTED: dict[str, int] = {
    "BLIND_RADIUS_M": 0,
    "BLIND_GRID_M": 6,
}
# 计数锚点文件：合成树里没有它就不判这一名（与 G-9/G-10 的"白名单文件不在本树则不判"同理）。
# `BLIND_RADIUS_M` 期望是 0 ⇒ **不设锚**：任何树里冒出一个常量默认值都要判红（fail-closed）。
CONSTANT_DEFAULT_ANCHORS: dict[str, str] = {
    "BLIND_GRID_M": "app/living_circle/blindspot.py",
}


def _names_under(node: ast.AST) -> "list[str]":
    """默认值表达式里出现的**常量名** —— 通用递归，不认包装形状（第十六轮 P2-3 再宽一次）。

    原先只认顶层 `Name`/`Attribute`（第一版只剥 `float/int/round`、一元、二元），于是这些形状
    仍出闸：`r=1000.0 if cap else BLIND_RADIUS_M`（`IfExp`）、`r={"m": BLIND_RADIUS_M}`、
    `r=(BLIND_RADIUS_M, 1)`、`def f(r=np.float64(BLIND_RADIUS_M))`（带模块前缀的转换）。
    它们和被撤掉的 `EVIDENCE_MARGIN_M = BLIND_RADIUS_M` 是同族：**值在 def/模块期就被焊死**。
    唯一跳过的是函数位（`f(...)` 里的 `f` 不是被焊进来的口径值）。
    ⚠️ 宽抓的代价由真树自证：加宽后 `BLIND_RADIUS_M` 仍恰 0、`BLIND_GRID_M` 仍恰 6
       ⇒ 没有误伤既有代码；这两条计数就是本检测器的规模自证。
    """
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    out: list[str] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(node, ast.Call) and child is node.func:
            continue
        out.extend(_names_under(child))
    return out


def _assignment_aliases(tree: ast.AST) -> "dict[str, str]":
    """模块/文件级**赋值别名**：`R = BLIND_RADIUS_M` ⇒ `{"R": "BLIND_RADIUS_M"}`。

    `_import_aliases` 只收 `import … as`，赋值别名是同一个洞的另一半：本仓那条
    `EVIDENCE_MARGIN_M = BLIND_RADIUS_M` 就是这么活的，G-11 一直看不见它。
    带注解的赋值（`M: float = BLIND_RADIUS_M`，第十六轮 P2-3）算同一种形状。
    只做「右值恰为一个名字」的简单赋值（多目标/解包/属性赋值/复合表达式不收）。
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if len(targets) != 1 or not isinstance(targets[0], ast.Name) or node.value is None:
            continue
        names = _names_under(node.value)
        if len(names) == 1 and names[0] != targets[0].id:
            out[targets[0].id] = names[0]
    return out


def _resolve_alias(name: str, aliases: "dict[str, str]") -> str:
    """沿赋值别名走到底（A→B→C ⇒ C），最多 8 跳后停在原地，防自指环。"""
    for _ in range(8):
        nxt = aliases.get(name)
        if nxt is None or nxt == name:
            return name
        name = nxt
    return name


def _constant_default_sites(tree: ast.AST, aliases: "dict[str, str]"):
    """G-11：产出 `[(行号, 函数名, 常量名)]` —— 任何函数默认值里出现的口径常量。

    五个形状都要吃到，少一个就是洞：
      ① `def f(r=BLIND_RADIUS_M)` ⇒ `Name`；
      ② `from scope import BLIND_RADIUS_M as R` 后 `def f(r=R)` ⇒ 经**别名表**认回原名；
      ③ `def f(r=scope.BLIND_RADIUS_M)` ⇒ `Attribute` 末段；
      ④ `def f(r=float(BLIND_RADIUS_M))` / `r=BLIND_RADIUS_M * 1.0` / `r=A if c else B` /
        `r={"m": BLIND_RADIUS_M}` / `r=np.float64(BLIND_RADIUS_M)` ⇒ `_names_under` 通用递归；
      ⑤ 模块级 `R = BLIND_RADIUS_M`（含带注解的 `M: float = …`）之后再 `def f(r=R)`
        ⇒ `_assignment_aliases` + 逐跳归一。
    `args.defaults` 只管普通形参，`*` 之后的 kwonly 形参在 `args.kw_defaults` —— 本仓真有
    这个形状（`scope.py` 的 `to_ring`/`area_km2`），漏了它等于给 kwonly 开门。
    `Lambda` 也扫（今日 app/** 无命中，留着是为了 `f = lambda r, x=BLIND_RADIUS_M: …` 长不回来）。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        a = node.args
        fname = getattr(node, "name", "<lambda>")
        for d in list(a.defaults) + list(a.kw_defaults):
            if d is None:
                continue
            for nm in _names_under(d):
                nm = _resolve_alias(nm, aliases)
                if nm in CONSTANT_DEFAULT_EXPECTED:
                    out.append((getattr(node, "lineno", 0), fname, nm))
    return out


def _iter_py(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _walk_with_func(tree: ast.AST):
    """产出 `(节点, 所在函数名)`；函数名供 G-1 做「唯一工厂」收窄。模块级记为 ''。"""
    out: list[tuple[ast.AST, str]] = []

    def rec(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            nf = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            out.append((child, nf))
            rec(child, nf)

    rec(tree, "")
    return out


def _called_name(node: ast.Call) -> str | None:
    """被调用者名：`CallGuard(...)` → `CallGuard`；`rg.CallGuard(...)` → `CallGuard`。

    ⚠️ 属性调用（带点号）**同样是直接构造**，漏掉它等于留一条「加个前缀就绕过」的通道。
    """
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _resolve_called(node: ast.Call, aliases: "dict[str, str]") -> "str | None":
    """被调者名，并把本文件的**函数名别名**换回原名。

    登记表（G-1 的工厂、G-9 的取证原语、G-10 的判定原语）全是按名字匹配的，
    所以「改个名再调」是最便宜的一条绕过路径 —— 归一后这条不成立。
    """
    name = _called_name(node)
    return None if name is None else aliases.get(name, name)


def _import_aliases(tree: ast.AST) -> "dict[str, str]":
    """本文件的**函数名别名**表：`from x import judge_once as probe` ⇒ `{"probe": "judge_once"}`。

    G-9/G-10 是按**名字**匹配调用点的：别名把名字换掉、调用还在，那道门就只剩装饰作用。
    只收函数名别名；`import numpy as np` 这类**模块**别名不必收 —— 属性形式
    `blindspot.judge_once(...)` 的末段本来就被 `_called_name` 读得到。
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.asname and a.asname != a.name:
                    out[a.asname] = a.name
    return out


def _getattr_literals(node: ast.AST) -> "tuple[str, ...]":
    """`getattr(obj, "judge_once")` 里的属性名字面量 —— 动态取用同样是调用。

    这是别名归一之外**另一个洞**：别名好歹要写 `as`，getattr 连导入都不用改。
    ⚠️ 效力上限：`globals()["judge_once"]`、`eval`、以及赋值别名
    `probe = judge_once` 之后再 `probe(...)` 仍看不见 —— 本道门拦的是**顺手**绕，
    不是铁了心绕；把这三种形态也吃掉会让守卫变成半个解释器。
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2):
        return ()
    arg = node.args[1]
    return (arg.value,) if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else ()


def _declaration_table_nodes(tree: ast.AST) -> "set[int]":
    """G-8：标出**模块顶层声明表**内部的所有字符串常量节点（按 id）。

    判据是 AST 形状而非文件路径：`UPPER_CASE 常量 = 字典/元组/集合字面量`（含 AnnAssign，
    如 `_COERCERS: Dict[str, …] = {…}`）。注册表、`_COERCERS`、`_STRUCTURED_SCHEMAS` 这些
    **登记处**天然合法；函数体里的同名键一律不合法 —— 与"哪个文件"无关，把表搬去别处
    照样合法，把散点写进注册表照样违例。
    """
    ok: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            val = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, val = [node.target.id], node.value
        else:
            continue
        if val is None:
            continue
        # 「声明表」= 下划线可选 + 全大写（`_COERCERS` / `DEST_KEYED_ROWS`）；小写变量不算
        if not any(n.replace("_", "").isupper() and any(c.isalpha() for c in n) for n in names):
            continue
        for sub in ast.walk(val):
            if isinstance(sub, ast.Constant):
                ok.add(id(sub))
    return ok


# ── G-5/G-6/G-7：流水线分层 import 方向（M3 模块提取后的机器纪律）──────────
# 流水线内层禁止回握上层：pipeline/** → orchestrator/runner 一律违例。
_FORBIDDEN_UPPER = ("app.core.orchestrator", "app.core.runner")
# 外壳只许依赖旅游引擎公共面；pipeline 下其余模块（research 子模块/living_circle）
# 不是它的依赖目标。
_ORCH_ALLOWED_PIPELINE = "app.core.pipeline.research.engine"
_RESEARCH_DIR = "app/core/pipeline/research/"
_RESEARCH_BACKEDGE_FILES = frozenset({"__init__.py", "engine.py"})


# ── G-8：结构化块键字面量只许待在声明表里 ────────────────────────────
# 键全集**从注册表取**，不在本脚本抄第二份（抄了就又是两处口径，Part A 的病根之一）。
_G8_BACKEND = Path(__file__).resolve().parents[1]


def _structured_key_universe() -> "frozenset[str]":
    """块键全集 = 各类型基础键 ∪ 各视角章挂载键 ∪ 已退役键。"""
    import sys
    if str(_G8_BACKEND) not in sys.path:
        sys.path.insert(0, str(_G8_BACKEND))
    from app.core import research_types as rt
    keys: set[str] = set(rt.PERSP_STRUCTURED_KEYS) | set(rt.DEPRECATED_CLAIM_FIELDS)
    for spec in rt.RESEARCH_TYPES.values():
        keys |= set(spec["structured_keys"])
        for p in (spec.get("perspectives") or {}).values():
            keys |= set(rt.section_structured_keys(p["section"]))
    return frozenset(keys)


# 现网遗留命中（G-8 落地时如实登记，**不是文件白名单**：按 `文件::所在函数` 精确到键与次数）。
# 语义是**棘轮**：多一处 ⇒ 红（新散点）；少一处 ⇒ 也红（那处已被改掉，条目必须从这里删掉）。
# ⇒ 本表只会变短；每次变短都是一次真实的去硬编码。
#
# 分组理由（三条不同性质，别混成一句"历史原因"）：
# ① `schemas.py coerce_*` —— 读 LLM 载荷的**自身包装子键**（`{"spot_ranking": [...]}`）。
#    该函数已在 `_COERCERS` 表里按同名键登记，这里是同名键的第二次出现；
#    彻底收敛要让 coerce 接住 key 入参，属独立重构，不在本道门的代价里。
# ② `charts_build.py` —— 图元与逐景点数据网格按块名 `structured.get(...)`。
#    Part A 已把**视角那一支**改成读 `checklist_key`（原 `elif section_id == "persp_family"`
#    即 G-8 要拦的形状）；剩余是 guide 基础块的既有分叉。
# ③ `engine.py` —— 主管线按块名挂阶段（`if "spot_ranking" in spec[...]` 的取数与回写）、
#    执行摘要的事实块。此处是 churn 最高的文件，动它须单独排期。
G8_BASELINE: "dict[str, dict[str, int]]" = {
    # ② 图元与逐景点数据网格按块名取数（**视角那一支已改读 checklist_key，不在表里**）
    "app/core/pipeline/research/charts_build.py::_build_data_grid": {
        "access_matrix": 1, "cost_breakdown": 1, "food_ranking": 1,
        "route_plan": 1, "shop_list": 1, "spot_ranking": 1},
    "app/core/pipeline/research/charts_build.py::_chart_access_radar": {"access_matrix": 1},
    "app/core/pipeline/research/charts_build.py::_chart_amenity_bar": {"amenity_checklist": 1},
    "app/core/pipeline/research/charts_build.py::_chart_cost_compose": {"cost_breakdown": 1},
    "app/core/pipeline/research/charts_build.py::_chart_risk_heat": {"risk_profile": 1},
    # ③ 主管线按块名挂阶段与摘要
    "app/core/pipeline/research/engine.py::_brief_facts_block": {
        "cost_breakdown": 1, "food_ranking": 1, "persp_rules": 1,
        "shop_list": 1, "spot_ranking": 1, "stay_options": 1},
    "app/core/pipeline/research/engine.py::research_pipeline": {
        "route_plan": 3, "shop_list": 4, "spot_ranking": 3, "spot_routes": 2},
    # ① 规整器读自身包装子键（已在 _COERCERS 按同名键登记）
    "app/core/schemas.py::coerce_access_matrix": {"access_matrix": 1},
    "app/core/schemas.py::coerce_amenity_checklist": {"amenity_checklist": 1},
    "app/core/schemas.py::coerce_cost_breakdown": {"cost_breakdown": 1},
    "app/core/schemas.py::coerce_food_ranking": {"food_ranking": 1},
    "app/core/schemas.py::coerce_risk_profile": {"risk_profile": 1},
    "app/core/schemas.py::coerce_route_plan": {"route_plan": 1},
    "app/core/schemas.py::coerce_shop_list": {"shop_list": 1},
    "app/core/schemas.py::coerce_spot_ranking": {"spot_ranking": 1},
    "app/core/schemas.py::coerce_spot_routes": {"spot_routes": 1},
    "app/core/schemas.py::coerce_stay_options": {"stay_options": 1},
}
# 基线总处数（**由表算出，不硬编码**：硬编码会在删条目时忘了改总数，让打印说谎）
G8_EXPECTED = sum(c for per_key in G8_BASELINE.values() for c in per_key.values())


def _resolve_relative(rel: str, level: int, module: str, imported_name: str) -> str | None:
    """把包内相对导入解析成绝对点路径；无法落到 app 包内时返回 None。

    rel 形如 app/core/pipeline/research/spots.py（4 级包路径）：
    level=1 锚定 research、2→pipeline、3→core、4→app。
    `from . import engine` 时 imported_name='engine'；其余尾部取 module 点路径。
    """
    parts = Path(rel).with_suffix("").parts
    try:
        idx = parts.index("app")
    except ValueError:
        return None
    base = parts[idx:len(parts) - (level - 1)]
    if not base:
        return None
    tail = module or imported_name
    return ".".join((*base, tail)) if tail else ".".join(base)


def _scan_layer_imports(rel: str, tree: ast.AST) -> list[str]:
    """G-5/G-6/G-7：只看 app/ 生产代码（测试经 engine 命名空间打桩，天然豁免）。"""
    if not rel.startswith("app/"):
        return []
    bad: list[str] = []

    in_pipeline = rel.startswith("app/core/pipeline/")
    is_orchestrator = rel == "app/core/orchestrator.py"
    in_research = rel.startswith(_RESEARCH_DIR)
    backedge_allowed = in_research and Path(rel).name in _RESEARCH_BACKEDGE_FILES

    for node in ast.walk(tree):
        targets: list[tuple[str, int]] = []
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # 相对导入逐个解析（from . import a, b 可能有多目标）
                for a in node.names:
                    resolved = _resolve_relative(rel, node.level, node.module or "", a.name)
                    if resolved:
                        targets.append((resolved, node.lineno))
            elif node.module:
                # 同时登记来源模块与其下每个别名点路径：
                # `from app.core import orchestrator` 必须与 `import app.core.orchestrator`
                # 同判（否则换个写法就绕过）。
                targets.append((node.module, node.lineno))
                for a in node.names:
                    targets.append((f"{node.module}.{a.name}", node.lineno))
        elif isinstance(node, ast.Import):
            for a in node.names:
                targets.append((a.name, node.lineno))

        for mod, lineno in targets:
            # G-5：pipeline 内层不得回握 orchestrator/runner
            if in_pipeline and (mod in _FORBIDDEN_UPPER
                                or any(mod.startswith(u + ".") for u in _FORBIDDEN_UPPER)):
                bad.append(
                    f"{rel}:{lineno}: G-5 pipeline 模块不得导入上层 `{mod}`"
                    "（流水线是被调度内层；回握外壳/调度器即成环形依赖）"
                )
            # G-6：orchestrator 只许依赖 research.engine 公共面
            # （`from ...engine import X` 派生出的 ...engine.X 别名点路径同属放行面）
            if is_orchestrator and (mod == "app.core.pipeline"
                                    or mod.startswith("app.core.pipeline.")):
                on_surface = (mod == _ORCH_ALLOWED_PIPELINE
                              or mod.startswith(_ORCH_ALLOWED_PIPELINE + "."))
                if not on_surface:
                    bad.append(
                        f"{rel}:{lineno}: G-6 orchestrator 的 pipeline 依赖只能打在 "
                        f"`{_ORCH_ALLOWED_PIPELINE}` 公共面，不得直达 `{mod}`"
                        "（内部符号经 engine re-export）"
                    )
            # G-7：research 子模块不得回握 engine（__init__/engine 自身豁免）
            if in_research and not backedge_allowed:
                if (mod == "app.core.pipeline.research.engine"
                        or (mod.startswith("app.core.pipeline.research")
                            and mod.split(".")[-1] == "engine")):
                    bad.append(
                        f"{rel}:{lineno}: G-7 research 子模块不得导入 engine 回边 `{mod}`"
                        "（engine 是编排顶层；子模块须只依赖同层/下层叶子）"
                    )
    return bad


def scan(root: Path) -> "tuple[list[str], int]":
    """返回 `(违例列表, 扫描文件数)`。"""
    bad: list[str] = []
    n = 0
    _from_iso_calls = [0]  # G-4：许可调用点的实际计数（用 list 便于闭包累加）
    _forensic_calls: dict[str, int] = {}  # G-9：唯一入口内每个取证原语的调用次数
    _judge_calls: dict[str, int] = {}     # G-10：每个判定原语的（登记内）调用次数
    _constant_defaults: dict[str, int] = {}   # G-11：每把尺的"常量默认值"计数
    _constant_where: dict[str, list] = {}     # G-11：报红时要指出是哪几处
    # G-8 命中按 `文件::函数` → 键 → 行号 收集（判红时要与棘轮基线比**次数**，不能见一个报一个）
    g8_hits: dict[str, dict[str, list[int]]] = {}
    # G-8 基线核对还须知道「这个函数在不在」—— 见下方 stale 判据的注释
    g8_funcs: dict[str, set[str]] = {}
    try:
        universe = _structured_key_universe()
    except Exception as e:  # noqa: BLE001
        # 取不到键全集**不等于没有违例**：静默放行会把这道门变成恒绿假护栏。
        bad.append(f"G-8 UNIVERSE 键全集取自注册表失败，本道门当前无效力：{type(e).__name__}: {e}")
        universe = frozenset()
    for p in _iter_py(root):
        rel = p.relative_to(root).as_posix()
        n += 1
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, UnicodeDecodeError) as e:  # noqa: BLE001
            # 不静默跳过：跳过即「守卫有洞」而无人知晓（静默失败是更坏的失败）
            bad.append(f"{rel}:{getattr(e, 'lineno', 0) or 0}: SYNTAX 无法解析（不静默跳过）：{e}")
            continue

        # G-5/G-6/G-7：分层 import 方向（与函数体无关，整文件一次扫）
        bad.extend(_scan_layer_imports(rel, tree))

        # G-8：块键字面量的合法栖身之所 = 模块顶层声明表（整文件算一次）
        table_nodes = _declaration_table_nodes(tree) if (universe and rel.startswith("app/")) else set()
        if rel.startswith("app/"):
            g8_funcs.setdefault(rel, set()).update(
                n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))

        in_tests = rel.startswith("tests/")
        # G-1/G-9/G-10 都按**名字**匹配 ⇒ 先把本文件的函数名别名（`import x as y`）收下来，
        # 调用点归一后再查表；否则「换个名再调」一行就把三道门同时绕过。
        aliases = _import_aliases(tree)
        # ── G-11：口径常量不许做函数默认值（整文件一次，形状见 `_constant_default_sites`）
        if rel.startswith("app/"):
            # 这道门额外吃**赋值别名**（模块级 `R = BLIND_RADIUS_M` 之后再 `def f(r=R)`）——
            # 第十五轮 P1-4：本仓那条 `EVIDENCE_MARGIN_M = BLIND_RADIUS_M` 就是这么躲过所有闸的。
            # G-9/G-10 按调用名匹配，赋值别名不构成绕路（调用名仍是原语名），故不合进上面那份。
            g11_aliases = {**_assignment_aliases(tree), **aliases}
            for ln, fn, cname in _constant_default_sites(tree, g11_aliases):
                _constant_defaults[cname] = _constant_defaults.get(cname, 0) + 1
                _constant_where.setdefault(cname, []).append(f"{rel}:{ln}({fn})")

        for node, func in _walk_with_func(tree):
            # ── G-8：块键字面量散进函数体 ────────────────────────────
            if (universe and rel.startswith("app/")
                    and isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in universe and id(node) not in table_nodes):
                g8_hits.setdefault(f"{rel}::{func}", {}).setdefault(node.value, []).append(node.lineno)

            # ── G-1：生产侧不得直接构造 CallGuard ──────────────────────
            if not in_tests and isinstance(node, ast.Call) and _resolve_called(node, aliases) == "CallGuard":
                allow = CALLGUARD_ALLOWLIST.get(rel, _ABSENT)
                if allow is _ABSENT:
                    bad.append(
                        f"{rel}:{node.lineno}: G-1 生产代码直接构造 CallGuard —— "
                        "只能经 `BaiduClient` 拿闸（共享闸是构造期不变量）"
                    )
                elif allow is not None and func not in allow:
                    bad.append(
                        f"{rel}:{node.lineno}: G-1 `CallGuard(...)` 出现在 {func or '<模块级>'}() 中；"
                        f"本文件只放行 {sorted(allow)}（否则「唯一工厂」退化成整文件豁免）"
                    )

            # ── G-4：SpatialScope.from_iso 的唯一调用点 ───────────────
            if not in_tests and isinstance(node, ast.Call):
                f = node.func
                if (
                    isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "SpatialScope"
                    and f.attr == "from_iso"
                ):
                    allow = FROM_ISO_ALLOWLIST.get(rel, _ABSENT)
                    if allow is _ABSENT or func not in allow:
                        bad.append(
                            f"{rel}:{node.lineno}: G-4 `SpatialScope.from_iso(...)` 出现在 "
                            f"{func or '<模块级>'}()；只能由 `data_source.scope_or_degrade` 调用 "
                            "（其余入口直接选环 ⇒ 空等时圈时降级不可达，根因 B 复发）"
                        )
                    else:
                        _from_iso_calls[0] += 1

            # ── G-9：取证原语只许在唯一编排入口里被调（app/** 生产侧）──
            if rel.startswith("app/") and isinstance(node, ast.Call):
                called = _resolve_called(node, aliases)
                if called in FORENSIC_PRIMITIVES:
                    allow = FORENSIC_ALLOWLIST.get(rel, _ABSENT)
                    if allow is _ABSENT or func not in allow:
                        bad.append(
                            f"{rel}:{node.lineno}: G-9 取证原语 `{called}(...)` 被 "
                            f"{func or '<模块级>'}() 直接调用 —— 生产侧唯一允许调它的地方是 "
                            "`data_source.live_forensic_steps`；在别处串一遍这些原语就是"
                            "第四份取证编排（降级分流、partial 披露、取证回合都到不了它）"
                        )
                    else:
                        _forensic_calls[called] = _forensic_calls.get(called, 0) + 1

            # ── G-10：判定只许从唯一入口走（app/** 生产侧）──────────
            if rel.startswith("app/") and isinstance(node, ast.Call):
                called = _resolve_called(node, aliases)
                if called in JUDGE_EXPECTED_CALLS:
                    allow = JUDGE_ALLOWLIST.get(rel, _ABSENT)
                    if allow is _ABSENT or func not in allow:
                        bad.append(
                            f"{rel}:{node.lineno}: G-10 判定原语 `{called}(...)` 被 "
                            f"{func or '<模块级>'}() 直接调用 —— 逐格判定只许从 "
                            "`blindspot.judge_once` 起（它是唯一生产入口，产物 `Judgement` "
                            "带着掩码穿过组装层）；`cover_matrix`/`find_blindspots*` 是留给"
                            "测试的旧报告视图，生产侧调用者必须为 0"
                        )
                    else:
                        _judge_calls[called] = _judge_calls.get(called, 0) + 1

            # ── G-9/G-10 的**动态取用**面：getattr(obj, "原语名") ──────
            # 别名归一吃掉的是 `import … as …`；`getattr` 连导入都不改就直接取函数，
            # 名字匹配看不见。这里不并入计数（那等于给它一条合法栖身之所），一律判红：
            # 生产侧没有任何理由动态取用这两个登记表的成员。
            if rel.startswith("app/"):
                for lit in _getattr_literals(node):
                    if lit in FORENSIC_PRIMITIVES or lit in JUDGE_EXPECTED_CALLS:
                        bad.append(
                            f"{rel}:{node.lineno}: G-9/G-10 原语 `{lit}` 经 "
                            f"getattr(..., {lit!r}) 动态取用 —— 登记表按名字匹配调用点，"
                            "动态取用把名字藏进字符串就等于换了个入口重启编排/第二遍判定"
                            "（要调用就按名字显式调用，让它落在登记表里）"
                        )

            # ── G-2：tests/ 之外不得出现 allow_ungated= 关键字实参 ────
            if not in_tests and isinstance(node, ast.keyword) and node.arg == "allow_ungated":
                bad.append(
                    f"{rel}:{node.lineno}: G-2 `allow_ungated=` 只允许出现在 tests/**"
                    "（进程级闸豁免不得进入生产代码）"
                )

            # ── G-3：tests/ 的 assert **被测表达式**内不得读挂钟 ───────
            # 只看 `Assert.test`：`Assert.msg` 是解释文案，引用被禁字样是它的正当用法。
            if in_tests and isinstance(node, ast.Assert):
                for sub in ast.walk(node.test):
                    if not isinstance(sub, ast.Call):
                        continue
                    f = sub.func
                    if (
                        isinstance(f, ast.Attribute)
                        and isinstance(f.value, ast.Name)
                        and (f.value.id, f.attr) in CLOCK_READS
                    ):
                        bad.append(
                            f"{rel}:{sub.lineno}: G-3 assert 表达式内读挂钟（{f.value.id}.{f.attr}）—— "
                            "用注入的 clock 或夹具算出的字面量（断言不得依赖宿主机时钟）"
                        )
    # G-4 计数：许可入口内也只允许一处 —— 「唯一出口」必须机器可校验。
    # 期望值按**扫描树里真实存在的白名单文件**计（测试注入的局部树只含其中一个文件，
    # 若硬编码成常量会让「合法必绿」对照恒红 —— 那正是逼人关掉护栏的典型假阳性）。
    expected = sum(1 for rel in FROM_ISO_ALLOWLIST if (root / rel).is_file())
    if _from_iso_calls[0] != expected:
        bad.append(
            f"G-4 `SpatialScope.from_iso(...)` 的许可调用点共 {_from_iso_calls[0]} 处，"
            f"必须恰为 {expected} 处（多了 = 又有人在别处选环；少了 = 白名单失配）"
        )
    # G-9 计数：唯一入口内每个取证原语**恰调一次**。两个方向都要判 ——
    # 多了是同一步跑两遍（例如把采集重复调度）；**少了是生成器不再做那一步**
    # （静默少做比响亮多做更难发现，也正是「抄三份时各自漏一点」的起点）。
    # 与 G-4 同源：白名单文件不在本树（测试注入局部合成树）时不作判定。
    if (root / "app/living_circle/data_source.py").is_file():
        off = {
            name: _forensic_calls.get(name, 0)
            for name in FORENSIC_PRIMITIVES
            if _forensic_calls.get(name, 0) != FORENSIC_EXPECTED_CALLS_PER_PRIMITIVE
        }
        if off:
            bad.append(
                "G-9 取证原语在唯一入口 `live_forensic_steps` 内的调用次数必须恰为 "
                f"{FORENSIC_EXPECTED_CALLS_PER_PRIMITIVE}，实得 {off}"
                "（多了 = 同一步跑两遍；少了 = 那一步已从编排里掉出去）"
            )
    # G-11 计数：口径常量的"函数默认值"站点数逐名比对（期望值见 `CONSTANT_DEFAULT_EXPECTED`）。
    # 双向都判：多了 = 有人又把口径焊进 def（改源头不跟着变的那类缺陷就这么长回来）；
    # 少了 = 已清零的存量又被写回字面量，或登记过期（`BLIND_GRID_M` 那 6 处一旦被搬走，
    # 这里的 6 就该一起降下来，否则门上一条永不触发的豁免）。
    for cname, want in CONSTANT_DEFAULT_EXPECTED.items():
        anchor = CONSTANT_DEFAULT_ANCHORS.get(cname)
        if anchor is not None and not (root / anchor).is_file():
            continue   # 合成树里没有该尺的合法栖身文件 ⇒ 这一名不判（与 G-9/G-10 同理）
        got = _constant_defaults.get(cname, 0)
        if got != want:
            bad.append(
                f"G-11 口径常量 `{cname}` 被用作函数默认值的站点数 = {got}，必须恰为 {want}"
                f"（实得位置 {_constant_where.get(cname) or '—'}）。默认值在 **def 期**求值、"
                "被捕获进函数对象 ⇒ 改口径对象不会让这条默认路径跟着变；要省略就写哨兵 "
                "`None` 并在调用时经 `scope.blind_radius_or` 之类决议（口径值的唯一住所是 "
                "`caliber.ReachCaliber`）"
            )
    # G-10 计数：**逐名**比对（期望值按改后实测填，见 `JUDGE_EXPECTED_CALLS` 上方注释）。
    # 双向都判：多了 = 有人又开一处判定；少了 = 登记的那一处已经不存在（表过期，
    # 留着就是一条没人再触发的豁免 —— 与 G-8 棘轮同一种腐化）。
    if (root / "app/living_circle/blindspot.py").is_file():
        off = {
            name: (_judge_calls.get(name, 0), want)
            for name, want in JUDGE_EXPECTED_CALLS.items()
            if _judge_calls.get(name, 0) != want
        }
        if off:
            bad.append(
                "G-10 判定原语的调用数与登记表不符（实得, 期望）："
                f"{off} —— 表里的期望值是按**改后实测**钉的，动了判定入口就回来一起改；"
                "`cover_matrix`/`find_blindspots*` 的期望是 0，非 0 意味着生产侧又开了一处逐格判定"
            )
    # G-8 棘轮：与基线比**次数**，两个方向都要报 ——
    # 多了是新散点（本道门的存在理由）；少了是基线过期（不报就会长出一条"永远为真"的豁免，
    # 与文件白名单同一种腐化，只是慢一些）。
    if universe:
        for group, per_key in sorted(g8_hits.items()):
            rel, _, func = group.partition("::")
            base = G8_BASELINE.get(group, {})
            for key in sorted(per_key):
                lines = sorted(per_key[key])
                for ln in lines[base.get(key, 0):]:
                    bad.append(
                        f"{rel}:{ln}: G-8 块键字面量 `{key}` 出现在函数体 "
                        f"{func or '<模块级>'}() —— 键名归属注册表/声明表，"
                        "散进函数体即按块名分叉（加一块类型要改一片代码）"
                    )
        for group in sorted(G8_BASELINE):
            rel, _, func = group.partition("::")
            if rel not in g8_funcs:
                continue  # 局部夹具树不含该文件 ⇒ 不作判定（同 G-4 期望值纪律）
            if func and func not in g8_funcs[rel]:
                # ⚠️ 只在「函数还在」时核对基线，是**刻意的让步**：测试注入的局部树会拿
                # 真仓库路径写桩文件（`test_guard_construction_lint.py` 的 M3 用例就造了
                # 一个只有 4 行的 engine.py），按文件计会凭空报 10 条假阳性 —— 那正是
                # 「逼人关掉护栏」的失败模式。让掉的只有「函数被改名/删掉后仍留着条目」这一
                # 种**记账噪声**；真正的防线（新增散点必红）不受影响：散点若跟着改名一起
                # 搬走，它会落进一个基线里没有的新组 ⇒ 照样红。
                continue
            obs = g8_hits.get(group, {})
            for key, want in sorted(G8_BASELINE[group].items()):
                got = len(obs.get(key, []))
                if got >= want:
                    continue
                bad.append(
                    f"{rel}: G-8 棘轮基线登记了 {want} 处 `{key}`，实际只剩 {got} 处 —— "
                    f"该处已去硬编码？请把 `G8_BASELINE[\"{group}\"]` 里的这条删掉"
                    "（基线只许变短，留着过期条目等于留着一条没人再触发的豁免）"
                )
    return bad, n


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="γ 静态守卫：进程级治理不得被绕过（AST，非正则）")
    ap.add_argument("--root", default=None, help="扫描根（默认：本脚本上一级，即 backend/）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"✗ 扫描根不存在：{root}", file=sys.stderr)
        return 1

    bad, n = scan(root)
    if bad:
        print(f"✗ γ 静态守卫：{len(bad)} 条违例（共扫 {n} 个 .py，root={root}）", file=sys.stderr)
        for line in bad:
            print(line, file=sys.stderr)
        return 1

    # 通过时也**可见打印**：否则「没输出」与「没跑」无法区分 —— 静默通过本身就是一种假绿
    print(
        f"✓ γ 静态守卫通过：{n} 个 .py（root={root}）· "
        "G-1 生产侧无直接构造 CallGuard · G-2 allow_ungated 仅在 tests/ · G-3 tests 断言未读挂钟 "
        f"· G-4 SpatialScope.from_iso 恰 {FROM_ISO_EXPECTED_CALLS} 处调用 · "
        "G-5 pipeline 无上层回握 · G-6 orchestrator 只依赖 engine 公共面 · G-7 research 无 engine 回边 "
        f"· G-8 块键字面量零新增散点（棘轮基线恰 {G8_EXPECTED} 处）"
        f"· G-9 取证编排唯一（{len(FORENSIC_PRIMITIVES)} 个原语各恰 "
        f"{FORENSIC_EXPECTED_CALLS_PER_PRIMITIVE} 处调用，只在 `live_forensic_steps` 内）"
        f"· G-10 判定唯一入口（{len(JUDGE_EXPECTED_CALLS)} 个判定原语逐个核对实测期望 "
        f"{JUDGE_EXPECTED_CALLS}）"
        f"· G-11 口径常量不作函数默认值（逐名实测 {CONSTANT_DEFAULT_EXPECTED}）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

白名单（**仅 G-1**，两处，都必须存在）
------------------------------------
- `app/living_circle/request_guard.py` —— 闸的**定义模块**（整文件放行）；
- `app/living_circle/baidu_client.py` —— **唯一工厂**，但**只放行 `_default_guard` 函数体内**。
  ⚠️ 在该文件的**其它函数**里构造 ⇒ **照红**：否则「唯一工厂」会退化成「整文件豁免」，
  守卫随之失去意义。文件被改名 / 函数被改名 ⇒ 白名单失配 ⇒ **响亮报错**（这是正确的失效方向）。

⚠️ 两处刻意的不对称（都是实测踩出来的，别「修」掉）
--------------------------------------------------
1. **G-3 只扫 `Assert.test`，不扫 `Assert.msg`**：`msg` 是**给人看的解释文案**，
   「若实现退回宿主机本地 `date.today()`，此处必红」这种**引用**正是它该出现的地方
   （本仓 `tests/test_rate_limiter_shared.py:394` 即活实例）。扫 `msg` 会把它误判成违例。
2. **G-1 的作用域是「`tests/**` 之外」而不是方案原文的「`app/**`」**：本仓生产侧还有
   `scripts/**`（`make_fixture_points.py` 就在那里真实构造 `BaiduClient`），
   而「新绕过写不进来」要求覆盖**未来新增的顶层目录**。作用域取严（零当前代价）。

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


def scan(root: Path) -> "tuple[list[str], int]":
    """返回 `(违例列表, 扫描文件数)`。"""
    bad: list[str] = []
    n = 0
    _from_iso_calls = [0]  # G-4：许可调用点的实际计数（用 list 便于闭包累加）
    for p in _iter_py(root):
        rel = p.relative_to(root).as_posix()
        n += 1
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, UnicodeDecodeError) as e:  # noqa: BLE001
            # 不静默跳过：跳过即「守卫有洞」而无人知晓（静默失败是更坏的失败）
            bad.append(f"{rel}:{getattr(e, 'lineno', 0) or 0}: SYNTAX 无法解析（不静默跳过）：{e}")
            continue

        in_tests = rel.startswith("tests/")
        for node, func in _walk_with_func(tree):
            # ── G-1：生产侧不得直接构造 CallGuard ──────────────────────
            if not in_tests and isinstance(node, ast.Call) and _called_name(node) == "CallGuard":
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
        f"· G-4 SpatialScope.from_iso 恰 {FROM_ISO_EXPECTED_CALLS} 处调用"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""绕闸静态守卫：生产代码不得给 `BaiduClient` 传私有 `guard`。

为什么这是根因级守卫而不是风格检查（`baidu_client.py:9,94-95` 已明文记录过这个坑）：
共享治理（per-AK 的 QPS 闸 `_limiter_cache` 与日预算 `_daily_cache`）只在
`_default_guard(ak)` 这条路径上挂进去。而构造签名是

    self.guard = guard if guard is not None else _default_guard(self.ak)

⇒ **只要调用方自带 `guard=`，整条 `_default_guard` 就不会被调用**，该 client 拿到一份
私有闸：它自己的限速/预算与全账号共享的那份完全无关。多一个这样的调用点，就等于在
共享治理上开一个洞 —— 而且**静默**：日额度设成 0 时它照样绕掉共享 QPS 闸。

地标 → 生活圈体检（第一片）会新增百度调用点，故先把这条钉死：基线 **0**，只降不升。
"""
import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
# 基线：当前生产代码里 0 处私有 guard。新增即红；若确属必要，须在此登记并说明理由。
BASELINE_BYPASS_SITES = ()


def _baidu_client_calls_with_private_guard():
    """AST 扫 app/**/*.py，返回 `BaiduClient(..., guard=...)` 的 (文件, 行号)。"""
    hits = []
    for py in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "BaiduClient":
                continue
            if any(kw.arg == "guard" for kw in node.keywords):
                hits.append((str(py.relative_to(APP_DIR)), node.lineno))
    return hits


def test_app_tree_is_actually_scanned():
    """守卫自检（S-0 同类）：扫不到任何 .py 就说明路径错了、守卫在空转。

    本仓已因「守卫找不到目标就静默通过」吃过教训，故先断言扫描面非空，
    再断言已知调用点存在（这三处是 `_default_guard` 正常路径，不带私有 guard）。
    """
    files = list(APP_DIR.rglob("*.py"))
    assert len(files) > 20, f"扫描面异常（{len(files)} 个文件）—— 守卫已失效"

    scanned = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert "BaiduClient(" in scanned, "扫不到 BaiduClient 调用点 —— 判据已过期，须重指"
    assert "_default_guard" in scanned, "扫不到 _default_guard —— 共享治理接缝已改名"


def test_no_production_call_site_bypasses_shared_guard():
    hits = set(_baidu_client_calls_with_private_guard())
    new = hits - set(BASELINE_BYPASS_SITES)
    assert not new, (
        "发现新建 BaiduClient 时自带私有 guard 的生产调用点："
        f"{sorted(new)}。这会整条跳过 _default_guard，使该 client 脱离共享 QPS 闸与"
        "日预算治理（baidu_client.py:9 记录过的后门）。地标体检等新链路请复用默认闸，"
        "确需自定义时必须先在本文件登记并说明理由。"
    )


def test_baseline_is_only_allowed_to_shrink():
    """棘轮只降不升：登记的基线站点若已消失，要求摘除登记。"""
    alive = set(_baidu_client_calls_with_private_guard())
    stale = set(BASELINE_BYPASS_SITES) - alive
    assert not stale, f"基线里这些绕闸点已不存在，请摘除登记：{sorted(stale)}"

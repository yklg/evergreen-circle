"""J6 · J3（批次 3）：γ 静态守卫 `scripts/check_guard_construction.py` 的**等价类**测试。

被测范围：γ 的三条规则（G-1 生产侧不得直接构造 `CallGuard` · G-2 `allow_ungated=` 只许
`tests/**` · G-3 `tests/**` 的 assert 被测表达式内不得读挂钟）。
判据：**违规必红 且 合法必绿**，两半都要（只测一半会得到恒红或恒绿的假护栏）。

⚠️ 为什么用 **subprocess 跑真实 CLI**，而不是 import 进来调内部函数：
**退出码与 `路径:行号: 规则号` 输出格式本身就是契约的一部分** —— CI 与人都只看这两样。
若只测函数，「脚本入口坏了（`--root` 没接线 / `sys.exit` 漏了）但函数还对」这类缺陷测不出来。

⚠️ 三处**必须不报**的等价类（不是可选项，它们各自钉住一个真实误判风险）：
1. 定义模块 `request_guard.py` 与唯一工厂 `_default_guard` 内的 `CallGuard(`；
2. **docstring / 字符串字面量 / 类型注解**里的 `CallGuard` 字样（本仓 `baidu_client.py:10/145` 有活实例）
   —— 用**正则**实现就会在这里误判 ⇒ 本条即是「不得用正则」的守卫；
3. `assert ..., "msg"` 的 **msg** 里出现挂钟（本仓 `tests/test_rate_limiter_shared.py:394` 是活实例）
   —— 故 G-3 只扫 `Assert.test`：msg 是给人看的解释文案，**引用**被禁字样与**把「今天」打进失败消息**
   都是它的正当用法（对应夹具里的 ⑤a 字样 / ⑤b 真实调用两种形态）。
"""
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_SCRIPT = _BACKEND / "scripts" / "check_guard_construction.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    """以给定 root 跑一次真实 CLI（退出码 + 输出即被测契约）。"""
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--root", str(root)],
        capture_output=True, text=True, timeout=120, cwd=str(root),
    )


def _tree(base: Path, files: dict) -> Path:
    for rel, body in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return base


# ── J6 · 合法必绿（6 类等价类，合并成一棵树一次跑 —— 误判会在输出里点名文件）──────
def test_j06_passes_on_every_legitimate_shape(tmp_path):
    """J6（🟢）：六类**合法**形态**一条都不许报**。

    ① 闸的定义模块（整文件放行）；② 唯一工厂 `_default_guard` 内构造；
    ③ docstring / 字符串字面量 / 类型注解里的字样（**正则实现会在此误判**）；
    ④ `tests/**` 内的 `allow_ungated=True`；⑤ `assert …, "msg"` 的 msg 里引用
    `date.today()` 字样（**扫 msg 的实现会在此误判**）；⑥ 断言用**夹具字面量**（正确形态）。
    """
    root = _tree(tmp_path / "ok", {
        # ① 定义模块
        "app/living_circle/request_guard.py": (
            "class CallGuard:\n"
            "    def __init__(self, **kw):\n"
            "        pass\n"
            "\n"
            "\n"
            "def make():\n"
            "    return CallGuard()\n"
        ),
        # ② 唯一工厂
        "app/living_circle/baidu_client.py": (
            "def _default_guard():\n"
            "    return CallGuard()\n"
        ),
        # ③ 字样出现在 docstring / 字符串字面量 / 类型注解里 —— 必须不报
        "app/foo.py": (
            '"""模块 docstring 里提到 CallGuard( 与 allow_ungated=True —— 这是**引用**，必须不报。"""\n'
            "from typing import Optional\n"
            "\n"
            "NOTE = 'CallGuard() 只许出现在工厂里；allow_ungated=True 只许在 tests/'\n"
            "\n"
            "\n"
            "def f(guard: Optional['CallGuard'] = None) -> 'CallGuard':  # 注解里也有字样\n"
            "    return guard\n"
        ),
        # ④ tests/ 内豁免 —— 合法
        "tests/test_a.py": (
            "def make(**kw):\n"
            "    return kw\n"
            "\n"
            "\n"
            "def test_a():\n"
            "    assert make(allow_ungated=True)['allow_ungated'] is True\n"
        ),
        # ⑤ assert 的 **msg** 里出现挂钟 —— **两种形态都必须不报**：
        #    ⑤a 字符串里的**字样**（本仓 tests/test_rate_limiter_shared.py:394 是活实例）；
        #    ⑤b msg 里的**真实调用**（f-string）—— 失败时把「今天」打进消息是正当用法。
        #    ⚠️ 光有 ⑤a 判别不了这个作用域：字样是 `ast.Constant`，扫不扫 msg 都一样
        #    ⇒ 必须补 ⑤b，本类才真正钉住「G-3 只扫 `Assert.test`」。
        "tests/test_b.py": (
            "from datetime import date\n"
            "\n"
            "\n"
            "def test_b():\n"
            "    assert 1 == 1, \"若实现退回宿主机本地 date.today()，此处必红\"\n"
            "\n"
            "\n"
            "def test_b2(got='2026-09-22'):\n"
            "    assert got == '2026-09-22', f\"口径漂了：今天 {date.today()} vs {got}\"\n"
        ),
        # ⑥ 断言用夹具算出的字面量 —— 正确形态
        "tests/test_c.py": (
            "from datetime import datetime, timezone\n"
            "\n"
            "\n"
            "def test_c():\n"
            "    assert datetime(2026, 9, 22, tzinfo=timezone.utc).date().isoformat() == '2026-09-22'\n"
        ),
    })
    cp = _run(root)
    assert cp.returncode == 0, (
        f"合法形态被误判为违例（G-x 规则过严 / 用了正则 / 扫了 msg）：\n"
        f"stdout={cp.stdout!r}\nstderr={cp.stderr!r}"
    )
    assert cp.stderr == "", f"通过时不得往 stderr 写东西：{cp.stderr!r}"
    assert "✓" in cp.stdout, "通过时必须**可见打印**（否则「没输出」与「没跑」不可区分）"
    assert "6 个 .py" in cp.stdout, (
        f"六棵夹具树必须**全被扫到**（数量对不上说明遍历剪枝过猛 / 漏了目录）：{cp.stdout!r}"
    )


# ── J6 / J3 · 违规必红（逐条点名规则号与行号）────────────────────────────
def test_j06_violation_g1_direct_construction_outside_tests(tmp_path):
    """G-1：生产侧直接 `CallGuard()` ⇒ 红，且输出含 `文件:行号: G-1`。"""
    root = _tree(tmp_path / "bad_g1", {"app/foo.py": "def f():\n    return CallGuard()\n"})
    cp = _run(root)
    assert cp.returncode == 1, f"应退出码 1：stdout={cp.stdout!r}"
    assert "app/foo.py:2: G-1" in cp.stderr, cp.stderr


def test_j06_violation_g1_attribute_call_is_not_a_loophole(tmp_path):
    """G-1：`rg.CallGuard(...)`（属性调用）**同样是直接构造** —— 加个前缀不许绕过。"""
    root = _tree(tmp_path / "bad_g1b", {"app/foo.py": (
        "import app.living_circle.request_guard as rg\n"
        "\n"
        "\n"
        "def f():\n"
        "    return rg.CallGuard()\n"
    )})
    cp = _run(root)
    assert cp.returncode == 1
    assert "app/foo.py:5: G-1" in cp.stderr, f"属性调用漏检 ⇒ 一条「加前缀就绕过」的通道：{cp.stderr!r}"


def test_j06_violation_g1_factory_allowlist_is_not_whole_file(tmp_path):
    """G-1：`baidu_client.py` 的白名单**只放行 `_default_guard`** ——

    在**同文件其它函数**里构造 ⇒ 照红。否则「唯一工厂」退化成「整文件豁免」，
    守卫失去意义（这条同时是把白名单做得**比方案原文更窄**的理由的守卫）。
    """
    root = _tree(tmp_path / "bad_g1c", {"app/living_circle/baidu_client.py": (
        "def _default_guard():\n"
        "    return CallGuard()\n"
        "\n"
        "\n"
        "def sneaky():\n"
        "    return CallGuard()\n"
    )})
    cp = _run(root)
    assert cp.returncode == 1, "整文件豁免 ⇒ sneaky() 不被抓"
    assert "baidu_client.py:6: G-1" in cp.stderr, cp.stderr
    assert "baidu_client.py:2: G-1" not in cp.stderr, f"白名单内的 _default_guard 不许报：{cp.stderr!r}"


def test_j06_violation_g2_exemption_outside_tests(tmp_path):
    """G-2：`scripts/**`（tests 之外）出现 `allow_ungated=True` ⇒ 红。

    ⚠️ 本仓生产侧真实存在 `scripts/`（`make_fixture_points.py` 就在那里构造 `BaiduClient`）
    —— 故 G-2 的作用域是「`tests/**` 之外」，而不是方案原文的「除 tests 外只点名 app/」。
    """
    root = _tree(tmp_path / "bad_g2", {"scripts/probe.py": (
        "from app.living_circle.baidu_client import BaiduClient\n"
        "\n"
        "\n"
        "def f():\n"
        "    return BaiduClient(ak='k', allow_ungated=True)\n"
    )})
    cp = _run(root)
    assert cp.returncode == 1
    assert "scripts/probe.py:5: G-2" in cp.stderr, cp.stderr


def test_j03_violation_clock_read_inside_assert_expression(tmp_path):
    """J3（🔴 · P0）：`tests/**` 的 assert **被测表达式**内读挂钟 ⇒ 三种写法**都要红**。

    被测范围：G-3 的判据覆盖面（`date.today()` / `datetime.now()` / `datetime.today()`）。
    ⚠️ `datetime.today()` 是**同族成员**，一并禁（同族要同批，否则缺陷从没被覆盖的那个进去）。
    """
    root = _tree(tmp_path / "bad_g3", {
        "tests/test_d.py": (
            "from datetime import date\n"
            "\n"
            "\n"
            "def test_d():\n"
            "    got = '2026-09-22'\n"
            "    assert got == date.today().isoformat()\n"
        ),
        "tests/test_n.py": (
            "from datetime import datetime\n"
            "\n"
            "\n"
            "def test_n():\n"
            "    got = '2026-09-22'\n"
            "    assert got == datetime.now().date().isoformat()\n"
        ),
        "tests/test_t.py": (
            "from datetime import datetime\n"
            "\n"
            "\n"
            "def test_t():\n"
            "    got = '2026-09-22'\n"
            "    assert got == datetime.today().date().isoformat()\n"
        ),
    })
    cp = _run(root)
    assert cp.returncode == 1, "assert 表达式内读挂钟未被拦下"
    for frag in ("tests/test_d.py:6: G-3", "tests/test_n.py:6: G-3", "tests/test_t.py:6: G-3"):
        assert frag in cp.stderr, f"漏检 {frag}：\n{cp.stderr}"


# ── 把 γ 从「一个脚本」变成「本仓的纪律」的那一步 ──────────────────────
def test_j06_this_repository_currently_passes_gamma():
    """**本仓当前必须合法**（默认 root = `backend/`，不依赖 cwd）。

    ⚠️ 这条的价值正在于「将来新增真实违例时它会红」—— 没有它，γ 就只是一个**没人跑**的脚本
    （方案 §12.4 选 ① 的唯一代价就是「不跑就等于没做」）。注意本用例同时钉住
    「默认 root 由脚本自身位置推导，而非 cwd」这一接线。
    """
    cp = subprocess.run(
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, timeout=180, cwd=str(_BACKEND)
    )
    assert cp.returncode == 0, f"本仓存在 γ 违例（这不是测试坏了，是仓库里真的有了）：\n{cp.stderr}"
    assert "✓" in cp.stdout, f"通过时必须可见打印：{cp.stdout!r}"

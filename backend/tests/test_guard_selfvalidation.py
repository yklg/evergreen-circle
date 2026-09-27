r"""GV · 元守卫自证：「守卫在对象消失时，会不会还报绿」。

## 为什么需要这一族

本仓已有范式级守卫：`scripts/check_guard_construction.py` 与它的等价类套件
`test_guard_construction_lint.py` —— 违规必红、合法必绿、通过时可见打印、扫描计数下界、
白名单收窄到函数体。但**同一套纪律没有推广到其余守卫**，本族就是把那套纪律当作被测契约，
钉在另外三处守卫上。

判据形态刻意取「跑真实 CLI / 真实用例」而非 import 内部函数：**退出码与输出文本本身就是
契约的一部分**（CI 与人都只看这两样），这与 `test_guard_construction_lint.py` 的理由同源。

## 修复记录（2026-09-26 · 下列 4 处假绿/死账均已落地）

| 被测守卫 | 修前实测 | 现在的行为 |
|---|---|---|
| `test_api_mirror_guard.py::test_api_mirror_common_modules_exist` | `api/` 不存在 → glob 空集 → `absent==[]` → **1 passed** | 补 exists-skip + 「扫到 0 文件即红」，现为 `1 skipped` |
| `scripts/check_app_mirror.sh` | 先哭 `diff: api/app: No such file or directory`，再打「✓ 镜像一致」并 exit 0（`\|\| true` 把退出码吞进命令替换，`set -e`/`pipefail` 都救不回） | 前置 `-d api/app` 判据，缺失时打 SKIP 且**不打 ✓** |
| `.github/workflows/ci.yml` 的 api/ 运行时校验 step | `sys.path.insert(0,'../api')` 指向不存在目录，而 `python -c` 已把 cwd(`backend/`) 放进 path ⇒ 导入的是 backend 自己（拿后端验证后端） | step 内先 `test -d ../api`，缺失时显式 SKIP |
| `test_semantic_residue.py` 的 `_ALLOW` | 22 条里 2 条零命中（字样已消失 / 文件已移入 `_travel_pending/` 致豁免永不命中） | 死豁免已删，并由该文件新增的 `test_every_allowlist_entry_fires_at_least_once` 与 `test_scan_trees_actually_contain_files` 机器保证不回潮 |

> 两侧 CI 定义（`.github/workflows/ci.yml` 与 `.workflow/ci.yml`）旧注释都写「保持两边一致」，
> 实测 Gitee 侧本就是真源的**子集**（无 api/ step、无 docker job）⇒ 注释已改成如实记录差异。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]          # skip/backend
_ROOT = _BACKEND.parent                                  # 仓库根 skip/
_MIRROR_NODE = "tests/test_api_mirror_guard.py::test_api_mirror_common_modules_exist"


def _run_pytest_node(node: str) -> subprocess.CompletedProcess:
    """真实跑一条既有用例 —— 它的「红/绿/skip」本身就是被测契约。"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header", "-rs",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=180, cwd=str(_BACKEND),
    )


def _run_shell_guard() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_ROOT / "scripts" / "check_app_mirror.sh")],
        capture_output=True, text=True, timeout=120, cwd=str(_ROOT),
    )


def test_gv_mirror_exist_check_does_not_silently_pass_when_api_absent():
    """比对对象不存在时，守卫只能 skip 或 fail，不能「通过」。

    「没跑」与「跑过且通过」必须可区分 —— 静默通过本身就是一种假绿。
    """
    assert not (_ROOT / "api").exists(), (
        "前提已变：`api/` 又出现了。本用例的判据（缺失时不得报通过）不再适用，"
        "应改为在临时树里造两种形态分别验证。"
    )
    cp = _run_pytest_node(_MIRROR_NODE)
    silent_pass = cp.returncode == 0 and "skipped" not in cp.stdout
    assert not silent_pass, f"api/ 缺失却报通过（假绿回潮）：\n{cp.stdout}"
    assert "skipped" in cp.stdout or cp.returncode != 0


def test_gv_shell_mirror_guard_does_not_claim_success_on_missing_api():
    """`check_app_mirror.sh` 在无镜像可比时只能显式 SKIP，不得打「✓ 一致」。"""
    assert not (_ROOT / "api" / "app").exists(), (
        "前提已变：api/app 又出现了，本用例判据需重新评估。"
    )
    cp = _run_shell_guard()
    assert "✓" not in cp.stdout, f"无对象可比却宣称一致：{cp.stdout!r}"
    assert "SKIP" in cp.stdout or cp.returncode != 0, (
        f"既没打 SKIP 也没非零退出 —— 与「没跑」不可区分：exit={cp.returncode} {cp.stdout!r}"
    )


def test_gv_ci_api_runtime_check_step_declares_its_subject():
    """CI 里任何以「镜像存在」为前提的 step，必须自己声明该前提。"""
    yml = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    checked = 0
    for raw in re.split(r"\n      - ", yml):
        if "../api" not in raw:
            continue
        # 截到下一个 job 边界（2 空格缩进的键）为止 —— 否则会把后一个 job 的 `if:`
        # 误当成本 step 的判据（实测：docker job 的 `if:` 会让本条假绿）。
        block = re.split(r"\n  \S", raw, maxsplit=1)[0]
        checked += 1
        assert re.search(r"test -d|^\s+if:|\|\|\s*echo SKIP", block, re.MULTILINE), (
            f"引用 ../api 却没有存在性判据的 step（会静默导入 backend 自己）：\n{block}"
        )
    assert checked, "CI 里已不存在引用 ../api 的 step —— 本用例可随该 step 一起删除"

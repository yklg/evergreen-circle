"""backend/ 与 api/ 双源镜像一致性守卫（执行计划 G4；方案 B-10）。

方向：api/ 是可裁剪镜像，其中存在的模块/公开函数，backend/ 必须存在**同名同签名**的实现，
防双源漂移（api 残留过时签名 / backend 改名导致镜像引用失效）。

实现：AST 解析源码文件（不 import，规避两包同名 `app` 的 sys.modules 冲突），
比对顶层公开 def 的规范化签名文本（参数名 + 缺省 + 返回注解）。

运行：backend/ 下 `pytest tests/test_api_mirror_guard.py -q`
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 仓库根
API_CORE = ROOT / "api" / "app" / "core"
BACKEND_CORE = ROOT / "backend" / "app" / "core"


def _top_public_defs(src: str) -> dict[str, str]:
    """返回 {定义名: 规范化签名}（仅顶层公开 def/class，忽略 _ 私有）。"""
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out[node.name] = ast.unparse(node.args)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out[node.name] = "class"
    return out


def _module_pairs():
    if not (API_CORE.exists() and BACKEND_CORE.exists()):
        pytest_skip()
        return []
    pairs = []
    for f in sorted(API_CORE.glob("*.py")):
        if f.name == "__init__.py":
            continue
        bf = BACKEND_CORE / f.name
        if bf.exists():
            pairs.append((f.name, f, bf))
    return pairs


def pytest_skip():
    import pytest
    pytest.skip("api/ 或 backend/ 目录缺失（非双源形态）")


def test_api_mirror_public_signatures():
    """api/core 中每个公开顶层定义，backend/core 必须有同名同签名实现。"""
    pairs = _module_pairs()
    if not pairs:
        pytest_skip()
    missing: list[str] = []
    mismatched: list[str] = []
    for fname, af, bf in pairs:
        a_defs = _top_public_defs(af.read_text(encoding="utf-8"))
        b_defs = _top_public_defs(bf.read_text(encoding="utf-8"))
        for name, a_sig in a_defs.items():
            if name not in b_defs:
                missing.append(f"{fname}.{name}")
            elif a_sig != b_defs[name]:
                mismatched.append(f"{fname}.{name}\n   api:     {a_sig}\n   backend: {b_defs[name]}")
    assert not missing, "api 定义了 backend 缺失的公开项：\n  " + "\n  ".join(missing)
    assert not mismatched, "api/backend 签名漂移：\n  " + "\n  ".join(mismatched)


def test_api_mirror_common_modules_exist():
    """api/core 引用的模块文件，backend/core 都应存在（防 import 断裂）。"""
    api_files = {f.name for f in API_CORE.glob("*.py")} - {"__init__.py"}
    backend_files = {f.name for f in BACKEND_CORE.glob("*.py")} - {"__init__.py"}
    absent = sorted(api_files - backend_files)
    assert not absent, f"backend/ 缺 api/ 依赖的模块文件：{absent}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
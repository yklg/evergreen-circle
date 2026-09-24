"""语义残留门禁与镜像文件级守卫（《测试覆盖方案》B10；规则 R1 单一真相源一致性）。

守护的不变量：
- 「竞品 / brand」语义在本仓库只剩**白名单**内的合法残留（存量库迁移旧名、旧数据读时兼容、
  deprecated 保留函数、产品品牌模块 `lib/brand.ts` 与品牌静态资源路径）；
  任何新增的竞品语义（新文件、或白名单文件里换一种写法）都会让本门禁变红。
- `api/app/{core,services}` 与 `backend/app/{core,services}` 的模块文件集合一致（双向）：backend 新增模块
  （如 platforms / research_types / runner / baidu）必须同步进镜像；互补 `test_api_mirror_guard.py`
  的「api ⊆ backend 单向 + 签名比对」，合起来构成完整镜像面守卫。

说明：本文件只扫源码真相源（backend/app、frontend/src）。api/ 是镜像，P5-2 整目录同步后
其 core 内容与 backend 逐文件等同，故不重复扫描，由上面的文件集合守卫 + 镜像签名守卫覆盖。

运行：backend/ 下 `pytest tests/test_semantic_residue.py -q`
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # 仓库根
SRC_TREES = ("backend/app", "frontend/src")
SUFFIXES = (".py", ".ts", ".tsx", ".json", ".css", ".html")

_TOKEN = re.compile(r"竞品|brand", re.IGNORECASE)

# 白名单：(相对路径正则, 行内必须命中的正则, 原因)
# 「行内必须命中」使豁免精确到具体写法——白名单文件里出现新的竞品语义仍会被拦下。
_ALLOW = [
    (r"^backend/app/core/db\.py$",
     r"_migrate_brand_to_destination|_LEGACY_|\"brands?\"|brands / brand|竞品语义|"
     r"coverage_by_brand|brand_coverage_rate|brand → destination",
     "存量库列/表迁移与旧报告读时归一：旧列名/旧契约键必须原样保留，否则存量库迁移失效"),
    (r"^backend/app/core/charts\.py$", r"deprecated|竞品时代",
     "deprecated 五力雷达：保留函数以维持图表能力面与镜像签名面"),
    (r"^backend/app/core/orchestrator\.py$", r'rep\.get\("brands"\)|it\.get\("brand"\)|name/brand',
     "旧报告读时兼容（destinations or brands）+ LLM 偶发沿用旧键的行主键兜底"),
    (r"^backend/app/core/schemas\.py$", r'it\.get\("brand"\)|旧键 brand',
     "LLM 偶发沿用旧键 brand 的主键兜底（防整行丢失）"),
    (r"^frontend/src/lib/brand\.ts$", r".",
     "产品品牌模块（BRAND = 青野 Verda），与竞品语义无关"),
    (r"^frontend/src/lib/brand\.test\.ts$", r".",
     "同上：品牌漂移守卫，文件名与 describe 沿用模块名"),
    (r"^frontend/src/lib/persist\.test\.ts$", r"BRAND|describe\('brand'",
     "断言产品品牌常量字段齐备"),
    (r"^frontend/src/(main\.tsx|layout/VSidebar\.tsx|pages/SlidesPage\.tsx|lib/cover\.ts)$",
     r"\bBRAND\b|brand\.test\.ts|brand\.ts",
     "产品品牌常量消费点（文档标题 / 页眉 / 封面 byline）与漂移守卫注释"),
    (r"^frontend/src/(pages/HomePage|pages/LibraryPage)\.tsx$", r"assets/brand",
     "产品品牌静态资源路径"),
    (r"^frontend/src/__tests__/(reportHero|reportBriefView|reportRefine)\.test\.tsx$",
     r"assets/brand", "测试夹具中的品牌封面资源路径"),
    (r"^frontend/src/lib/cover\.test\.ts$", r"竞品|BRAND|brand",
     "封面兜底守卫自身：以「竞品」为负向哨兵（断言封面不回流竞品文案），并消费品牌常量/资源路径"),
    (r"^frontend/src/__tests__/dashboardPage\.test\.tsx$", r"历史竞品口径残留守卫",
     "负向断言注释（断言「竞争情报中心 / 覆盖品牌」不再出现）"),
]


def _allowed(rel: str, line: str) -> bool:
    return any(re.match(path, rel) and re.search(mark, line) for path, mark, _ in _ALLOW)


def test_no_semantic_residue_outside_whitelist():
    """backend/app + frontend/src 中「竞品 / brand」仅剩白名单内的合法残留。"""
    leftovers = []
    for tree in SRC_TREES:
        for p in sorted((ROOT / tree).rglob("*")):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            rel = p.relative_to(ROOT).as_posix()
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if _TOKEN.search(line) and not _allowed(rel, line):
                    leftovers.append(f"{rel}:{i}: {line.strip()[:140]}")
    assert not leftovers, (
        "发现白名单外的竞品语义残留（新增即说明改造不彻底；确需保留请连同理由登记白名单）：\n  "
        + "\n  ".join(leftovers)
    )


def test_api_core_module_set_mirrors_backend():
    """api/app 各代码包（core/services）与 backend 模块文件集合一致（双向）——
    backend 新增即须同步镜像；M2 起 services 层纳入同一守卫。"""
    api_app = ROOT / "api" / "app"
    backend_app = ROOT / "backend" / "app"
    if not (api_app.exists() and backend_app.exists()):
        pytest.skip("非双源形态（缺 api/ 或 backend/）")

    def _mods(d: Path) -> set:
        return {f.name for f in d.glob("*.py")} - {"__init__.py"}

    for pkg in ("core", "services"):
        api_dir, backend_dir = api_app / pkg, backend_app / pkg
        if not (api_dir.exists() and backend_dir.exists()):
            continue
        api_mods, backend_mods = _mods(api_dir), _mods(backend_dir)
        missing_in_api = sorted(backend_mods - api_mods)
        orphan_in_api = sorted(api_mods - backend_mods)
        assert not missing_in_api, f"镜像 {pkg}/ 缺 backend 的模块文件（需整目录同步）：{missing_in_api}"
        assert not orphan_in_api, f"镜像 {pkg}/ 存在 backend 已删除的模块文件：{orphan_in_api}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

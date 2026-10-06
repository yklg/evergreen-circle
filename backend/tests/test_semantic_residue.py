"""语义残留门禁与镜像文件级守卫（《测试覆盖方案》B10；规则 R1 单一真相源一致性）。

守护的不变量：
- 「竞品 / brand」语义在本仓库只剩**白名单**内的合法残留（存量库迁移旧名、旧数据读时兼容、
  deprecated 保留函数、产品品牌模块 `lib/brand.ts` 与品牌静态资源路径）；
  任何新增的竞品语义（新文件、或白名单文件里换一种写法）都会让本门禁变红。
- `api/app/{core,services}` 与 `backend/app/{core,services}` 的模块文件集合一致（双向）：backend 新增模块
  （如 platforms / research_types / runner / baidu）必须同步进镜像；互补 `test_api_mirror_guard.py`
  的「api ⊆ backend 单向 + 签名比对」，合起来构成完整镜像面守卫。
- **白名单自身不空转**（2026-09-26 补）：每条豁免至少命中一次，且扫描树必须真有文件 ——
  否则「守卫在看守什么」这个问题会随文件改名/移出而静默失效（详见那两个新增用例的 docstring）。

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
     r"coverage_by_brand|brand_coverage_rate|brand → destination|读时归一|brands→destinations",
     "存量库列/表迁移与旧报告读时归一：旧列名/旧契约键必须原样保留，否则存量库迁移失效"),
    (r"^backend/app/core/charts\.py$", r"deprecated|竞品时代",
     "deprecated 五力雷达：保留函数以维持图表能力面"),
    (r"^backend/app/core/pipeline/research/engine\.py$",
     r'rep\.get\("brands"\)|it\.get\("brand"\)|name/brand|run_pipeline|竞品',
     "旧报告读时兼容（destinations or brands）+ LLM 偶发沿用旧键的行主键兜底 + 历史注释"),
    (r"^backend/app/core/schemas\.py$", r'it\.get\("brand"\)|旧键 brand',
     "LLM 偶发沿用旧键 brand 的主键兜底（防整行丢失）"),
    (r"^backend/app/core/pipeline/research/_util\.py$", r'it\.get\("brand"\)|name/brand',
     "M3 提取：行主键对 LLM 偶发旧键 brand 的读容忍（与 schemas 同理由），不写入新数据"),
    # ── M2-flip 临时：skip 旧中立模块/注释，M3 引擎提取与语义精修时清理 ──
    (r"^backend/app/core/(source_type|expert_prompt)\.py$",
     r"竞品|brand",
     "简版时代模块的历史 docstring/注释（research_profile 已随决策 8 删除，"
     "注册表单一性由 test_registry_single_source 守卫）"),
    (r"^backend/app/core/runner\.py$", r"竞品",
     "封闭注册表注释（fail-loud 不回落竞品引擎），无代码语义"),
    (r"^backend/app/core/pipeline/diagnosis_templates\.py$", r'"brands"',
     "LC 报告模板的 legacy 空数组键（读兼容）；不被旅游引擎消费"),
    (r"^frontend/src/lib/brand\.ts$", r".",
     "产品品牌模块（BRAND = EvergreenCircle 常青圈），与竞品语义无关"),
    (r"^frontend/src/lib/brand\.test\.ts$", r".",
     "同上：品牌漂移守卫，文件名与 describe 沿用模块名"),
    (r"^frontend/src/lib/faviconSvg\.test\.ts$",
     r"brand\.test\.ts|make_brand_icon\.py|preview-brand-icon\.html",
     "favicon 事故复盘里点名的三个**真实在仓文件**（品牌图标链：旧图标测试、生成脚本、验收页），"
     "作用是让读者能按名去查，不是竞品语义；本文件其余行不豁免"),
    (r"^frontend/src/lib/persist\.test\.ts$", r"BRAND|describe\('brand'",
     "断言产品品牌常量字段齐备"),
    (r"^frontend/src/(main\.tsx|layout/VSidebar\.tsx|pages/SlidesPage\.tsx|lib/cover\.ts)$",
     r"\bBRAND\b|brand\.test\.ts|brand\.ts",
     "产品品牌常量消费点（文档标题 / 页眉 / 封面 byline）与漂移守卫注释"),
    (r"^frontend/src/pages/HomePage\.tsx$", r"assets/brand",
     "产品品牌静态资源路径（`pages/LibraryPage.tsx` 曾同用此路径，随归档入口收敛删除后已收窄至此）"),
    (r"^frontend/src/__tests__/(reportHero|reportBriefView|reportRefine|slidesPage)\.test\.tsx$",
     r"assets/brand|brands|brand|竞品", "活跃前端测试夹具/负向哨兵；P2 前端 flip 后随 gaizao 版替换"),
    (r"^frontend/src/lib/cover\.test\.ts$", r"竞品|BRAND|brand",
     "封面兜底守卫自身：以「竞品」为负向哨兵，并消费品牌常量/资源路径"),
    # ── M2-flip 临时：skip 旧前端品牌组件/测试，P2 前端 flip 整文件替换后删除本组白名单 ──
    # （两条已按「替换后此条白名单删除」的自述纪律收窄，由本文件末尾的
    #   `test_every_allowlist_entry_fires_at_least_once` 机器保证不再回潮：
    #    · `VStructured|VMetricsPanel|VQualityGate|VSentimentFlatPanel` 组 —— 随词云口碑化修复
    #      删除孤儿组件 VSentimentFlatPanel 后整组零命中；
    #    · `dashboardPage.test.tsx` —— 该文件已移入 `_travel_pending/`，被 _EXCLUDE_DIR_PARTS
    #      排除在扫描树之外 ⇒ 这条豁免**永远不可能命中**。若那个目录回归扫描，需连同豁免一起加回。）
    (r"^frontend/src/__tests__/(clarifyAsync|reportHero)\.test\.tsx$",
     r"competitors_fallback|竞品|ZZBRANDMARK|brands|brand",
     "P2 随问卷 v2/C1 报告页测试整文件替换"),
    # ── M2-flip 临时（二）：P2 前端 flip 将整文件替换的页面/store/lib（旧旅游契约用词）──
    (r"^frontend/src/(types|lib/api|lib/cover|store/taskStore|store/expertStore|store/annotationStore|"
     r"pages/HomePage|pages/ClarifyPage|pages/ReportPage|pages/SlidesPage|pages/KnowledgePage|"
     r"mocks/researchStream)\.tsx?$",
     r"brand|竞品|BRAND",
     "P2 前端 flip 随 gaizao 契约整文件替换（含产品品牌常量消费点）；替换后此条白名单删除"),
    (r"^frontend/src/lib/__tests__/textBrief\.test\.ts$", r"brand|竞品",
     "P2 随 textBrief 合并替换"),
    # ── LC 域保留文件（P2 不替换）：仅说明性注释/兼容字段允许，代码不回流竞品语义 ──
    (r"^frontend/src/(components/lifecircle/LifeCircleReportView|mocks/livingCircleReports)\.tsx?$",
     r"竞品|brand",
     "LC A1 渲染与 mock 的说明性注释/旧字段容错；LC 业务冻结，不参与旅游契约"),
]

# M2-flip：暂不启用的 gaizao 前端测试隔离目录，P2/P3 随组件 flip 移回后再纳入门禁
_EXCLUDE_DIR_PARTS = ("_travel_pending",)


def _allowed(rel: str, line: str) -> bool:
    return any(re.match(path, rel) and re.search(mark, line) for path, mark, _ in _ALLOW)


def _scan_residue():
    """按守卫口径扫一遍树，返回 `(白名单外残留, 每条豁免的命中行数, 扫到的文件数)`。

    三个产出共用一次遍历 —— 拆成三份各扫一遍会造出三套可能互相漂移的口径。
    """
    leftovers: list[str] = []
    hits = {i: 0 for i in range(len(_ALLOW))}
    files = 0
    for tree in SRC_TREES:
        for p in sorted((ROOT / tree).rglob("*")):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if any(part in rel for part in _EXCLUDE_DIR_PARTS):
                continue
            files += 1
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not _TOKEN.search(line):
                    continue
                for j, (path, mark, _why) in enumerate(_ALLOW):
                    if re.match(path, rel) and re.search(mark, line):
                        hits[j] += 1
                if not _allowed(rel, line):
                    leftovers.append(f"{rel}:{i}: {line.strip()[:140]}")
    return leftovers, hits, files


def test_no_semantic_residue_outside_whitelist():
    """backend/app + frontend/src 中「竞品 / brand」仅剩白名单内的合法残留。"""
    leftovers, _hits, _files = _scan_residue()
    assert not leftovers, (
        "发现白名单外的竞品语义残留（新增即说明改造不彻底；确需保留请连同理由登记白名单）：\n  "
        + "\n  ".join(leftovers)
    )


def test_scan_trees_actually_contain_files():
    """扫描树必须真有内容 —— 目录被改名/被排除面扩大时集合会塌向空集，守卫随即恒绿。

    这是本文件最容易静默失效的一条：`rglob` 对不存在的目录**不报错，只返回空**。
    下界取 200（基线 283，2026-09-26 实测），留正常增删余量。
    """
    _leftovers, _hits, files = _scan_residue()
    assert files >= 200, (
        f"词表守卫只扫到 {files} 个文件（基线 283）⇒ SRC_TREES 指错或 _EXCLUDE_DIR_PARTS 过宽，"
        "本文件其余断言正在空转"
    )


def test_every_allowlist_entry_fires_at_least_once():
    """每条豁免必须**至少命中一行** —— 零命中的豁免是静默堆积的债务，不是无害的冗余。

    两种真实漂移都会留下死豁免（2026-09-26 实测各抓到一条）：
    ① 被豁免的字样已消失，豁免还留着；
    ② 被豁免的文件移出了扫描树（如进 `_travel_pending/`），于是该豁免**永远不可能命中**，
       而「排除面缩小覆盖面」与「豁免过期」两件事会互相掩盖。
    判据形态取自 `check_guard_construction.py` 的 G-4 计数收口（唯一出口必须机器可校验）。
    """
    _leftovers, hits, _files = _scan_residue()
    dead = [f"  · {_ALLOW[i][0]} —— {_ALLOW[i][2]}" for i, n in hits.items() if n == 0]
    assert not dead, (
        "存在零命中的死豁免（字样已消失，或文件已移出扫描树 ⇒ 永不命中）。"
        "请删除该条；若文件只是被排除，需连同排除理由一并复核：\n" + "\n".join(dead)
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

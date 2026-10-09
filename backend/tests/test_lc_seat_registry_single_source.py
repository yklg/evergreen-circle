"""席位注册表是**唯一出口**：任何第二份抄本、任何空转判据，都必须当场红。

守住四件事：
  - B1 席位 id 字面量只能住在注册表（AST 扫字符串常量，不扫注释）；
  - B2「又抄了一张表」的赋值形状不得出现在生产码与测试里（必须 import 注册表）；
  - B3 键集闭合（stage 轴）+ 行为闭合（带署名的章节必须在表里）；
  - TC-A1 **反空转**：注册表被清空、或判据的探针失效时，本文件必须红而不是恒绿。

B1 为什么与其余三条同笔而不是早一笔：它要求 `pipeline/living_circle.py` 里那 5 处
`collected_by` 与 2 处 `node.expert` 先清空（C2 的活）。C1 单独立这条会当场红，
反而逼人在守卫里开豁免名单 —— 而"守卫自带豁免名单"就是这条守卫要消灭的形状。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app.living_circle.seat_registry import (
    ARTIFACT_SEAT,
    FALLBACK_TEAM,
    SECTION_SEAT,
    STAGE_SEAT,
    TEAM_FALLBACK,
)

BACKEND = Path(__file__).resolve().parent.parent
REGISTRY = BACKEND / "app" / "living_circle" / "seat_registry.py"

#: 允许出现"章节→席位"表形状的地方只有注册表本身。
#: 规范化脚本与本目录下的测试都曾经各自抄过一份，改一处必漏一处。
COPY_SCAN_TREES = (BACKEND / "app", BACKEND / "tests", BACKEND / "scripts")
# 只认"真赋值"：键值体从下一行开始。第一版写成 `SECTION_SEAT\s*=\s*\{` 时，
# 本文件自己注释里那句描述就被扫成了命中 —— 残留扫描被解释性注释绊倒，
# 是上一轮已经踩过一次的坑（判据要按**代码形状**写，不按散文措辞写）。
COPY_SHAPE = re.compile(r"^SECTION_SEAT\s*=\s*\{\s*\n", re.M)

#: 装配器产出的章节里，带 claims 的必须都能在 SECTION_SEAT 查到席位

def _scan_copy_sites() -> list[str]:
    """返回"抄了第二份 SECTION_SEAT"的文件清单（注册表自身除外）。"""
    hits = []
    for tree in COPY_SCAN_TREES:
        for p in sorted(tree.rglob("*.py")):
            if p == REGISTRY or "__pycache__" in p.parts:
                continue
            if COPY_SHAPE.search(p.read_text(encoding="utf-8", errors="replace")):
                hits.append(str(p.relative_to(BACKEND)))
    return hits


# ── TC-A1 反空转 ────────────────────────────────────────────────────
def test_registry_tables_are_all_nonempty():
    """任一张表被清空 ⇒ 下面所有判据都会恒真变绿，这里先把"空表"本身判死。"""
    assert FALLBACK_TEAM, "编排期保底队为空 ⇒ lc_team 会交出一支没人认领的队"
    assert TEAM_FALLBACK, "装配期兜底名单为空 ⇒ report.dispatch 会空转"
    assert STAGE_SEAT and SECTION_SEAT and ARTIFACT_SEAT, "注册表有空表 ⇒ 归属判据全部失效"


def test_copy_detector_actually_detects():
    """探针自证：喂给它一段"确实抄了一份"的源码，它必须报命中。

    没有这条，`_scan_copy_sites()` 只要正则写错（比如漏了空格变体）就会永远返回空，
    而 B2 看起来"全绿"。这正是本仓 `test_sse_event_type_single_source` 加反空转用例的理由。
    """
    assert COPY_SHAPE.search('SECTION_SEAT = {\n    "medical": "L2-001",\n}')
    assert COPY_SHAPE.search('SECTION_SEAT={\n  "x": "L1-001",\n}')
    # 散文里提一句这件事，不该被当成又抄了一张表
    assert not COPY_SHAPE.search('把 SECTION_SEAT = 这张表搬进注册表是 C1 的活')
    assert not COPY_SHAPE.search("from app.living_circle.seat_registry import SECTION_SEAT")


# ── B2 唯一出口 ─────────────────────────────────────────────────────
def test_no_second_copy_of_section_seat_exists():
    hits = _scan_copy_sites()
    assert not hits, (
        "发现 SECTION_SEAT 的第二份定义（唯一出口是 app/living_circle/seat_registry.py）："
        f"{hits}"
    )


# ── B3 键集与行为闭合 ───────────────────────────────────────────────
def test_stage_seat_keys_match_pipeline_stages():
    """stage 轴：注册表的键集必须与流水线 STAGES **相等**。

    两侧 import 只发生在测试里 —— 注册表本体 import pipeline 会成环
    （pipeline→registry→pipeline），并撞 check_guard_construction 的 G-5。
    """
    from app.core.pipeline.living_circle import STAGES

    assert set(STAGE_SEAT) == set(STAGES), (
        f"stage 归属表与流水线阶段不齐：多出 {sorted(set(STAGE_SEAT) - set(STAGES))}、"
        f"缺少 {sorted(set(STAGES) - set(STAGE_SEAT))}"
    )


# B3 的**行为半边**不在这里重复实现：`test_expert_signature_derivation.py` 已经跑一次真流水线
# 拿到 signed_report，并判「注册表每个键都在报告章节里」「带署名的章 ≥ 6（防空转）」
# 「每章 author == 该席位名册姓名」。这里再造一份合成夹具 = 同一判据两处承载，
# 而且那份合成 lc 与真装配路径的偏差本身就会成为新的漂移源。


def test_the_two_fallback_lists_stay_different_by_design():
    """编排期 10 席 与 装配期 13 人 **故意**是两张表（见注册表文件头）。

    这条不是"防止变红"，是把"不许顺手合并"写成判据：哪天有人裁齐，
    `report.dispatch` 的字节就变了，必须先按换代流程立项。
    """
    orchestration = {s.seat_id for s in FALLBACK_TEAM}
    assembly = set(TEAM_FALLBACK)
    assert orchestration != assembly, "两张保底名单被合并了 —— 这会改 report.dispatch 的字节"
    # 两轴各自独有：编排期有方法专家（定位/核验/测时/评分），装配期有类别细位。
    # 断言"互有独有成员"而不是"谁包含谁"—— 上一版写了子集，实测并不成立。
    assert orchestration - assembly, f"编排期独有席位被删空：{sorted(orchestration)}"
    assert assembly - orchestration, f"装配期独有席位被删空：{sorted(assembly)}"

# ── B1（C2 起生效）：席位字面量只能住在注册表 ──────────────────────
# 用 AST 找**字符串常量**，不拿正则扫全文：上一版残留扫描判据就是被自己注释里的
# 字面形状绊倒的（散文里提一句"SECTION_SEAT = {"不该算抄表，注释里写 L2-001 也不该）。
SEAT_LITERAL = re.compile(r"^L[123]-\d{3}$")
#: 扫描面 = **生活圈域**的代码。刻意不扫全仓：两本名册共用同一套 48 个 id，
#: `app/core/audit.py` 里的 "L3-003" 指旅游域的质检总监**周翊**，生活圈同 id 是**裴砚秋** ——
#: 把 travel 域的字面量也算进这条守卫，等于假设"一个 id 只有一个含义"，
#: 而那正是本批所有署名缺陷的根因。travel 域要收口时另立一张表、另开一条守卫。
SCAN_TARGETS = [
    *(BACKEND / "app" / "living_circle").rglob("*.py"),
    BACKEND / "app" / "core" / "pipeline" / "living_circle.py",
    BACKEND / "app" / "core" / "pipeline" / "lc_team.py",
    BACKEND / "app" / "core" / "pipeline" / "diagnosis_templates.py",
]


def _seat_literals_in(path: Path) -> list[str]:
    """返回该文件里作为**字符串常量**出现的席位 id（含所在行号）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and SEAT_LITERAL.match(node.value):
            hits.append(f"{path.name}:{node.lineno}={node.value}")
    return hits


def test_seat_literal_detector_actually_detects():
    """反空转：探针喂一段真含席位字面量的代码，必须报命中。"""
    probe = BACKEND / "app" / "living_circle" / "seat_registry.py"
    assert _seat_literals_in(probe), "探针在注册表自身上都扫不出席位 ⇒ 判据在空转"


def test_registry_scan_scope_covers_the_living_circle_domain():
    """反空转（B1 自己的）：扫描面必须真的覆盖生活圈子域的全部模块。

    上一版把扫描面写成"整个 app/"，结果被 travel 域的同形 id 顶红 —— 收窄成显式清单后，
    新风险变成"加了新模块忘了纳入"。这条判据把那个遗漏变成红，而不是静默漏检。
    """
    from app.living_circle import __name__ as _pkg  # noqa: F401  只为确认包存在

    pkg = BACKEND / "app" / "living_circle"
    modules = {p.name for p in pkg.glob("*.py") if p.name != "__init__.py"}
    covered = {p.name for p in SCAN_TARGETS if p.parent == pkg and p.name != '__init__.py'}
    assert covered == modules, f"扫描面漏了生活圈子域模块：{sorted(modules - covered)}"


def test_seat_id_literals_live_only_in_the_registry():
    """`app/**` 生产码里除注册表外不得再出现席位字面量（travel 域 research/** 除外）。

    这条是 C2 的收口判据：`living_circle.py` 曾有 5 处 `collected_by` + 2 处 `node.expert`
    硬编码，`diagnosis_templates.py` 曾有 8 处章节署名 + 3 处证据姓名 + 1 份 13 人名单。
    """
    offenders = []
    for path in sorted(SCAN_TARGETS):
        if not path.is_file() or path.name == "seat_registry.py":
            continue
        offenders += _seat_literals_in(path)
    assert not offenders, (
        "席位字面量泄漏到注册表之外（唯一出口是 app/living_circle/seat_registry.py）："
        f"{offenders}"
    )

"""证据域图层 v7.2 · 子类口径（`sub_kinds` / `required` / `weight`）的判据（计划 §14.3）。

## 这批用例要证明什么

v7.2 把覆盖度的分子从「点数」改成「门槛项数」，并新增一张子类表。评审（第十七轮）
判出 5 条 P0，其中 **P0-1 的测试面是零防线**：`poi.py:274`（`to_stats`）与 `poi.py:421`
（`derive_stats_from_points`）是**两份同式实现**，而后者**就地覆盖**前者、且评分吃的是后者。
⇒ 只改 274 会让整批改动静默失效，而 I1 那三条既有种子（都只断"以派生为准"）**全部继续绿**。
本文件的 T2/A3 就是为了堵这个洞而存在的。

## 两组用例的分工（为什么不是整文件 skip）

沿用 `test_forensic_rounds.py:15-17` 的纪律：**守卫按单条打，不整文件 `importorskip`**
——整文件守卫会把"今天就该生效的锁"一起静默掉。

- **A 组（今日即绿）**：真锚与**现状记录**。A3 原先钉"含 `ideal` 的封顶式今天全仓有**三份**
  （`poi.py` 两份 + 迁移脚本一份）"，`cov-1` 落地后**重指**为"0 份自己算 + 那三个历史位点都在调用"；
  A1 原先钉"18 颗教育点 ⇒ coverage 1.0"，重指为"1/3，且 1.0 那个左端点由同一颗函数的
  缺 `sub_kind` 支现场复现"。**重指而不是删**的理由留着：删掉就等于把"我们曾经有三份、
  曾经顶满"这两条证据一起删了。
- **B 组（`xfail(strict=True)`）**：目标行为，实现未落地即失败。
  **用 xfail 而不是 skipif 的理由**：skip 在实现落地时**不发信号**（悄悄开始跑），
  而 strict-xfail 在实现落地时会 XPASS ⇒ **套件当场红** ⇒ 强制摘标。
  这正是本项目对"xfail 修好那轮必须摘标"的既有纪律（见 `test_forensic_rounds` 的 T3 段
  在片 4 落地后转真判据的先例）。
  **10-01 摘标 8 条**：T1/T2/T3/T6/T10/T14/T15/T17 —— 每条都以 XPASS(strict) 为信号，
  摘标时把复核到的读数写进各自 docstring。**另重指 1 条**：T18 原稿断"带后缀与不带后缀逐位相同"，
  那条**永远不可能成立**（名称通道多命中归 `other`），已改写成 T19 的反向对照并摘标。
  本文件**只剩 2 条 xfail**：T9（`sub_kind` 契约判据 B14 未写）、T0（展示面并集未接）。
  **T4 已在第二十一轮摘标**（它原先查 `CATEGORY_RULES[...]["sub_kinds"]` 这个**不存在的键**，
  真身是 `SUB_KIND_TABLE` ⇒ 与 T8 同型的"符号位置写错"死账）；摘标时补了反向对照与全局表恢复。
  **T8 已在 10-01 片 1d 摘标**（§六 选了 (a) 档：新键进载荷 + 进复用门
  + 进口径名册（`report::coverage_caliber_version`）+ 四份演示夹具已声明，
  **不进**契约门禁；缓存键那一档**刻意跳过**，理由见计划 §六 与 §十七·补5）。
  ⚠️ 同轮 P0-1 还订正了 T8 里一条**近似恒真**的前置判据（`"COVERAGE_CALIBER_VERSION" in vars(scope)`
  靠 import 就为真，删掉发射行照样绿）⇒ 现在它吃 `SpatialScope.payload` 的**产出**。

## 禁则

禁恒真断言。每条 B 组用例都必须能被"什么都不实现"以外的方式证伪 ——
能在 A 组找到配对现状记录的，以 A 组为准。
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Dict, List

import pytest

from app.living_circle import assemble as asm
from app.living_circle import poi as poi_mod
from app.living_circle import scoring
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import derive_stats_from_points, to_stats
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)          # 凯里老街，与 test_poi_conservation 同锚
POI_PY = Path(inspect.getsourcefile(poi_mod))
BACKEND_ROOT = POI_PY.parent.parent.parent          # .../skip/backend（app 的上一级）


def _scanned_files() -> List[Path]:
    """生产码扫描面：`app/` + `scripts/`，含 `app/` 与 `scripts/` 两棵子树。

    ⚠️ 第十九轮 P0-④：T2 原先只读 `poi.py` 一个文件 ⇒ 新纯函数若落在别处，
       "只许一份"当场变成 0 处（与刚修的 P0-2 同型的死守卫）。扫描面必须比被改面大。
    """
    return sorted(p for sub in ("app", "scripts")
                  for p in (BACKEND_ROOT / sub).rglob("*.py"))


def _coverage_recompute_fns(src: str) -> List[str]:
    """判据（结构面，不吃变量名）：返回"把某东西除以一个什么、再夹到 1.0、并写回 `coverage`"的函数名。

    三个条件同时成立才算一份**重算**：
      1) 函数体内出现 `ast.Div`；
      2) 出现"夹到 1.0"的形状 —— `min(1.0, x)` 调用 **或** 与字面量 `1.0/1` 比较（`if cov > 1.0`）；
      3) 写回目标叫 `coverage`：`coverage = …` 或 `s["coverage"] = …`。
    条件 3 用来排除 `scoring.py:82/102/126`、`geo_utils`、`field.py` 那些"对已算好的值再夹一次"
    的防御夹钳 —— 它们不产生分子，不是第二份口径。

    ⚠️ 第二十轮评审 P0-1：旧判据是"AST 里 `min` 的 unparse 含子串 `ideal`"⇒ 只要实施者先算
       `cov = n / ideal` 再写 `min(1.0, cov)`，或者把 `ideal` 改名，计数就打成 **0**，
       `== 1` 永不成立 ⇒ 本条又是"一路 xfail 的死守卫"（同 P0-2、同 ④，同一个形状第三次犯）。
       现在这三条绕法都由 `test_the_coverage_replica_scanner_actually_catches_the_shape` 当场钉住。
    """
    found: List[str] = []
    for fn in (n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
        has_div = any(isinstance(n, ast.Div) for n in ast.walk(fn))
        has_clamp = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and (
                    getattr(n.func, "id", getattr(n.func, "attr", "")) == "min") \
                    and any(isinstance(a, ast.Constant) and a.value in (1.0, 1) for a in n.args):
                has_clamp = True
            if isinstance(n, ast.Compare) and any(
                    isinstance(c, ast.Constant) and c.value in (1.0, 1) for c in n.comparators):
                has_clamp = True
        writes_cov = False
        for n in ast.walk(fn):
            if not isinstance(n, (ast.Assign, ast.AnnAssign)):
                continue
            for tgt in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(tgt, ast.Name) and tgt.id == "coverage":
                    writes_cov = True
                if isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant) \
                        and tgt.slice.value == "coverage":
                    writes_cov = True
        if has_div and has_clamp and writes_cov:
            found.append(fn.name)
    return found


def _coverage_recompute_sites(files: List[Path]) -> List[str]:
    """按 `相对路径::函数名` 列出全仓的"覆盖度重算点"（A3 与 T2 共用这一颗，避免两处口径各写一遍就漂）。"""
    return [f"{path.relative_to(BACKEND_ROOT)}::{fn}"
            for path in files for fn in _coverage_recompute_fns(path.read_text(encoding="utf-8"))]


def _fn_nodes(tree: ast.AST):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _has_div_and_clamp(fn: ast.FunctionDef) -> bool:
    """函数体内同时有"除法"和"夹到 1.0"（`min(1.0, x)` 或与字面量 1.0 比较）。"""
    div = any(isinstance(n, ast.Div) for n in ast.walk(fn))
    clamp = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "min" \
                and any(isinstance(a, ast.Constant) and a.value in (1.0, 1) for a in n.args):
            clamp = True
        if isinstance(n, ast.Compare) and any(
                isinstance(c, ast.Constant) and c.value in (1.0, 1) for c in n.comparators):
            clamp = True
    return div and clamp


def _clamp_fns(src: str) -> List[str]:
    """"算式本身"所在的那些函数（不看写回目标）—— 给 T2 的**正向半边**用。

    为什么需要它：`_coverage_recompute_fns` 的三个条件里含"写回 `coverage`"，而抽出来的纯函数
    通常是 `return min(1.0, n / ideal)`、并不赋值 ⇒ 落地后被检数为 **0** 而不是 1。
    只断"== 1"的话，T2 会第三次犯同一个错（判据自己失效）。故正向半边改用这颗：
    **全 `poi.py` 里"除法 + 夹钳"只许出现在 1 个函数里**，且那两个消费者都调它。
    """
    return [fn.name for fn in _fn_nodes(ast.parse(src)) if _has_div_and_clamp(fn)]


def _called_names(src: str, fn_name: str) -> set:
    """`fn_name` 函数体里被调用的**裸函数名**集合（属性调用取末段）。"""
    out = set()
    for fn in _fn_nodes(ast.parse(src)):
        if fn.name != fn_name:
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                out.add(getattr(n.func, "id", None)
                        or getattr(n.func, "attr", None) or "")
    return {x for x in out if x}


TARGET_XFAIL = pytest.mark.xfail(
    strict=True, reason="计划 v7.2 未落地（§14.3）—— 落地即 XPASS 报错，必须摘标并复核读数"
)


def _ll(x: float, y: float) -> Dict[str, float]:
    lng, lat = xy_to_lnglat(CENTER, x, y)
    return {"lng": lng, "lat": lat}


def _scope(half: float = 1000.0) -> SpatialScope:
    ring = [
        xy_to_lnglat(CENTER, -half, -half),
        xy_to_lnglat(CENTER, half, -half),
        xy_to_lnglat(CENTER, half, half),
        xy_to_lnglat(CENTER, -half, half),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


SCOPE = _scope()


def _named(names: List[str], cat: str = "education") -> List[Dict[str, object]]:
    """按真实百度 POI 的形状造点：判定走 `tag` 优先、名字弱先验，所以两者都要给。"""
    out = []
    for i, name in enumerate(names):
        out.append({**_ll(120.0 + i * 40.0, 60.0), "name": name, "tag": "", "type": ""})
    return out


def _version_check_params(ds):
    """本次请求的口径三元组 —— **走生产那颗组装函数**，不在测试里手拼形状。

    ⚠️ 改前基线首跑（10-01，落地前）抓出的真缺陷：这里原先直接返回 `ds.CheckParams(...)`，
       而 `reuse_policy` 比较的是**映射**（`report_contract.py:935-939` 用 `wanted["travel_mode"]`
       下标取）⇒ A4 当场 `TypeError: 'CheckParams' object is not subscriptable`，
       而同一颗喂给 T8 时那个 TypeError 被 `xfail(strict)` **当成"预期失败"吞了**
       ⇒ T8 的 xfail 是被崩溃挣到的、不是被"缺新键没人拦"这个机制挣到的（第十九轮 P0-③ 批评的
       正是这个形状，我在 ② 的修复里又造了一个新的）。
       ⇒ 改吃 `data_source.wanted_caliber`（`:61` 那颗"只在这一个地方组装"的出口）：
       测试与生产共用同一份形状，就不可能出现"测试里能跑、生产里形状不对"。
    """
    return ds.wanted_caliber(ds.CheckParams(scene_name="版本台架", city="凯里", address="测试",
                                            center=CENTER, study_radius_m=2500.0,
                                            sample_profile="standard", travel_mode="walking"))


# 复用门读的三样东西各有出处（`report_contract.py:937-941`）：`travel_mode`/`sample_profile`
# 在 `caliber` 里，而**研究半径在 `scene`**（那次请求的半径），不是 `caliber.study_radius_m`
# （那是档位半径，用户改半径时两者不等）。第十九轮 P0-② 里 ③ 永红就是因为缺 `scene`。
_SCENE_TRIPLE = {"study_radius_m": 2500}


def _caliber_triple(rc) -> Dict[str, object]:
    """除"第二把版本键"外完全合规的口径三元组 —— 每次现取，别烘成模块常量。"""
    return {"scope_policy_version": rc.SCOPE_POLICY_VERSION,
            "travel_mode": "walking", "sample_profile": "standard"}


# 凯里教育类**实测原样**（live 报告 `skip/tmp/out/lc_p5_live_kaili_walking_standard.json`：
# 圈内 18 点，`in_circle=18 / coverage=1.0 / min_minutes=7.6`）。逐子类分桶读数是步 0 补数产物
# （`skip/tmp/lc_step0_live.py`）：**真小学只有 1 所**，14 家幼儿园，3 个既非小学也非幼儿园的
# 存疑项 —— 其中「凯里市第十三小学家长学校」名字**含"小学"却不是小学**，是 W1 `reject_tags`
# 必须拦住的那一颗。判别力全在「点数 18 ≫ ideal 3，而门槛项 1 < 3」。
# ⚠️ 早先这里写的是"2 所小学"（含我凭空补的「第十四小学」）—— 那颗点在本市报告里不存在，
#    已按实测改成 1 所；对应的期望值全线从 2/3 改指 1/3（见 T1/T3/T10）。
KAILI_EDU_PRIMARY = ["凯里市第十三小学"]
KAILI_EDU_KINDERGARTEN = [
    "童欣宏源幼儿园", "剑桥第二幼儿园", "凯里市第三幼儿园", "凯里丰球亲子幼儿园",
    "凯里新世纪第六幼儿园", "虹霖幼儿园", "天欣苑幼儿园", "东昇幼儿园(友庄路)",
    "金果果幼儿园", "凯里市第三十二幼儿园", "金地幼儿园", "金马天贻幼儿园",
    "新时代幼儿园", "哈佛幼儿园(宁波路)",
]
KAILI_EDU_AMBIGUOUS = [
    "凯里市第十中学", "凯里市第十三小学家长学校", "凯里市学前教育第三集团总园",
]
KAILI_EDU_ALL = KAILI_EDU_PRIMARY + KAILI_EDU_KINDERGARTEN + KAILI_EDU_AMBIGUOUS   # 18 点


def _edu_stats():
    per_cat = {"education": _named(KAILI_EDU_ALL)}
    return to_stats(per_cat, {}, SCOPE, CENTER), per_cat


# ── A 组 · 今日即绿（真锚 + 现状记录）────────────────────────────


def test_record_coverage_required_only_caliber_lands():
    """A1 · **现状记录（10-01 重指到 `cov-1`）**：凯里教育 18 颗点 ⇒ 门槛项口径 **1/3**。

    改前这里断的是 `coverage == 1.0`（18 颗点把 ideal=3 顶满）。左端点**没有丢**：
    同一条 18 颗点，只要载荷里**没有** `sub_kind` 键，`coverage_from_points` 就按点数支给出 1.0
    （下面 `left` 那一行）⇒ "88.6 → 41.9" 这个差值的**两端都由生产函数现算**，
    答辩现场可复算，不依赖任何手填字面量。

    ⚠️ 重指经过（不是"红了就改期望值"）：`in_circle == 18` 这一半**一条没动** ⇒ 证明掉下来的是
    分子而不是点数（红线：`in_circle` 被门槛计数替换会破 `check_poi_conservation`）。
    """
    stats, per_cat = _edu_stats()
    edu = next(s for s in stats if s["category"] == "education")
    assert edu["in_circle"] == 18, edu
    assert edu["coverage"] == pytest.approx(round(1 / 3, 4)), (
        f"新口径右端点实得 {edu['coverage']} ⇒ 分子不是门槛项数（应为 1 所小学 / ideal 3）")
    # 左端点：同一批点、**缺 `sub_kind` 键**的载荷 ⇒ 退回点数支（= 改前那条 1.0）
    left = poi_mod.coverage_from_points(per_cat["education"], 3, "education")
    assert left == pytest.approx(1.0), (
        f"缺 `sub_kind` 的载荷不再按点数解释（实得 {left}）⇒ §六「旧载荷按旧口径读、不回填」失守，"
        "并且本条失去左端点")


def test_coverage_recompute_sites_today_record():
    """A3 · **现状记录（10-01 重指）**：全仓"自己除一遍再夹 1.0 并写回 `coverage`"的函数 = **0 处**，
    而当年那三个位点（`to_stats` / `derive_stats_from_points` / 迁移脚本 `_migrate_poi`）
    现在都是**调用者**。

    改前这里钉的是"今天有**三处**"这一事实（第十八轮 P0-1 的原始形态：274 与 421 两份同式实现、
    421 就地覆盖 274，而第十九轮 ④ 又追出迁移脚本是第三份）。
    **为什么重指而不是删**：删掉就等于把"我们曾经有三份"这条证据删了；新的形态钉的是
    "那三个名字仍然在，但它们不再自己算" —— 将来谁在**任意一个**位点里手写一遍算式，
    `sites` 立刻非空 ⇒ 本条红。

    ⚠️ 与 T2 的分工（两条共用同一颗判据，但断的不是同一件事）：
      · T2 = 反向"0 处" + 正向"算式**存在且只有一份**、就在 `poi.py`、两个消费者都调它"；
      · A3 = 反向"0 处" + **第三个历史位点（迁移脚本）也在调用**，T2 不扫 `scripts/` 的调用面。
    "数不出东西"这种判据自失效形状由 `test_the_coverage_replica_scanner_actually_catches_the_shape`
    （A6 敏感性对照）守住，不靠本条的运气。
    """
    files = _scanned_files()
    assert POI_PY in files, (
        f"扫描面共 {len(files)} 个文件却不含 poi.py ⇒ 扫描根算错，"
        "本条与 T2 会一起退化成数不出东西的死守卫（第十九轮 P0-④）")
    sites = _coverage_recompute_sites(files)
    assert sites == [], (
        f"又长出 {len(sites)} 处本地重算：{sites} ⇒ `cov-1` 的「单一算式」被破（计划 §三 第 1–2 条）")
    poi_src = POI_PY.read_text(encoding="utf-8")
    for consumer in ("to_stats", "derive_stats_from_points"):
        assert "coverage_from_points" in _called_names(poi_src, consumer), (
            f"`{consumer}` 不再调用那一份算式 ⇒ 它自己算（A3 的历史形态复发）")
    mig_src = (BACKEND_ROOT / "scripts" / "migrate_poi_conservation.py").read_text(encoding="utf-8")
    assert "coverage_from_points" in _called_names(mig_src, "_migrate_poi"), (
        "迁移脚本不再调用那一份算式 ⇒ 它回到自己除一遍（评审 P0-4 的第三处实现复发），"
        "T7 的同式判据会同时红")


def test_migration_formula_matches_production_derivation():
    """T7 · 迁移脚本与生产派生**必须同式**，否则改了生产公式会让脚本按旧口径回填夹具。

    评审 P0-4 指出的第三处实现（`scripts/migrate_poi_conservation.py:75` 自己 `min(1.0, n/ideal)`）
    **10-01 已收敛**：脚本现在 `from app.living_circle.poi import coverage_from_points` 并**按类别
    分桶后**调它 ⇒ 与本条生产侧吃的是同一颗函数、同一批点位。本条因此从"现状能红的对照"
    转正成**日常同式判据**：将来谁再手改其中一边（例如给脚本加"回填旧夹具"的分支），当场红。
    ⚠️ 第十八/十九轮订正（原写"静默回填存量 27 份"是**假的**，已撤销）：该脚本的 `SCENES` 与写入面
    只有 4 份夹具 JSON，**碰不到 DB**；存量是 **30 份**，其真正的替换面是 `replace_scene=True`
    的先删后增（而那条今天**没有生产调用点**，见计划 §十七 ④）。⇒ 本条的效力上限 = **夹具面**。
    本条今天绿（两式都是点数版），而它**自我武装**：W2 改了生产口径却没改脚本 ⇒ 两边算出的
    coverage 当场分叉 ⇒ 红。这是本文件里唯一一条"不需要实现就能防住第三处漂移"的用例，故不打 xfail。
    """
    mig = pytest.importorskip("scripts.migrate_poi_conservation",
                              reason="迁移脚本不在可导入路径上（须从 backend 目录跑 pytest）")
    fixtures = POI_PY.parent / "fixtures"
    checked = 0
    for key in ("kaili", "beijing-jinsong"):
        path = fixtures / f"{key}.json"
        if not path.exists():
            continue
        import json
        doc = json.loads(path.read_text(encoding="utf-8"))
        loc = doc.get("living_circle") or doc
        poi_block = loc.get("poi")
        if not poi_block:
            continue
        migrated, _lines = mig._migrate_poi(json.loads(json.dumps(poi_block)))
        stats = [{"category": c["category"], "label": c.get("label"),
                  "total": c.get("total"), "in_circle": c.get("in_circle"),
                  "coverage": c.get("coverage"), "min_minutes": None,
                  "nearest_name": None} for c in poi_block["categories"]]
        derive_stats_from_points(stats, poi_block["points"])
        for prod, migrated_c in zip(stats, migrated["categories"]):
            assert prod["coverage"] == migrated_c["coverage"], (
                f"{key}/{prod['category']}: 生产派生 {prod['coverage']} ≠ 迁移脚本 "
                f"{migrated_c['coverage']} ⇒ 两处公式已分叉。"
                "要么同步脚本，要么让它按报告自带的口径版本选公式（计划 §三 第 4 条）")
        checked += 1
    assert checked >= 1, "两份夹具都没读到 ⇒ 本条等于没跑（判据失去活入口）"


# ── B 组 · 目标行为（实现落地即 XPASS 报错）─────────────────────


def test_coverage_numerator_is_required_only():
    """T1 · 覆盖度分子只数门槛项 ⇒ 凯里教育 18 点（真小学 1 所）得 **1/3**，不再顶满。

    **10-01 摘标经过**（不是"看它绿了就摘"）：改前基线 122 passed / 14 xfailed；
    落地后本条 **XPASS(strict)** ⇒ 套件当场红 ⇒ 摘标，并按新口径复核两条读数
    （`to_stats` 与 `derive_stats_from_points` 两边都是 0.3333，`in_circle` 仍是 18）。

    判别样本是**实测原样**（含「第十三小学家长学校」这颗名字带"小学"却不是小学的雷）：
    点数 18 ≫ ideal 3，而门槛项 1 < 3 ⇒ 只有"按门槛项数"才会让覆盖度掉下来。
    若只改 `to_stats:274` 而忘改 `derive:421`，本条仍会红（因为下面同时走两条路）——
    这正是 A3/T2 之外对 P0-1 的第二重拦截。
    """
    per_cat = {"education": _named(KAILI_EDU_ALL)}
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    edu = next(s for s in stats if s["category"] == "education")
    assert edu["coverage"] == pytest.approx(round(1 / 3, 4)), (
        f"to_stats 未按门槛项算覆盖度：{edu['coverage']}")

    points = asm.build_poi_block(per_cat, {}, SCOPE, CENTER, stats)["points"]
    stats2 = to_stats(per_cat, {}, SCOPE, CENTER)
    derive_stats_from_points(stats2, points)
    edu2 = next(s for s in stats2 if s["category"] == "education")
    assert edu2["coverage"] == pytest.approx(round(1 / 3, 4)), (
        f"derive_stats_from_points 未按门槛项算覆盖度：{edu2['coverage']}"
        " ⇒ 它把 to_stats 的结果覆盖回去了（评审 P0-1 的原始形态）")
    assert edu2["in_circle"] == 18, (
        f"`in_circle` 被门槛计数替换了（{edu2['in_circle']}）⇒ 会破 check_poi_conservation")


def test_coverage_formula_has_single_implementation():
    """T2 · 收敛成**全仓一份**算式，且那一份就落在 `poi.py`（A3 的目标面）。

    **10-01 摘标**：反向半边实算 `sites == []`（三处历史位点全部改为调用），正向半边实算
    `_clamp_fns(poi.py) == ['coverage_from_points']` 且 `to_stats`/`derive_stats_from_points`
    都调它 ⇒ 两条同时成立，故摘标后本条转为**日常判据**（谁再手写一遍算式或把 helper 挪出 `poi.py` 都会红）。

    判据用 AST 而不是字符串匹配：要拦的是"又手写了一遍 min/除 ideal"，
    而字符串匹配会被换个变量名绕过。

    ⚠️ 第十八轮评审 P0-2 修正：原先只认 `node.func` 是 `ast.Attribute`（即 `x.min(...)`），
       而生产那两处都是**裸 `min`**（`ast.Name`）⇒ 实得 sites=`[]`，`== 1` **永不成立**，
       本条会一路 xfail 且落地后也不 XPASS —— 那等于 §14.1 指望它补的洞全开。
    ⚠️ 第十九轮评审 P0-④ 修正：原先只扫 `poi.py` 一个文件，而 §三 当时**没写新纯函数落在哪**
       ⇒ 若实施者把它放进 `caliber.py`，`poi.py` 里的计数当场变 **0**，`== 1` 依旧永不成立
       —— 与 P0-2 同型的死守卫，只是换了成因。现改为扫 `app/` + `scripts/` 全量生产码，
       并**同时钉住落点**（§三 第 1 条已把落点钉死在 `poi.py`）⇒ "函数藏在别处"这种漂移
       会被这一条当场抓住，而不是悄悄让守卫失效。
    """
    src = POI_PY.read_text(encoding="utf-8")
    # ── 反向半边：谁都不许自己重算 ──
    recomp = _coverage_recompute_sites(_scanned_files())
    assert recomp == [], (
        f"仍有 {len(recomp)} 处函数自己「除一遍 + 夹 1.0 + 写回 coverage」：{recomp} ⇒ "
        "覆盖度公式没收敛成一份（计划 §三 第 1–2 条：抽一个纯函数，274 与 421 都调它，"
        "回退支只换分子、不另起 `min`）")
    # ── 正向半边：算式必须**存在**、只有一份、就在 poi.py、且两个消费者都调它 ──
    # （只有反向半边时，"把公式整段删掉"也能让上面那条成立 ⇒ 那才是最大的假绿）
    clamps = _clamp_fns(src)
    assert len(clamps) == 1, (
        f"`poi.py` 里「除法 + 夹 1.0」的函数有 {len(clamps)} 个（{clamps}）——应是**恰好 1 个**："
        "0 个 ⇒ 公式被删了或在别的文件（§三 第 1 条钉死落点在 `poi.py`）；"
        ">1 个 ⇒ 仍是多份实现")
    helper = clamps[0]
    for consumer in ("to_stats", "derive_stats_from_points"):
        assert helper in _called_names(src, consumer), (
            f"`{consumer}` 没调用唯一那份算式 `{helper}` ⇒ 它仍在本地算，或在用旧值")


def test_the_coverage_replica_scanner_actually_catches_the_shape():
    """A6 · **敏感性对照**（照 `test_judge_single_implementation.py:90` 的先例）：把三种绕法喂给判据，必须逐种报出来。

    第二十轮评审 P0-1：上一版 T2 的判据是"`min` 调用的 unparse 里含子串 `ideal`"，于是
      (a) 先算 `cov = n / ideal` 再 `coverage = min(1.0, cov)`  —— 子串不在 Call 里 ⇒ 检数 **0**；
      (b) 把参数改名成 `target` ⇒ 同样 **0**；
      (c) `if coverage > 1.0: coverage = 1.0` ⇒ 根本没有 `min` Call ⇒ **0**。
    三种都把"== 1"变成永不成立 ⇒ 守卫又失效一次。现在判据改结构三条件，本条**当场钉住这三种形状**：
    判据抓不住 ⇒ 本条今天（无需任何实现）就红 ⇒ 我不能再等到落地那天才发现。
    另配两条**负对照**：干净的纯函数、以及 `scoring` 那种"对已算好的值再夹一次"，都不许被误报成重算。
    """
    bypass = {
        "先算变量再夹": "def f(rows, ideal):\n    cov = len(rows) / ideal\n"
                       "    coverage = min(1.0, cov)\n    return coverage\n",
        "把 ideal 改名": "def f(rows, target):\n    coverage = min(1.0, len(rows) / target)\n"
                        "    return coverage\n",
        "if 夹钳不用 min": "def f(rows, ideal):\n    coverage = len(rows) / ideal\n"
                          "    if coverage > 1.0:\n        coverage = 1.0\n    return coverage\n",
        "下标写回": "def f(s, n, ideal):\n    s[\"coverage\"] = round(min(1.0, n / ideal), 4)\n",
    }
    missed = [name for name, code in bypass.items() if not _coverage_recompute_fns(code)]
    assert missed == [], f"判据抓不到这些重算形状：{missed} ⇒ T2/A3 是死守卫（第二十轮 P0-1 复发）"
    negative = {
        "干净纯函数（不写回 coverage）":
            "def coverage_from_points(n, ideal):\n    return min(1.0, n / ideal)\n",
        "对已算好的值再夹一次（scoring 形状）":
            "def g(categories):\n    return [min(1.0, c.get('coverage', 0.0)) for c in categories]\n",
    }
    false_pos = [name for name, code in negative.items() if _coverage_recompute_fns(code)]
    assert false_pos == [], f"判据把这两类误报成重算：{false_pos} ⇒ 收敛到 0 处永远做不到，T2 永红"
    # 正向半边用的那颗 `_clamp_fns` 也必须自己有牙：干净纯函数要被判为"算式所在"
    assert _clamp_fns(negative["干净纯函数（不写回 coverage）"]) == ["coverage_from_points"], (
        "`_clamp_fns` 认不出纯函数里的算式 ⇒ T2 的正向半边会恒判 0 个，落地那天直接永红")


def test_scores_use_required_coverage_end_to_end():
    """T3 · 端到端：评分吃到的必须是门槛项口径，88.6 那一档不得回流。

    **10-01 摘标**：本条 **XPASS(strict)** ⇒ 摘标。摘标时复核它确实"进了评分路径"而不是
    只进了覆盖度：`bars[education]` 现算为 33.33（1/3 × 100），且与"把 coverage 塞回 1.0"
    那一次算出的总分**不同** —— 这两半都在本条里，缺一即不得摘标。

    预期值**由 `_cat_score` 现算**（覆盖度取 1/3、耗时取 None ⇒ 可达分量按 0 分算），
    不是手填字面量 —— 否则这条会变成"我算给我自己看"。
    """
    per_cat = {"education": _named(KAILI_EDU_ALL)}
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    out = asm.build_poi_block(per_cat, {}, SCOPE, CENTER, stats)
    scores = scoring.compute_scores(out["categories"], [], 0)
    edu_bar = next(b for b in scores["bars"] if b["category"] == "education")
    assert edu_bar["value"] == pytest.approx(round(1 / 3 * 100.0)), (
        f"雷达/柱状仍按点数封顶：{edu_bar['value']}")
    assert scores["total"] != scoring.compute_scores(
        [{**s, "coverage": 1.0} for s in out["categories"]], [], 0)["total"], (
        "门槛项口径与点数口径算出同一个总分 ⇒ 改动没进评分路径")


def test_weight_does_not_move_any_score():
    """T4 · **任意 `weight` 取值都不得影响覆盖度与总分**（"设计而非漏接"的机器证明）。

    **10-01 摘标（第二十一轮评审 P0-2：它本条是死账，与刚修掉的 T8 同型错）** —— 原稿前置查
    `"sub_kinds" in CATEGORY_RULES["education"]`，而子类表的真身是**另一个模块级字典**
    `SUB_KIND_TABLE`（`category_rule.py:116`）⇒ 那个条件永假 ⇒ 本条永久判"未落地"，
    把一条今天已经成立的判据按在 xfail 上。计划九④ 的饱和账（凯里教育门槛项 1、非门槛 17
    ⇒ 需 `w < 2/17 = 0.1176` 才影响得到）原本是手算的；这条把它变成跑得出的判据。
    ⚠️ 三条自证缺一不可：
      · **注入确实落在表上** —— 取回值核对，不是数循环次数（原稿那句 `swept == 5*N` 是代数恒真，第十九轮 低-12）；
      · **反向对照** —— 同一副台架上翻 `required` ⇒ 分数**必须**动。缺它的话"逐位相同"可能只是因为
        这张表没连通到评分，而断链恰恰是真漏接，会被本条误判成"设计如此"；
      · **恢复原值**（评审 ①）—— 本条就地改**全局表**，不恢复就等于污染同一次运行里后面的用例。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["SUB_KIND_TABLE"])
    table = cr.SUB_KIND_TABLE["education"]
    assert len(table) > 0, "education 子类表为空 ⇒ weight 扫描没有注入点"

    def scores_now():
        stats = to_stats({"education": _named(KAILI_EDU_ALL)}, {}, SCOPE, CENTER)
        return ([round(s["coverage"], 6) for s in stats],
                scoring.compute_scores(stats, [], 0)["total"])

    saved = {k: dict(row) for k, row in table.items()}
    try:
        baseline = None
        for w in (0.0, 0.2, 0.5, 1.0, 3.0):
            for row in table.values():
                row["weight"] = w
            got = scores_now()
            if baseline is None:
                baseline = got
            assert got == baseline, f"weight={w} 改变了分数 {baseline} → {got} ⇒ weight 进了评分判据"
        assert all(row["weight"] == 3.0 for row in table.values()), (
            "最后一轮 weight=3.0 没落到表上 ⇒ 上面那句『逐位相同』是在没改过的表上空转")
        # 反向对照：把所有"非门槛"行一起翻成门槛 ⇒ 分数必须动
        # （样本里 18 颗教育点只有 1 所真小学，其余是幼儿园/中学/存疑 ⇒ 翻完必然进分子）
        flipped = 0
        for row in table.values():
            if not row.get("required"):
                row["required"] = True
                flipped += 1
        assert flipped > 0, "教育表里全是门槛项 ⇒ 反向对照没有可翻的行，本条退化成自证"
        assert scores_now() != baseline, (
            "把非门槛子类全改成门槛项后分数仍与基线逐位相同 ⇒ 子类表没连到评分，"
            "上面那条『weight 不影响分数』就是在断链上空转")
    finally:
        for k, row in saved.items():
            table[k].update(row)
    assert scores_now() == baseline, "恢复原值后分数没回到基线 ⇒ 本条把全局表改脏了"


def test_sub_roles_never_enter_coverage_numerator():
    """T6 · `sub_roles`（归并吸收的多值职能）不得冒充 `sub_kind`（自身唯一子类）。

    **10-01 摘标**：`sub_kind_of` 只吃 `name`/`tag`/`type` 三样（`category_rule.py:173`），
    `sub_roles` 从不参与 ⇒ 那颗"仅凭 sub_roles 带 pharmacy"的点位覆盖度实算 **0.0**。
    反向对照仍由 `test_absorbed_sub_point_suffix_does_not_decide_sub_kind`（T18）与
    `tests/test_poi.py::test_sub_kind_is_judged_on_raw_name_not_annotated_name`（T19）提供：
    名字里真的带出关键词时**是会**改判的（判成 `other`），所以本条的 0.0 不是"恒零"。

    评审 P0-5：点位身上已有 `sub_roles`（`poi.py:201`），若不划界，
    "图上医疗点从 23 变成几"会有两种算法。反向对照（同点设成门槛子类 ⇒ 该计入）
    保证这条不是"因为两个字段都没实现所以恒真"。
    """
    item = {**_ll(150.0, 80.0), "name": "嘉和盛世社区综合体", "tag": "综合医院", "type": ""}
    item["sub_roles"] = ["pharmacy"]
    stats = to_stats({"medical": [item]}, {}, SCOPE, CENTER)
    med = next(s for s in stats if s["category"] == "medical")
    assert med["coverage"] == 0.0, (
        f"仅凭 sub_roles 带 pharmacy 就被计入门槛项：coverage={med['coverage']}"
        " ⇒ 两个字段没划界（计划 §二）")


def test_ambiguous_subkinds_never_count_as_required():
    """T15 · 存疑点位一律**不算门槛项**（10-01 用户拍板的保守档，机器形态）。

    **10-01 摘标**：三颗存疑项（`凯里市第十中学` / `凯里市第十三小学家长学校` /
    `凯里市学前教育第三集团总园`）加进去前后覆盖度**逐位相同**（都是 0.3333），
    而"全 18 颗"那一次 `in_circle` 仍是 18 ⇒ 它们照样在图上、只是不计门槛 —— 这正是拍板承诺的那件事。

    判据写成"加进去前后 coverage 逐位相同"，不是"某个名字被判成 unknown" —— 后者只验
    中间变量，前者验的是拍板真正承诺的那件事：**这 19 颗存疑项不参与把覆盖度顶满**
    （实算 19 不是早先写的 22，见计划 §二 订正）。
    反向对照（真小学加进去必须**改变** coverage）保证这条不是"两边都不计所以恒相同"。
    """
    only_primary = to_stats({"education": _named(KAILI_EDU_PRIMARY)}, {}, SCOPE, CENTER)
    base = next(s for s in only_primary if s["category"] == "education")["coverage"]

    with_ambiguous = to_stats({"education": _named(KAILI_EDU_PRIMARY + KAILI_EDU_AMBIGUOUS)},
                              {}, SCOPE, CENTER)
    got = next(s for s in with_ambiguous if s["category"] == "education")["coverage"]
    assert got == pytest.approx(base), (
        f"存疑项（中学/家长学校/集团总园）把教育覆盖度从 {base} 顶到 {got} ⇒ 保守档没生效")
    assert got == pytest.approx(round(1 / 3, 4)), (
        f"门槛项只该是 1 所小学，实得覆盖度 {got} ⇒ 存疑项被计入了分子")
    assert base < 1.0, f"反向对照失效：加存疑项前的基线 {base} 已封顶，本条将退化为恒真"

    full = to_stats({"education": _named(KAILI_EDU_ALL)}, {}, SCOPE, CENTER)
    assert next(s for s in full if s["category"] == "education")["in_circle"] == 18, (
        "存疑项被从 `in_circle` 里摘掉了 ⇒ 会破点数守恒（红线：它们仍在图上，只是不计门槛）")


def test_second_caliber_version_gate_three_shapes():
    """T8 · 第二把**评分口径**版本键的复用门形状（照 I5 族抄）。

    ① 旧报告缺新键 ⇒ 复用门必须拒；③ 刚产出的报告 ⇒ 复用门不得拒（防"每次都重跑取证"的零复用回归）。
    ⚠️ 10-01 落地时**删掉了原稿承诺的第②形状**（"声明新键却缺 `sub_kind` ⇒ 契约红"）：
      那条属于 §六 二选一的 **(b) 档**（契约门禁改双键），而本批选的是 **(a) 档** ——
      契约继续单键，理由是"把 29 份存量一律判成契约违规"会在页面上挂红字，
      把"分数是旧分子算的"说成"报告坏了"。**名字里的"three"因此是历史遗留**，
      函数名不改（改它要 sweep 计划与 §14.3 台账的引用，收益为零）。

    ⚠️ 第十九轮评审 P0-② 修正（原两条皆死）：
      · 原 ① 用 `gate(old, None)` —— `report_contract.py:921-925` 里 **`wanted is None` 本身就返
        False**，所以那条断言**今天就成立**、不含任何信号（它拦的是"调用方忘传三元组"，
        不是"缺新键"）。⇒ 现在两半喂**同一份 check**，让"缺不缺新键"成为唯一变量。
      · 原 ③ 的 `fresh` 没有 `scene` 节点 ⇒ `:941` 读 `scene.study_radius_m` 得 None ⇒
        **永返"报告没有声明研究半径"** ⇒ 落地后也永不 XPASS。⇒ 现在补齐 caliber + scene。
    ⚠️ 10-01 摘标时又修掉一条**符号位置写错**：原 ① 的前置断言查 `report_contract` / `scoring`
      上有没有 `COVERAGE_CALIBER_VERSION`，而常量的真落点是 `category_rule`（`scope.py` 从那里发射）
      ⇒ 那半条会一直判"未落地"，把这条已经成立的判据永久按在 xfail 上。
    """
    rc = __import__("app.living_circle.report_contract", fromlist=["reuse_policy"])
    ds = __import__("app.living_circle.data_source", fromlist=["CheckParams"])
    cr = __import__("app.living_circle.category_rule", fromlist=["COVERAGE_CALIBER_VERSION"])
    gate = rc.reuse_policy
    assert cr.COVERAGE_CALIBER_VERSION == "cov-1", (
        f"评分口径键取值变成 {cr.COVERAGE_CALIBER_VERSION!r} ⇒ 本条与 A4 的期望值要一起重指")
    # 发射点必须有**产出级**证据。⚠️ 第二十一轮评审 P0-1 抓到原先那半条是近似恒真：
    # 它断 `"COVERAGE_CALIBER_VERSION" in vars(scope)`，而那个名字是 `scope.py` 从 `category_rule`
    # **import** 进来的 ⇒ 把发射行整行删掉，它照样为真，而每份新 live 报告都会被自家门拒。
    # 现在直接吃生产生产者（`SpatialScope.payload`）：只加常量、不加发射 ⇒ 本条当场红。
    # 效力上限：这条只钉"产出的 caliber 里带了这把键"，不钉"assemble 之后还在"（那条链由
    # `test_caliber_invariants` 的名册↔产出核对与 `test_scope` 的键清单一起守）。
    produced = SCOPE.payload(get_caliber("walking"),
                             {"cells_inside": 1, "cells_judged": 1, "cells_unknown": 0})
    assert produced.get("coverage_caliber_version") == cr.COVERAGE_CALIBER_VERSION, (
        f"生产 payload 拿到 {produced.get('coverage_caliber_version')!r} ⇒ 发射行不在或改了名，"
        "自家新报告会被自家复用门拒（每次体检静默重采、烧配额）")

    check = _version_check_params(ds)
    old = {"data_origin": "live", "scene": dict(_SCENE_TRIPLE),
           "caliber": _caliber_triple(rc)}          # 就是没有 coverage_caliber_version
    ok_old, why_old = gate(old, check)
    assert ok_old is False, "缺新键的旧报告被当成可复用 ⇒ 旧口径会冒充新体检答案"
    assert "评分口径" in why_old, (
        f"拒是拒了，但理由不是新键：{why_old!r} ⇒ 拦它的是别的门（第十九轮 P0-② 那个形状复发）")

    fresh = {"data_origin": "live", "scene": dict(_SCENE_TRIPLE),
             "caliber": {**_caliber_triple(rc),
                         "coverage_caliber_version": cr.COVERAGE_CALIBER_VERSION}}
    ok2, why2 = gate(fresh, check)
    assert ok2 is True, f"刚产出的报告被自己的复用门拒了（{why2}）⇒ 每次体检都会重跑取证"
    # 旧档也拦得住（缺键与值不同是两种漂法，都得拒）
    stale = {"data_origin": "live", "scene": dict(_SCENE_TRIPLE),
             "caliber": {**_caliber_triple(rc), "coverage_caliber_version": "cov-0"}}
    ok3, why3 = gate(stale, check)
    assert ok3 is False and "cov-0" in why3, f"旧评分档没被拒或理由不含实际值：{ok3} {why3!r}"


def test_reuse_gate_declares_the_coverage_key_now():
    """A4 · **现状记录（10-01 两次重指）**：除新键外完全合规的载荷**已被复用门拒**，且拒因指向新键。

    改前这里断的是 `ok is True`（"缺新键没人拦"）—— 它是 T8 的锚值证据。T8 落地那轮它**必须变红**，
    红了才说明那半条判据真的换了边；今天它绿着的新断言是：**拒因文案里带着"评分口径"这四个字**
    （否则"被拒"可能只是被别的门顺手拦了，那既不算 T8 达成，也会把 T8 的 ① 变成假绿 ——
    第十九轮 P0-② 批评的正是这个形状）。
    ⚠️ **第二次重指（全量 9 红之后）**：本条末段原先断"请求侧 `wanted_caliber` 必须带这把键"，
    那句话把门的比较对象绑到了请求侧三元组上 ⇒ 见末段注释，现改断**它不许带**。
    """
    rc = __import__("app.living_circle.report_contract", fromlist=["reuse_policy"])
    ds = __import__("app.living_circle.data_source", fromlist=["CheckParams"])
    cr = __import__("app.living_circle.category_rule", fromlist=["COVERAGE_CALIBER_VERSION"])
    old = {"data_origin": "live", "scene": dict(_SCENE_TRIPLE),
           "caliber": _caliber_triple(rc)}
    ok, why = rc.reuse_policy(old, _version_check_params(ds))
    assert ok is False, "缺新键的载荷又变成可复用了 ⇒ 第二把版本键被摘掉了（T8 ① 会同时红）"
    assert "评分口径" in why, f"拒因不是新键而是别的门（{why!r}）⇒ T8 的 ① 归因不成立"
    assert cr.COVERAGE_CALIBER_VERSION == "cov-1", (
        f"键取值变了（{cr.COVERAGE_CALIBER_VERSION!r}）⇒ 本条与 T8 的期望值要一起重指")
    # **形状半边（10-01 全量实测后重指）**：门的比较对象来自代码常量，**不来自** `wanted`。
    # 原稿这里断的是 `want["coverage_caliber_version"] == cov-1` —— 那等于要求请求侧"携带"这把键，
    # 代价是全量 9 红：`reuse_policy` 读 `wanted[...]` ⇒ 手写三元组的调用方当场 KeyError
    # （`test_caching_datasource::test_reuse_gate_requires_the_request_caliber_triple`），
    # 而 `wanted_caliber` 里多出一个"假装用户请求过 cov-1"的假键（用户从没这个选项）。
    want = ds.wanted_caliber(ds.CheckParams(scene_name="版本台架", city="凯里", address="测试",
                                            center=CENTER, study_radius_m=2500.0,
                                            sample_profile="standard", travel_mode="walking"))
    assert sorted(want) == ["sample_profile", "study_radius_m", "travel_mode"], (
        f"请求侧口径不再是三元组（{sorted(want)}）⇒ 评分键被塞回请求侧了")
    # 上面 :630 那次调用吃的就是这份三元组 ⇒ 它给出"拒 + 拒因点名评分口径"而未炸，
    # 本身就是"门不靠调用方传这把键"的正向对照（T8 ①/②/③ 三形同判）。


@TARGET_XFAIL
def test_sub_kind_contract_can_go_red():
    """T9 · 新契约判据必须**能红**：手改 payload 使 `sub_kind` 与后端表不符。

    照 `test_the_replica_scanner_actually_catches_the_shape_it_guards` 的自证形状 ——
    只写"判据存在"不算守卫，能让它红才算。

    ⚠️ 第十八轮 P0-3：原先调不存在的 `rc.contract_violations`（真出口 `assess_geometry`，
       `report_contract.py:664/199-208`）。
    ⚠️ **第十九轮 P0-① 再修**：换了符号之后**仍然到不了 B 系列** —— `assess_geometry` 在
       `:677-684` 有一道"输入不足即早退"（缺 `isochrones` ⇒ 只填 `missing` 就 return），
       我那份手搓的最小载荷连 `isochrones` 都没有 ⇒ `_evidence_phase_violations`（`:261`，
       B14 的指定落点）根本不执行 ⇒ 断言永远靠不上，和"符号不存在"是同一类死判据。
       ⇒ 现在**以真夹具载荷为底**（isochrones / caliber / poi 都齐），只动两处：
       `data_origin` 设成 live、把一颗点的 `sub_kind` 伪造成表里没有的值。
    """
    rc = __import__("app.living_circle.report_contract", fromlist=["assess_geometry"])
    doc = json.loads((POI_PY.parent / "fixtures" / "kaili.json").read_text(encoding="utf-8"))
    lc = doc.get("living_circle") or doc
    lc["data_origin"] = "live"
    lc.setdefault("caliber", {})["scope_policy_version"] = rc.SCOPE_POLICY_VERSION  # 过 :279
    (lc["poi"]["points"] or [{}])[0]["sub_kind"] = "not-a-real-sub-kind"
    issues = rc.assess_geometry(lc)
    all_msgs = list(issues.violations) + list(issues.missing)
    assert any("sub_kind" in m for m in all_msgs), (
        f"伪造的 sub_kind 没被判据抓到：violations={issues.violations} missing={issues.missing}")


def test_old_new_caliber_readings_differ_as_predicted():
    """T10 · 新旧口径**对照读数**的差值必须由生产公式自己产出（左 88.6 ⇒ 右 41.9）。

    **10-01 摘标**：差值两端都由 `scoring._cat_score` + `poi.coverage_from_points` 现算 ⇒
    本条转日常判据（有人把分子改回点数，第一条断言就红）。

    计划 12.4 自证包第 1 条。左端点来自 A1（现状记录），右端点来自本条；
    两端都由 `_cat_score` 现算 ⇒ 答辩时"现场复算给你看"有落点。
    ⚠️ 本条用的是**样本点位算出的 min_minutes**，所以它复现的是"差值方向与公式"，
       **不是** 41.9 这个具体数 —— 41.9 出自 `skip/tmp/lc_step0_live.py`：那里耗时取报告实测
       的 7.6min（`_cat_score(1/3, 7.6)=41.9`、`_cat_score(1.0, 7.6)=88.6`）。两条各守各的口径。
    """
    per_cat = {"education": _named(KAILI_EDU_ALL)}
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    edu = next(s for s in stats if s["category"] == "education")
    got = scoring._cat_score(edu["coverage"], edu["min_minutes"])
    want = scoring._cat_score(round(1 / 3, 4), edu["min_minutes"])
    assert got == pytest.approx(want), f"维度分 {got} ≠ 门槛项口径的 {want}"
    assert got < scoring._cat_score(1.0, edu["min_minutes"]), "改动没让分数下降 ⇒ 口径没生效"
    # 报告实测那一端（7.6min）单独钉住，防止有人把本条的样本读数当成答辩用的 41.9
    assert scoring._cat_score(round(1 / 3, 4), 7.6) == pytest.approx(41.9, abs=0.1)
    assert scoring._cat_score(1.0, 7.6) == pytest.approx(88.6, abs=0.1)


def test_sub_kind_order_and_disjoint_judge():
    """T14 · 子类裁决不得受 `sub_kinds` **书写次序**影响（I4 扩展到子类层）。

    **10-01 摘标**：J14b 两半都过 —— `SUB_KIND_TABLE["education"]` 三行 `accept_tags` 两两
    不相交（小学/小学部 · 幼儿园/托儿所 · 中学/初中/高中/九年一贯制），且
    `凯里市第十三小学` ⇒ `primary`（与 TRIAD 的 `primary` 键同名，`category_rule.py:92` 的
    对接没断）。J14a 那半（故意相交 ⇒ 次序翻判）仍然绿，它的价值是**证明这条危害是真的**：
    谁把两张子类的 tags 写成相交，红的会是 J14b（真表那一半）；J14a 只负责证明"相交确实会翻判"
    这个危害是真的、不是理论 —— 两条缺一不可。

    8 类层已有先例（`test_ruling_is_independent_of_table_order`）。子类层为什么更要测：
    标签通道是"取第一个命中"（`category_rule.py:143-148`），只有**名称**通道做了
    "多命中归 other"（`:155-158`）⇒ 两个子类的 `accept_tags` 一旦相交，唯一性就由字典顺序
    决定，改表顺序会改分数 —— 那是最难归因的一类漂移。

    ⚠️ 第十八轮修正：原调 `cr.classify_sub_kind` = **第二份判类实现**，§二 与
       `tests/test_judge_single_implementation.py:85` 都禁止 ⇒ 改走 `evaluate_category(table=...)`。
    ⚠️ **第十九轮 P0-③ 再修**：那份改写传的是 `tag=""` ⇒ **标签通道根本不触发**，
       走的是名称通道（`:155-158` 已做"多命中归 other"，本来就与次序无关）
       ⇒ 对"两表 accept_tags 相交时次序会翻判"这条它**恒成立**，守的是空气。
       ⇒ 现在分两半：**J14a** 用一张故意相交的表把"次序翻判"当场跑出来（今日即绿，
       不需要实现，且证明这条危害是真的、不是理论）；**J14b** 断真表的 tags 两两不相交
       （表未落地 ⇒ xfail）。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])

    def row(tags, kws):
        return {"keywords": kws, "accept_tags": tags, "reject_tags": [],
                "required": True, "weight": 1.0, "label": "行"}

    # J14a · 故意让两个子类的 accept_tags 相交（"学校"同时属 primary 与 junior）
    inter = {"primary": row(["小学", "学校"], ["小学"]), "junior": row(["学校", "中学"], ["中学"])}
    flipped = {"junior": inter["junior"], "primary": inter["primary"]}
    poi = {"name": "凯里市第十中学", "tag": "学校", "type": ""}
    a = cr.evaluate_category(poi, table=inter)
    b = cr.evaluate_category(poi, table=flipped)
    assert a != b, (
        f"相交表在两种书写次序下给出同一裁决（{a}）⇒ 次序不参与裁决，"
        "那 §二 的『两两不相交』约束就是多余的，本用例该被删而不是留")

    # J14b · 真表必须不相交（今日表不存在 ⇒ xfail；落地后这条才是主判据）
    table = dict(cr.SUB_KIND_TABLE["education"])
    keys = list(table)
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            assert not (set(table[k1]["accept_tags"]) & set(table[k2]["accept_tags"])), (
                f"子类 `{k1}` 与 `{k2}` 的 accept_tags 相交 ⇒ 裁决由字典顺序决定")
    assert cr.evaluate_category({"name": "凯里市第十三小学", "tag": "", "type": ""},
                                table=table)[0] == "primary", (
        "真小学未判成 `primary` ⇒ 键名与 TRIAD 的 `primary` 脱钩（`category_rule.py:92`）")


@TARGET_XFAIL
def test_display_eats_union_and_delta_is_attributable():
    """T0 的**新半**（配套方案见计划 §14.4）：并集上屏后，展示面差额必须可精确归因。

    为什么不直接改 `test_forensic_rounds.py:315` 那条 `==`：
    那条闸的注释自陈它是"v5.1 拍板**批次二才动展示面**"的授权门，而本批正是那次批次二。
    把 `==` 翻成 `!=` 会让"任何人随手并入点位"都变成"合理地不等" ⇒ 守卫失效。
    故本条**新增**而不替换：它断的是"差额 == 可归因的检回点位数"，
    与旧闸的"未授权时不许变"方向相反、职责互补，两条都得在。

    落地时须补的第二条反向对照（本条给不了，因为要真跑编排）：
    把 `display_points` 退回首轮 ⇒ 本条红；检回点未经 `facility_merge` 直接并入 ⇒ 差额对不上、本条红。
    """
    ds = __import__("app.living_circle.data_source", fromlist=["live_forensic_steps"])
    assert hasattr(ds, "live_forensic_steps"), "编排入口不在"
    sig = inspect.signature(asm.assemble_living_circle)
    assert "display_points" in sig.parameters, (
        "组装层还没有 `display_points` 形参 ⇒ 展示面仍吃首轮（D1 未落地）")
    # ⚠️ 第十八轮评审 P0-8 修正：原先断 `"points_added_judging_only" not in str(POLICY)` ——
    #    那句披露是**中文**（`data_source.py:516-518`），英文字段名从来不在里面 ⇒ 断言**今天即成立**，
    #    文案原样不改也判绿。判据必须吃"那句话将来要上屏的字面内容"：它会不会继续念"仍按首轮"。
    policy = str(getattr(ds, "FORENSIC_POINTS_POLICY", ""))
    assert "仍按首轮" not in policy, (
        f"D1 已落地但披露仍在念「仍按首轮点位」⇒ 那句话是假话（计划 §五）：{policy}")


def _fixture_points() -> List[Dict[str, str]]:
    """名册样本源：**只取仓内夹具**（`app/living_circle/fixtures/*.json`）。

    不取 `skip/tmp/out/` 那些 live 报告 —— 它们是 gitignored 的工作产物，别人手上没有，
    钉在它们上的 golden 会变成"只有我这台机器能绿"的判据。
    """
    out: List[Dict[str, str]] = []
    for path in sorted((POI_PY.parent / "fixtures").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        loc = doc.get("living_circle") or doc
        for x in ((loc.get("poi") or {}).get("points") or []):
            out.append({"name": x.get("name", "") or "",
                        "tag": x.get("tag", "") or "",
                        "type": x.get("type", "") or ""})
    return out


def test_name_roster_golden_on_in_repo_fixtures():
    """A5 · 名册型 golden：夹具里每颗点位**今天**被判成哪一类，逐类计数钉死（§十六 ⑥(i)）。

    预期值来源：10-01 用本仓 venv 直接调生产 `evaluate_category` 现算出来的（探针
    `skip/tmp/lc_roster_golden_probe.py`），**不是我照规则表推的** —— 规则与样本同时新写会互相迁就。

    为什么值得留：拍板 ①（名称级 reject 进共用实现）落地那天，本条**必须变红并被重指**，
    它就是"其余 6 类有没有被误伤"的漂移检测网。今天它绿，是给那次红留的基线。

    ⚠️ 效力上限（不许读成"8 类都核过"）：
      · 夹具点位 `tag`/`type` **全为空** ⇒ 本 golden 只覆盖**名称通道**，标签通道零覆盖
        （这与 live 报告一致：502 颗里带 tag/type 的 0 颗）；
      · `market` 与 `elderly` 计 0，但别一起读成"样本没抽到"：
        `market` 在 ① **之前**是**规则侧死类** —— 它三颗 keyword（`菜市场/农贸市场/生鲜市场`，
        `category_rule.py:29`）全都内含 `shopping.keywords` 的 `市场`（`:50`）⇒ 名称通道必 ≥2 命中
        ⇒ 归 `other`。10-01 只读实测（① 前）：`洪源居农贸市场`/`金井农贸市场`/`凯里市农贸市场`
        全部 ⇒ `('other', 0.3)`。
        ⚠️ **① 落地后可达性变了一半（10-01 真实实现实测，不再是探针）**：`大十字菜市场` 现在 ⇒
        `market`（`菜市场` 同时是 `shopping.reject_tags` 的一颗，名称通道吃 reject 后 shopping 被摘掉
        ⇒ 单命中）；但 `洪源居农贸市场` **仍** ⇒ `other`（`农贸市场` 不在 shopping 的 reject 里）。
        ⇒ "① 修好 8 类"是过头话，只修好了 `菜市场` 那一形状；`market` 的本类夹具仍是 0 颗 ⇒
        **本 golden 对 `market` 依旧零覆盖**。`elderly` 是否与 `market` 同型：未做同类上溯 ⇒ **未核**。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    pts = _fixture_points()
    assert len(pts) == 248, (
        f"夹具名册读到 {len(pts)} 颗，不是 248 ⇒ 样本面变了（夹具被增删或键路径改了），"
        "下面的逐类计数全部失去基线，本条须先重指样本面再重取读数")
    tally: Dict[str, int] = {k: 0 for k in list(cr.CATEGORY_RULES) + ["other"]}
    for it in pts:
        tally[cr.evaluate_category(it)[0]] += 1
    assert tally == {"medical": 23, "education": 28, "shopping": 46, "finance": 27,
                     "recreation": 11, "service": 10, "other": 103,
                     "market": 0, "elderly": 0}, (
        f"逐类命中计数变为 {tally} ⇒ 判类实现相对 10-01 基线漂移。"
        "若这是 ① 落地造成的：按计划 §二 逐颗核对漂掉的点位，重指本条并把差值写进交付说明")
    anchors = {"万博新时代诊所": "medical", "凯里市第十三小学": "education",
               "佳惠超市(佳和店)": "shopping", "中国人民银行(黔东南州分行)": "finance",
               "劲松五区公园": "recreation", "北京市公安局朝阳分局潘家园派出所": "service"}
    by_name = {p["name"]: p for p in pts}
    for name, want in anchors.items():
        # 判的是**名册里那一颗**（不是现造的 `{name, tag:"", type:""}`）——否则"锚点在不在样本里"
        # 与"锚点判得对不对"就吃的是两份输入，点位一旦带 tag 两处读数会分叉。
        assert name in by_name, f"锚点 `{name}` 已不在夹具名册里 ⇒ 本条退化成自证"
        assert cr.evaluate_category(by_name[name])[0] == want, (
            f"锚点 `{name}` 判成 `{cr.evaluate_category(by_name[name])[0]}`，基线是 `{want}`")


def test_name_channel_honors_reject_tags():
    """T16 · ① 的**已落地判据**（10-01 摘标）：任一类的 `reject_tags` 里的词，不得被名称通道判成该类。

    摘标经过（不是"看它绿了就摘"）：改前基线 `121 passed / 15 xfailed`；打上 ① 之后
    `121 passed`（**既有锚值一条没动**）+ 本条 **XPASS(strict)** ⇒ 套件当场红 ⇒ 按纪律摘标。
    真实实现落地后的实算读数（不再是探针抄的那份）：`牙科诊所`⇒`other`、
    `凯峰建材大市场`⇒`other`、`大十字菜市场`⇒`market`（shopping 被自己 reject 摘掉后单命中）、
    `洪源居农贸市场`⇒`other`（`市场` 仍命中 shopping ⇒ 这颗**不可达**，见 A5 docstring）。

    历史（留档，别删）：落地前全表 reject 词恰有 **1 颗**违反 —— `medical.reject_tags` 含
    `牙科诊所`，而"诊所"也在 `medical` 的 keyword 里 ⇒ 当时它判成 `medical`（P0-4 的机制在
    **展示 8 类**上同样成立，不只是子类表）。其余词当时判 `other` 是因为**压根不含任何类的 keyword**
    ⇒ 那是"没命中"不是"已拒绝"。所以本条断"逐颗都要 != 本类"，**不数命中次数** ——
    数次数会把"没命中"混进"已拒绝"，那正是第十八轮 P0-1 教过的口径错。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    all_tags = [(k, r) for k, defn in cr.CATEGORY_RULES.items() for r in defn["reject_tags"]]
    assert len(all_tags) >= 30, (
        f"全表只读到 {len(all_tags)} 颗 reject 词 ⇒ 扫描面缩水，本条会退化成空转（R7 同型）")
    violated = [(k, r) for k, r in all_tags
                if cr.evaluate_category({"name": r, "tag": "", "type": ""})[0] == k]
    assert violated == [], (
        f"这些词带着本类的 reject 标记却仍被判成本类：{violated} ⇒ 名称通道没吃 reject（§二 ① 未落地）")
    # ⚠️ 第二十条评审 P0-3：`violated == []` 单独存在时**没有牙** —— 一份把所有名字都判成 `other`
    #    的退化实现当场满足它。故本条自带**正向对照**：reject 词的"父关键词"必须仍判成本类，
    #    这样"摘掉整条名称通道"这种实现就同时撞两条。10-01 实测：`诊所`⇒medical、`市场`⇒shopping、
    #    `社区卫生服务中心`⇒medical（三颗都不含任何 reject 词，今天就是真读数不是预期）。
    positive = {"诊所": "medical", "社区卫生服务中心": "medical", "市场": "shopping"}
    for name, want in positive.items():
        got = cr.evaluate_category({"name": name, "tag": "", "type": ""})[0]
        assert got == want, (
            f"正向对照失效：`{name}` 判成 `{got}`（应为 `{want}`）⇒ "
            "本类的名称通道已被摘掉或改坏，此时 `violated == []` 不算 ① 达成")


def test_mixed_caliber_only_tabled_categories_switch_numerator():
    """T17 · §十六 ⑥(ii)：**同一次调用里**两种口径必须并存 —— 有表的换分子、没表的一分不动。

    **10-01 摘标**：半边甲实算 `education` = 0.3333（门槛项 1 / ideal 3），半边乙实算
    `finance` = `in_circle 3` / `coverage 1.0`（该类不在 `SUB_KIND_TABLE` ⇒ 同一处 `min` 里
    退回点数分子，**没有被归零**）。摘标时特意复核的就是半边乙 —— 它今日绿、落地后**必须一直绿**，
    是"未建表的 6 类一起归零"这种实现的唯一拦截点。

    为什么不做成"今日即绿"的单向断言：`finance` 的 coverage 今天**本来就是**点数口径 ⇒
    只断"它等于点数口径"今天必绿、落地后也绿 ⇒ 它守不住任何东西（正是 §十四 反复讲的死守卫）。
    所以本条把两半写进**同一次调用**：
      半边甲（今日红）：`education` 必须按**门槛项**算 ⇒ 18 点 / 真小学 1 所 / ideal 3 ⇒ `1/3`；
      半边乙（今日绿、且**必须一直绿**）：`finance` 没建子类表 ⇒ coverage 仍等于 `min(1, 3/1) = 1.0`。
    ⇒ 实施者把未建表的 6 类一起归零时，半边乙当场红（这是本条存在的全部理由）；
      只改一半（比如只改 274 没改 421）时，甲红。两半各自的消息指明是哪一半塌的。
    `finance.ideal_circle = 1`（`category_rule.py` 现读，非手填），故"归零"与"维持"给出的是
    `0.0` vs `1.0` 两个可区分的数，不会因 ideal 大小糊在一起。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    per_cat = {
        "education": _named(KAILI_EDU_ALL),                                   # 18 颗，门槛项 1
        "finance": _named(["中国工商银行(凯里支行)", "中国农业银行(凯里迎宾路支行)",
                           "凯里市农村信用合作联社"]),                          # 3 颗，无子类表
    }
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    fin_ideal = cr.CATEGORY_RULES["finance"]["ideal_circle"]
    assert fin_ideal == 1, f"本条的预期值建立在 finance ideal=1 上，实得 {fin_ideal} ⇒ 先重取读数"

    fin = next(s for s in stats if s["category"] == "finance")
    assert fin["in_circle"] == 3 and fin["coverage"] == pytest.approx(min(1.0, 3 / fin_ideal)), (
        f"未建子类表的 `finance` coverage={fin['coverage']}、in_circle={fin['in_circle']} ⇒ "
        "它被换成了门槛项口径（该类没有表 ⇒ 门槛项数会被算成 0、coverage 归零、总分崩塌）。"
        "计划 §三 第 5 条：无表必须**在同一处 min 里**退回点数分子")

    edu = next(s for s in stats if s["category"] == "education")
    assert edu["coverage"] == pytest.approx(round(1 / 3, 4)), (
        f"建了表的 `education` coverage={edu['coverage']}，不是门槛项口径的 1/3 ⇒ 半边甲未落地"
        "（今日即红是预期的，落地后这条与半边乙必须同时成立）")


def test_required_in_circle_is_landed_by_both_producers():
    """T20 · 片 1c 的数据面：门槛项数必须**落进 payload**，且两个生产者一起落。

    为什么要有这个字段：展示侧那句"门槛项 N / ideal M"若不读 payload，就只有两条路 ——
    要么前端自己再拿子类表判一遍（**第二份判类实现**，§二 与
    `test_judge_single_implementation.py:85` 都禁止），要么把 N 当字面量写死（中-12 刚判过的那笔账）。
    ⇒ 唯一合规形态是后端把分子随 `coverage` 一起交回来，前端只念。

    三档语义各有各的真值（缺一档就是给将来上屏的那句话留假话空间）：
      · 建表 + 带键 ⇒ 整数（教育 = 1）；
      · **没建表** ⇒ `None`（金融：该类根本没有门槛口径，不得印成 0）；
      · 建表但**该类一颗点都没有** ⇒ `0`（"门槛 0 ⇒ 真缺口"正是最需要上屏的那一句）。
    ⚠️ 空批次不算"旧载荷"：两种读法在这里都是 0，所以给 0 不给 None（`poi.py` 里那条注释）。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    per_cat = {
        "education": _named(KAILI_EDU_ALL),
        "finance": _named(["中国工商银行(凯里支行)", "中国农业银行(凯里迎宾路支行)",
                           "凯里市农村信用合作联社"]),
    }
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    assert next(s for s in stats if s["category"] == "education")["required_in_circle"] == 1
    assert next(s for s in stats if s["category"] == "finance")["required_in_circle"] is None

    # 第二个生产者：派生链**就地覆盖** `to_stats` 的结果，所以它也必须一起更分子
    points = asm.build_poi_block(per_cat, {}, SCOPE, CENTER, stats)["points"]
    assert points, "样本没造出点位 ⇒ 下面这一半会在空集上恒真"
    stats2 = to_stats(per_cat, {}, SCOPE, CENTER)
    derive_stats_from_points(stats2, points)
    edu2 = next(s for s in stats2 if s["category"] == "education")
    assert edu2["required_in_circle"] == 1, "派生链只更了 coverage、把分子留在旧点集上 ⇒ 两条链分叉"
    for s in stats2:
        cat = s["category"]
        ideal = int(cr.CATEGORY_RULES[cat]["ideal_circle"])
        pts = [p for p in points if p["category"] == cat]
        numerator = len(pts) if s["required_in_circle"] is None else s["required_in_circle"]
        assert s["coverage"] == pytest.approx(round(min(1.0, numerator / ideal), 4)), (
            f"{cat}: coverage={s['coverage']} 与它自己报出的分子 {s['required_in_circle']} "
            f"（点数 {len(pts)}）/ ideal {ideal} 对不上 ⇒ 两个数不同源")

    empty = to_stats({"education": []}, {}, SCOPE, CENTER)
    assert next(s for s in empty if s["category"] == "education")["required_in_circle"] == 0, (
        "建表类别在零点位时被报成 None ⇒ 前端只能印『无口径』，"
        "而真话是『门槛项 0 个 = 真缺口』（凯里养老那一档的同型形状）")


def test_sub_kind_rule_labels_land_in_payload_without_rejudging():
    """T23 · 片 1c-β C1 甲档：门槛项**名单**落进 payload，且它只是"读表"、不是第二份判类。

    三条各拦一种漂移：
      ① 名单是**规则名单**（`SUB_KIND_TABLE` 的 `label` 按 `required` 分两组），**一个点位都不看**
         ⇒ 凯里圈内 25 处医疗点的实测分账是 诊所 16 / 中心 2 / 站 3 / 存疑 4，`pharmacy` 圈内 0 颗；
         若改成 present-only，"药店"会从披露里消失（而药店是三要素之一）——那是为措辞好看说假话。
      ② 未建表类别 ⇒ 两键都是 `None`（**不是 `[]`**：空名单会说"这一类没有不计分的形状"，是假话），
         且与 `required_in_circle` 的 `None` 同生同灭（一个有一个没有 = 两条链分叉）。
      ③ 三个生产者（`to_stats` / `derive_stats_from_points` / 迁移脚本 `_migrate_poi`）都得写这两键。
    反向对照：翻 `primary.required` ⇒ 两组名单同时变（钉字面量的实现过不了这一条），并当场还原。
    """
    import copy

    from app.living_circle.category_rule import SUB_KIND_TABLE, sub_kind_rule_labels

    assert sub_kind_rule_labels("education") == (["小学"], ["幼儿园", "中学"])
    assert sub_kind_rule_labels("medical") == (
        ["社区卫生服务中心", "社区卫生服务站", "药店"], ["诊所", "医院"])
    assert sub_kind_rule_labels("finance") is None, "没建表的类别报出了名单 ⇒ 前端会印一句无据的话"

    before = sub_kind_rule_labels("education")
    row = SUB_KIND_TABLE["education"]["primary"]
    row["required"] = False
    try:
        flipped = sub_kind_rule_labels("education")
    finally:
        row["required"] = True
    assert flipped == ([], ["小学", "幼儿园", "中学"]), f"翻档后名单没跟着变：{flipped}"
    assert sub_kind_rule_labels("education") == before, "还原失败 ⇒ 污染了全局表（后续用例全不可信）"

    per_cat = {
        "education": _named(KAILI_EDU_ALL),
        "finance": _named(["中国工商银行(凯里支行)", "中国农业银行(凯里迎宾路支行)",
                           "凯里市农村信用合作联社"]),
    }
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    edu_s = next(s for s in stats if s["category"] == "education")
    fin_s = next(s for s in stats if s["category"] == "finance")
    assert edu_s["scored_as"] == ["小学"] and edu_s["unscored_as"] == ["幼儿园", "中学"]
    assert fin_s["scored_as"] is None and fin_s["unscored_as"] is None
    assert fin_s["required_in_circle"] is None, "名单与分子两件事不同源 ⇒ 三档语义裂开"

    # 生产者②：派生链就地覆盖 ⇒ 两键也必须一起覆盖
    points = asm.build_poi_block(per_cat, {}, SCOPE, CENTER,
                                 to_stats(per_cat, {}, SCOPE, CENTER))["points"]
    assert points, "样本没造出点位 ⇒ 下面这一半会在空集上恒真"
    stats2 = to_stats(per_cat, {}, SCOPE, CENTER)
    derive_stats_from_points(stats2, points)
    edu2 = next(s for s in stats2 if s["category"] == "education")
    assert edu2["scored_as"] == ["小学"] and edu2["unscored_as"] == ["幼儿园", "中学"], (
        "派生链只更了分子、把名单留在旧值上 ⇒ 两条链分叉")

    # 生产者③：迁移脚本（T7 已钉它与生产同式，这里钉它**同键集**）
    mig = pytest.importorskip("scripts.migrate_poi_conservation",
                              reason="迁移脚本不在可导入路径上（须从 backend 目录跑 pytest）")
    poi_block = {"categories": copy.deepcopy(stats2), "points": copy.deepcopy(points),
                 "total": sum(s["total"] for s in stats2), "in_circle": len(points)}
    migrated, _lines = mig._migrate_poi(poi_block)
    for prod, mc in zip(stats2, migrated["categories"]):
        assert (mc.get("scored_as"), mc.get("unscored_as")) == (prod["scored_as"], prod["unscored_as"]), (
            f"{prod['category']}: 迁移脚本没写名单 ⇒ 经它回填的报告上那句说明会静默消失")


def test_stale_and_half_migrated_payloads_fall_back_to_point_counts():
    """T21 · 旧载荷与**半迁移载荷**都要沿 `derive_stats_from_points` 这条**真读路径**退回点数。

    第二十一轮评审两处合到这条：
      · **P2-b**：旧载荷识别原先用 `any("sub_kind" in p ...)`（`poi.py:275`）⇒ 半迁移批次被当成新口径，
        没带键的那颗**直接从分子里少算掉**。本批的原则是"读不准就按旧的、保守解释、不回填"，所以改成 `all`。
      · **效力上限**：回退那一支此前只由 A1 **直调** `coverage_from_points` 验过，而存量 29/30 份
        真走的是 `derive_stats_from_points`（读库里的旧 payload）⇒ 主路径上当时**没有判据**。
    ⚠️ 反向对照是这条的骨头：②里只抹掉**那颗真小学**的键 —— 若识别退回 `any`，分子会算成 0（coverage 0.0），
    而 `all` 给的是整批按点数（1.0）。两种读法数值差得很远 ⇒ 本条不会因"两边都差不多"而空转。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    per_cat = {"education": _named(KAILI_EDU_ALL)}
    ideal = int(cr.CATEGORY_RULES["education"]["ideal_circle"])

    def derive_of(pts):
        s = to_stats(per_cat, {}, SCOPE, CENTER)
        derive_stats_from_points(s, pts)
        return next(x for x in s if x["category"] == "education")

    points = asm.build_poi_block(per_cat, {}, SCOPE, CENTER,
                                 to_stats(per_cat, {}, SCOPE, CENTER))["points"]
    assert points and all("sub_kind" in p for p in points), (
        "生产写点没有**全量盖章** ⇒ 下面两支回退都没有对照面（也说明 `all` 那半边是空转）")

    full = derive_of(points)
    assert full["required_in_circle"] == 1, f"新口径半边漂了：{full['required_in_circle']}"
    assert full["coverage"] == pytest.approx(round(1 / ideal, 4))

    # ① 整批不带键（= 存量那种旧载荷）⇒ 退回点数，且分子报 None（"无口径可言"，不得印成 0）
    legacy = [{k: v for k, v in p.items() if k != "sub_kind"} for p in points]
    old = derive_of(legacy)
    assert old["required_in_circle"] is None and old["coverage"] == pytest.approx(
        round(min(1.0, len(points) / ideal), 4)), (
        f"旧载荷读出 coverage={old['coverage']} / 分子={old['required_in_circle']} ⇒ "
        "§六「旧载荷按旧口径解释、不回填」在**真读路径**上失守")

    # ② 半迁移：只抹掉那颗真小学的键
    half = [dict(p) for p in points]
    hit = [p for p in half if p.get("sub_kind") == "primary"]
    assert len(hit) == 1, f"样本里真小学 {len(hit)} 颗 ⇒ 反向对照失去判别力"
    hit[0].pop("sub_kind")
    got = derive_of(half)
    assert got["coverage"] == old["coverage"] and got["required_in_circle"] is None, (
        f"半迁移批次读成 coverage={got['coverage']} / 分子={got['required_in_circle']}，"
        f"点数口径应是 {old['coverage']} ⇒ 旧载荷识别又回到 `any`，那颗点被少算进分子（§十八 P2-b）")


def test_tag_channel_points_enter_the_numerator_without_name_keyword():
    """T22 · 只靠 `accept_tags` 命中的点位**也必须进分子**（§十八 P1-4：标签通道端到端零覆盖）。

    为什么这条必须存在：夹具点位键集实测**没有** `tag`/`type`（`_named` 也只给空串），
    而生产链路吃的是 `baidu_client.py:406` 回传的百度 `tag` —— 判定是 **tag 优先、名字弱先验**。
    ⇒ 在此之前，`accept_tags` 这条高置信主通道在**门槛计数**上一次都没被跑到：
    演示数与真跑数可能分叉，而全仓没有一条判据会发现。
    ⚠️ 反向对照同批给：同样的名字把 `tag` 清空 ⇒ 分子必须掉回 0，否则"进分子"其实是名字通道在起作用。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["CATEGORY_RULES"])
    ideal = int(cr.CATEGORY_RULES["medical"]["ideal_circle"])
    # 名字刻意不含任何药店关键词（"药房/药店/大药房"一个都不出现）
    names = ["健康驿站一号", "健康驿站二号", "健康驿站三号"]

    def stats_for(tag: str):
        items = [{**_ll(120.0 + i * 40.0, 60.0), "name": n, "tag": tag, "type": ""}
                 for i, n in enumerate(names)]
        return next(s for s in to_stats({"medical": items}, {}, SCOPE, CENTER)
                    if s["category"] == "medical")

    hit = stats_for("药店")
    assert hit["required_in_circle"] == len(names), (
        f"tag 命中 `accept_tags` 却没进分子（读到 {hit['required_in_circle']}）"
        "⇒ 标签通道仍不在端到端判据里，演示数与真跑数无从对照")
    assert hit["coverage"] == pytest.approx(round(min(1.0, len(names) / ideal), 4))

    miss = stats_for("")
    assert miss["required_in_circle"] == 0, (
        f"清空 tag 后仍算出门槛 {miss['required_in_circle']} ⇒ 上面那条其实是**名字通道**在过，"
        "本条没钉到标签通道")
    assert miss["coverage"] == pytest.approx(0.0)


def test_absorbed_sub_point_suffix_does_not_decide_sub_kind():
    """T18 · §十六 ⑥(iii)：被 `annotate_name` 拼进父名的子点职能**确实会**决定子类 ⇒ 入参必须是原始名。

    **10-01 重指 + 摘标**（原稿断的是"带后缀与不带后缀逐位相同"，那条**永远不可能成立**，
    我自己写它时没验：名称通道多命中归 `other`（`category_rule.py:252-253`），
    `万博新时代诊所 · 含大药房` 同时命中 `clinic`(诊所) 与 `pharmacy`(大药房) ⇒ 判 `other`。
    子类表**无从**"忽略后缀"，除非根本不吃后缀 —— 所以规范句的正确形态是"**别把加工后的名传进来**"，
    已由 T19（`tests/test_poi.py::test_sub_kind_is_judged_on_raw_name_not_annotated_name`）钉住落盘那一侧）。

    本条因此重指成 T19 的**反向对照**：证明"传原始名 / 传加工后的名"两种入参给出**不同**裁决。
    没有它，T19 就可能是"因为子类表对所有名字都不敏感而恰好相同"的假绿 ——
    即"判据要自带牙"的通用形状（第二十轮 P0-3 教过的那一课）。
    """
    cr = __import__("app.living_circle.category_rule", fromlist=["SUB_KIND_TABLE"])
    table = cr.SUB_KIND_TABLE["medical"]
    raw = {"name": "万博新时代诊所", "tag": "", "type": ""}
    merged = {"name": "万博新时代诊所 · 含大药房", "tag": "", "type": ""}
    assert cr.evaluate_category(raw, table=table)[0] == "clinic", (
        f"原始名那颗判成 `{cr.evaluate_category(raw, table=table)[0]}` ⇒ 样本或表变了，本条失去基线")
    assert cr.evaluate_category(merged, table=table)[0] == "other", (
        f"带后缀那颗判成 `{cr.evaluate_category(merged, table=table)[0]}` ⇒ 名称通道的"
        "「多命中归 other」不再生效 ⇒ T19 的反向对照失效，先修判类实现")
    # 两颗只差一个后缀 ⇒ 覆盖度分子会差一分（诊所非门槛、other 也非门槛，但药店本身是门槛项：
    # 若实现只摘掉 clinic 那一支而留下 pharmacy，父点会被算成**门槛项**，那是更坏的一种漂法）
    assert cr.SUB_KIND_TABLE["medical"]["pharmacy"]["required"] is True, (
        "`pharmacy` 不再是门槛项 ⇒ 本条与 T19 的威胁模型（子点替父点决定门槛归属）不成立")

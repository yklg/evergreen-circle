"""一次性回填（v7.2 片 1b 尾）：把 **4 份演示夹具**换成 `cov-1` 口径的产物。**零真实调用**。

## 做什么（三步全部走生产出口，脚本不写第二份算式）

1. 每颗点位盖上 `sub_kind` —— `category_rule.sub_kind_of`；8 类里**没建子类表的类别 ⇒ `null`**，
   与 `poi.to_points` 的落盘形状逐键相同（键集严格全等的那三条断言因此不会分叉）。
2. `categories[].coverage` = `poi.coverage_from_points(该类点集, ideal_circle, 该类)`，
   并把**同一颗 helper 报出的分子**写进 `categories[].required_in_circle`（没建表的类别 ⇒ `null`）。
   分子必须一起落盘：否则展示侧要么读不到"门槛项 N"，要么自己去重判一遍子类（第二份实现）。
3. `scores` 整块 = `scoring.compute_scores(...)` 重算。`note` 里那四个维度数**由生产函数自己写**，
   脚本不手改文案（同一条目里"字段值 + 文案数"必须同源，否则就是一句假话上了屏）。

## 为什么不碰 DB 里那 30 份存量（计划 §十）

存量点位**不带 `sub_kind`** ⇒ `coverage_from_points` 走"整批缺键 ⇒ 分子退回点数"那一支，
读数一条都不会动 —— 那是 §六 读侧规则的设计，不是漏改。本脚本只动演示夹具，
代价是**夹具派生锚要重取**（§5.1 行 12：`test_poi_metric_label_*`、A5 名册、镜像闸、居住类基线闸）。

## 改前自证（不通过就拒绝写盘）

先用**未改的** `categories` 调一次 `compute_scores`（`judged_share` 从载荷自带的 `scores.evidence` 回读），
复算结果必须在**存量已有的键**上逐字段等于存量。不相等 ⇒ 这份夹具的评分不是当前生产函数产出的，
回填得到的差值无法归因到"覆盖度分子" ⇒ 直接退出，不写一个字节。

后端 / 前端**必须同批**：`tests/test_fixture_mirror.py` 对 `poi` 块做双侧深比较，只改一侧当场红。

用法：
    cd backend && .venv/bin/python -m scripts.backfill_fixture_subkind --check
    cd backend && .venv/bin/python -m scripts.backfill_fixture_subkind
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.living_circle import scoring  # noqa: E402
from app.living_circle.category_rule import (  # noqa: E402
    CATEGORY_RULES,
    COVERAGE_CALIBER_VERSION,
    sub_kind_of,
    sub_kind_rule_labels,
)
from app.living_circle.poi import (  # noqa: E402
    check_poi_conservation,
    coverage_from_points,
    required_count_from_points,
)

SCENES = ["kaili", "beijing-jinsong"]
BACKEND_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"
)
# `annotate_name` 的后缀形态（`facility_rule.py:241`）。子类判定**只许吃它加工之前的名字**（§二）：
# 夹具里一旦存在带后缀的点，本脚本就没有"原始名"可判 ⇒ 当场停，不猜、不剥字符串。
SUFFIX_MARK = " · 含"


def _backfill_lc(lc: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """就地回填一个 `living_circle` 块；返回 (lc, 人读差异行)。"""
    lines: List[str] = []
    poi = lc["poi"]
    points = poi.get("points") or []

    bad = [p.get("name") for p in points if SUFFIX_MARK in (p.get("name") or "")]
    if bad:
        raise RuntimeError(
            f"夹具里有 {len(bad)} 颗点位名带 `· 含` 后缀（例：{bad[:3]}）⇒ 手里只有加工过的名字，"
            "按 §二 规范句不得用它判子类。请先在采集侧留原始名，再回来跑本脚本。")

    stored_scores: Dict[str, Any] = lc.get("scores") or {}
    before = scoring.compute_scores(
        poi["categories"], stored_scores.get("triads") or [], len(lc.get("blindspots") or []),
        judged_share=(stored_scores.get("evidence") or {}).get("judged_share"),
        evidence_complete=True,
    )
    # 闸只卡**数值键**（`total`/`bars`/`radar`/`triads`/`evidence`/`confidence`）：它们才是
    # "回填的差值能不能归因到覆盖度分子"的那条链。`note` 是一句渲染文案，自 09-19 快照以来
    # 生产自己多出了"1 类圈内无可达设施不计入可达维度"这一句 ⇒ 它必然不同，**不卡**，
    # 但必须**当场披露**（不披露就等于把无关 diff 混进口径回填里）。
    drift = [k for k in stored_scores if k != "note"
             and json.dumps(before.get(k), sort_keys=True, ensure_ascii=False)
             != json.dumps(stored_scores[k], sort_keys=True, ensure_ascii=False)]
    if drift:
        raise RuntimeError(
            f"改前自证不过：未改动的 `categories` 复算出的 {drift} 与夹具存量不等 ⇒ 这份夹具的评分"
            "不是当前生产函数产出的，回填差值无法归因（先修可复现性，再谈回填）")
    note_drift = ("note" in stored_scores
                  and stored_scores["note"] != before.get("note"))

    for p in points:
        cat = str(p.get("category"))
        p["sub_kind"] = sub_kind_of({"name": p.get("name") or "",
                                     "tag": p.get("tag") or "",
                                     "type": p.get("type") or ""}, cat)

    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for p in points:
        by_cat.setdefault(str(p.get("category")), []).append(p)
    added_key = 0
    added_label_keys = 0
    for c in poi["categories"]:
        cat = str(c.get("category"))
        pts = by_cat.get(cat, [])
        ideal = int((CATEGORY_RULES.get(cat) or {}).get("ideal_circle") or 1)
        old = c.get("coverage")
        req = required_count_from_points(pts, cat)
        new = round(coverage_from_points(pts, ideal, cat), 4)
        if old != new:
            lines.append(f"    {cat:<11} coverage {old} → {new}"
                         f"（图上 {len(pts)} 颗 · 门槛项 {'无表' if req is None else req}"
                         f" · ideal {ideal}）")
        c["coverage"] = new
        # 分子也落盘：前端那句"门槛项 N / ideal M"只许读 payload，不许自己按子类表再判一遍
        # （那是展示侧的第二份判类实现）。符号名见计划 §四 第 6 条。
        if "required_in_circle" not in c:
            added_key += 1
        c["required_in_circle"] = req
        # 片 1c-β C1 甲档：门槛项**名单**一起落盘（`sub_kind_rule_labels` 只读表、不吃点位，
        # 所以它不是第二份判类实现）。缺这两键的旧快照 ⇒ 前端那句"只数「小学」"不出现，
        # 而不是被前端拿名字自己凑出来。
        labels = sub_kind_rule_labels(cat)
        if "scored_as" not in c or "unscored_as" not in c:
            added_label_keys += 1
        c["scored_as"] = labels[0] if labels else None
        c["unscored_as"] = labels[1] if labels else None
    if added_key:
        lines.append(f"    （新落键：{added_key} 个类别补上 `required_in_circle`，"
                     "没建子类表的类别值为 null）")
    if added_label_keys:
        lines.append(f"    （新落键：{added_label_keys} 个类别补上 `scored_as`/`unscored_as`，"
                     "没建子类表的类别两个都是 null）")

    after = scoring.compute_scores(
        poi["categories"], stored_scores.get("triads") or [], len(lc.get("blindspots") or []),
        judged_share=(stored_scores.get("evidence") or {}).get("judged_share"),
        evidence_complete=True,
    )
    # 只回写**存量本来就有的键**：键集增长（如给 09-19 那份快照补 `confidence`/`evidence`）
    # 与本次口径回填无关，混进同一个 diff 里就看不出"改了哪几个数"。
    new_scores = {k: after[k] for k in stored_scores if k in after}
    if new_scores.get("total") != stored_scores.get("total"):
        lines.append(f"    总分 {stored_scores.get('total')} → {new_scores.get('total')}")
    old_radar = {r["dimension"]: r["score"] for r in stored_scores.get("radar") or []}
    for r in new_scores.get("radar") or []:
        if old_radar.get(r["dimension"]) != r["score"]:
            lines.append(f"    维度 {r['dimension']} {old_radar.get(r['dimension'])} → {r['score']}")
    old_bar = {b["category"]: b["value"] for b in stored_scores.get("bars") or []}
    for b in new_scores.get("bars") or []:
        if old_bar.get(b["category"]) != b["value"]:
            lines.append(f"    柱状 {b['category']} {old_bar.get(b['category'])} → {b['value']}")
    if new_scores.get("note") != stored_scores.get("note"):
        lines.append(f"    note → {new_scores.get('note')}")
        if note_drift:
            lines.append("    ⚠️ 上面那句与 cov-1 **无关**：这份夹具的 `note` 自 09-19 起就与生产当前"
                         "文案不同（差的是「不计入可达维度」那句披露），回填会一并刷新")
    lc["scores"] = new_scores
    # **必须一起声明版本键**：回填后的数字是新分子算的，载荷却不带 `cov-1` 的话，
    # 读侧（`reuse_policy`、前端 `staleCaliberNotice`）会把这份夹具当成"旧口径产物"解释 ——
    # 那是一句由我们自己写下的假话。（采集口径那把 `ev-*` 键**不动**：本脚本没改判盲证据域。）
    cal = lc.setdefault("caliber", {})
    old_cal_ver = cal.get("coverage_caliber_version")
    if old_cal_ver != COVERAGE_CALIBER_VERSION:
        lines.append(f"    caliber.coverage_caliber_version {old_cal_ver!r} → "
                     f"{COVERAGE_CALIBER_VERSION!r}")
    cal["coverage_caliber_version"] = COVERAGE_CALIBER_VERSION
    return lc, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只打印差异，不落盘")
    args = ap.parse_args()

    rc = 0
    for key in SCENES:
        paths = {"backend": BACKEND_DIR / f"{key}.json", "frontend": FRONTEND_DIR / f"{key}.json"}
        texts = {}
        for label, p in paths.items():
            if not p.exists():
                print(f"❌ 缺少 {label} 夹具：{p}")
                return 1
            texts[label] = p.read_text(encoding="utf-8")

        docs = {label: json.loads(t) for label, t in texts.items()}
        locs = {label: (d.get("living_circle") or d) for label, d in docs.items()}
        if locs["backend"]["poi"] != locs["frontend"]["poi"]:
            print(f"❌ {key}: 回填前 `poi` 块双侧已不一致 —— 先修镜像，再回填口径")
            rc = 1
            continue

        bad_roundtrip = [
            label for label, raw in texts.items()
            if json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            + ("\n" if raw.endswith("\n") else "") != raw
        ]
        if bad_roundtrip:
            print(f"❌ {key}[{'/'.join(bad_roundtrip)}]: 夹具序列化非幂等（重写会引入格式抖动）—— 请人工核对")
            rc = 1
            continue

        try:
            backfilled, lines = _backfill_lc(json.loads(texts["backend"]))
        except RuntimeError as exc:
            print(f"❌ {key}: {exc}")
            rc = 1
            continue

        issue = check_poi_conservation(backfilled["poi"])
        if issue is not None:
            print(f"❌ {key}: 回填后不守恒 —— {issue}")
            rc = 1
            continue
        fresh = {label: _backfill_lc(json.loads(raw))[0] for label, raw in texts.items()}
        if fresh["backend"]["poi"] != fresh["frontend"]["poi"]:
            print(f"❌ {key}: 回填后 `poi` 块双侧不一致 —— 停下，交给人工核对（镜像闸会红）")
            rc = 1
            continue
        for label, lc in fresh.items():
            lc["scores"] = dict(backfilled["scores"])   # 评分只算一次，两侧写同一份

        print(f"[{key}] 回填{'预览（--check，未写盘）' if args.check else '落盘'}")
        for line in lines or ["    （读数无变化）"]:
            print(line)
        if args.check:
            continue
        for label, p in paths.items():
            if "living_circle" in docs[label]:
                docs[label]["living_circle"] = fresh[label]
            else:
                docs[label] = fresh[label]
            out = json.dumps(docs[label], ensure_ascii=False, indent=2)
            out += "\n" if texts[label].endswith("\n") else ""
            p.write_text(out, encoding="utf-8")

    if args.check:
        print("\n（--check 干跑，未写盘）")
    return rc


if __name__ == "__main__":
    sys.exit(main())

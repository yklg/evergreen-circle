"""片 1-pre 探针：给判表**加游客类别键**，会不会改判居住档 POI。

为什么必须先跑它（计划 D7 的放行条件）：`evaluate_category` 是**全局单表**判类
（`category_rule.py:113-145`），新增键不是"多一类可选"，而是**参与同一轮裁决**——
新键的 `keywords` / `accept_tags` 一旦与现有居住类的名称/标签相撞，POI 就会被抢走，
居住档的逐类目计数随之变化。用户明确要求"优先保居住基线不动"，所以这一步是闸，
不是礼节。

**取数点只能在采集层，不能拿 fixture 重放**（实测核查，2026-09-27）：

* `FixtureDataSource.compute` 返回的是**已组装好的报告快照**，压根不重跑判类；
* 两城 fixture 的 `poi.points` 里带 `tag`/`type` 的点是 **0 个**，其余段也没有原始 POI 集；
* `scripts/make_fixture_points.py` 即使重生成也不写 tag（点位经 `poi.to_points`
  唯一出口时只留契约字段）。

⇒ 因此 `--source fixture` 模式只能覆盖**名称弱先验那半边**判据（`tag`/`reject_tags`
分支不可达），产出是**下界**，**不得**当作放行依据；真放行要用 `--source snapshot`
喂一份采集层抓的原始快照（`services/baidu.py:115` 的归一出口带 `tag`）。

用法：
    cd backend && python -m scripts.probe_category_key_delta --source fixture
    cd backend && python -m scripts.probe_category_key_delta --source snapshot --snapshot <path>

`--source snapshot` 的快照形状 = `{ "<category>": [ {name, lng, lat, tag?, type?}, ... ] }`
（即采集层 `per_category` 原样 dump）。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.living_circle import category_rule  # noqa: E402
from app.living_circle.category_rule import CATEGORY_RULES, evaluate_category  # noqa: E402

RESIDENTIAL = list(CATEGORY_RULES.keys())

# D7 点名的 7 个游客候选键。**只是探针输入，不是最终判表** —— 词表宽严直接决定改判面，
# 所以结果必须连同这份输入一起读。ideal_circle 对计数无影响（探针不看评分），占位 1。
VISITOR_CANDIDATES: Dict[str, Dict[str, Any]] = {
    "scenic": {"label": "风景名胜", "keywords": ["景区", "景点", "风景名胜", "古镇", "公园", "博物馆"],
               "accept_tags": ["风景名胜", "景区", "博物馆", "公园", "古镇"], "reject_tags": [], "ideal_circle": 1},
    "dining": {"label": "餐饮", "keywords": ["餐厅", "饭店", "小吃", "面馆", "火锅", "奶茶", "咖啡"],
               "accept_tags": ["餐厅", "小吃快餐", "饮品", "火锅"], "reject_tags": [], "ideal_circle": 1},
    "lodging": {"label": "酒店", "keywords": ["酒店", "宾馆", "旅馆", "民宿", "客栈"],
                "accept_tags": ["宾馆旅店", "酒店", "民宿"], "reject_tags": [], "ideal_circle": 1},
    "parking": {"label": "停车场", "keywords": ["停车场", "停车楼", "地下停车"],
                "accept_tags": ["停车场", "露天停车场"], "reject_tags": [], "ideal_circle": 1},
    "toilet": {"label": "公共厕所", "keywords": ["公共厕所", "厕所", "卫生间"],
               "accept_tags": ["公共厕所", "公厕"], "reject_tags": [], "ideal_circle": 1},
    "visitor_center": {"label": "游客中心", "keywords": ["游客中心", "游客服务", "集散中心"],
                       "accept_tags": ["游客中心"], "reject_tags": [], "ideal_circle": 1},
    "transit": {"label": "交通站点", "keywords": ["公交站", "客运站", "火车站", "地铁站", "机场"],
                "accept_tags": ["公交站", "地铁站", "火车站", "机场", "长途汽车站"], "reject_tags": [], "ideal_circle": 1},
}

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"


def _extended_table() -> Dict[str, Any]:
    """旧表 + 游客候选键（深拷贝，绝不改注册表本身）。"""
    table = copy.deepcopy(CATEGORY_RULES)
    for key, rule in VISITOR_CANDIDATES.items():
        assert key not in table, f"候选键 {key} 已在判表里，探针失去意义"
        table[key] = rule
    return table


def _classify_with(table: Dict[str, Any], pois: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """在给定判表下逐点判类，返回 (旧类, 新类) 里用到的**新类**序列。

    只 monkeypatch 迭代视图：`evaluate_category` 内部读 `CATEGORY_RULES.items()`，
    所以这里复刻它的裁决次序而**不碰全局注册表**（改全局表会让同进程的其他用例串味）。
    """
    out: List[str] = []
    for poi in pois:
        out.append(_evaluate_against(table, poi))
    return out


def _evaluate_against(table: Dict[str, Any], poi: Dict[str, Any]) -> str:
    """`category_rule.evaluate_category` 的**同序本地版**，唯一差别是判表由入参给。

    次序必须与生产一致，否则测的就不是同一套口径；两处若有出入，以生产为准。
    """
    def norm(s: Any) -> str:
        return (s or "").strip().lower() if isinstance(s, str) else ""

    if not isinstance(poi, dict) or not poi.get("name"):
        return "other"
    tag = norm(poi.get("tag", "") or "")
    typ = norm(poi.get("type", "") or "")
    name = norm(poi.get("name", ""))
    if any(no == tag for no in category_rule._NOISE_TAGS) or tag in category_rule._NOISE_TAGS:
        return "other"
    best = "other"
    for key, defn in table.items():
        a_hit, r_hit = category_rule._tag_hit(tag or typ, defn["accept_tags"], defn["reject_tags"])
        if r_hit:
            continue
        if a_hit:
            return key
        if any(norm(kw) in name for kw in defn["keywords"]):
            best = key
    return best


def _self_check_against_production(pois: List[Dict[str, Any]]) -> None:
    """本地复刻判类必须与生产 `evaluate_category` **逐点同判**，否则探针数字无意义。

    这是探针自己的守卫：复刻裁决次序是本项目最容易悄悄跑偏的一件事（生产判表一改，
    这里不同步就会产出一张"看起来很干净"的假 delta 表）。不一致 ⇒ 直接拒绝出结果。
    """
    mismatches = [
        (p.get("name", ""), _evaluate_against(CATEGORY_RULES, p), evaluate_category(p)[0])
        for p in pois
        if _evaluate_against(CATEGORY_RULES, p) != evaluate_category(p)[0]
    ]
    if mismatches:
        sample = "；".join(f"{n}: 复刻 {a} ≠ 生产 {b}" for n, a, b in mismatches[:5])
        raise SystemExit(
            f"探针自检失败：本地复刻与生产判类有 {len(mismatches)} 处分歧 ⇒ 先同步 "
            f"`_evaluate_against` 与 `category_rule.evaluate_category` 再跑。示例：{sample}"
        )


def _load_pois(source: str, snapshot: Path | None) -> Tuple[List[Dict[str, Any]], str]:
    if source == "snapshot":
        if snapshot is None or not snapshot.exists():
            raise SystemExit(f"--source snapshot 需要可读的快照路径（{snapshot}）")
        raw = json.loads(snapshot.read_text(encoding="utf-8"))
        pois = [dict(it, __from=cat) for cat, items in raw.items() for it in items or []]
        return pois, f"snapshot（采集层原始快照，含 tag ⇒ 全量判据可达）：{snapshot.name}"
    pois: List[Dict[str, Any]] = []
    for name in ("kaili.json", "beijing-jinsong.json"):
        d = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for p in d["poi"]["points"]:
            pois.append({"name": p.get("name"), "tag": p.get("tag", ""), "type": p.get("type", "")})
    return pois, (
        f"fixture 点位（{len(pois)} 个，**无 tag/type** ⇒ 仅名称弱先验半边可达，"
        "结果为**下界**，不作放行判据）"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("fixture", "snapshot"), default="fixture")
    ap.add_argument("--snapshot", type=Path)
    args = ap.parse_args()

    pois, note = _load_pois(args.source, args.snapshot)
    _self_check_against_production(pois)
    before = _classify_with(CATEGORY_RULES, pois)
    after = _classify_with(_extended_table(), pois)

    def counts(seq: List[str]) -> Dict[str, int]:
        out = {k: 0 for k in RESIDENTIAL}
        for c in seq:
            out[c] = out.get(c, 0) + 1
        return out

    c_before, c_after = counts(before), counts(after)
    changed = [(p.get("name", ""), b, a) for p, b, a in zip(pois, before, after) if b != a]

    print(f"样本来源：{note}")
    print(f"样本量：{len(pois)}   候选游客键：{len(VISITOR_CANDIDATES)}")
    print("\n居住档逐类目计数（旧表 → 新表）：")
    for cat in RESIDENTIAL:
        d = c_after[cat] - c_before[cat]
        print(f"  {cat:<11} {c_before[cat]:>4} → {c_after[cat]:>4}   delta {d:+d}")
    print(f"  {'other':<11} {c_before.get('other', 0):>4} → {c_after.get('other', 0):>4}")
    print(f"\n改判点位数：{len(changed)} / {len(pois)}")
    for name, b, a in changed[:40]:
        print(f"  · {name}  {b} → {a}")
    if len(changed) > 40:
        print(f"  …另有 {len(changed) - 40} 条")
    verdict = "居住档计数零变化" if all(c_after[c] == c_before[c] for c in RESIDENTIAL) else "居住档计数发生变化 ⇒ 阻断片 1"
    print(f"\n判定：{verdict}")
    if args.source == "fixture":
        print("提醒：本模式 tag 半边不可达，零变化 ≠ 放行；放行需 --source snapshot。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

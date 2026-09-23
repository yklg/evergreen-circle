"""一次性迁移（阶段 1.6 / 1.7）：把 4 份 fixture 的 `poi` 块收敛到**点数守恒**。

## 为什么需要它

两份夹具（`kaili` / `beijing-jinsong`）都是**旧版 `cap_per_cat=25` 截断**留下的产物：

| 夹具 | `poi.total` | 旧 `in_circle` | `len(points)` | 差值 | 成因 |
|---|---|---|---|---|---|
| kaili | 217 | 104 | 98 | −6 | `shopping` 圈内 31 被截到 25 |
| beijing-jinsong | 175 | 114 | 104 | −10 | `shopping` 圈内 35 被截到 25 |

差值**逐类定位**后唯一差异源都是 `shopping`：其余 7 类各自守恒（差值 0）。
于是前端「面板写圈内 104 处 / 图上 98 个点」——正是用户报的「点位与图例对不上」
在演示数据里的形态。

## 怎么做（与 D1 一致）

**不补造点位数据**（那需要编 6 个点的经纬度与名称 ⇒ 制造假数据，不予采用），
而是让统计字段向**唯一真身 `points`** 收敛：

- `categories[].in_circle` ← 该类别在 `points` 里的实际条数；
- `categories[].coverage` ← `min(1, in_circle / ideal_circle)` 重算（与 `poi.to_stats` 同式）；
- `poi.in_circle` ← `sum(categories[].in_circle)`；
- `poi.total` ← **不动**（采集口径，含圈外）；
- 新增 `poi.truncated` 与 `poi.conservation`：与 `build_poi_block` 产出的形状一致，
  同时充当「本夹具已是新口径产物」的机器可读标记。

语义上这是自洽的：它只表示「这份手编样本里购物类圈内就是 25 处」，不撒谎。
将来若用 live 管线重生成（`cap=200` 下 31 个购物点全进），夹具自然变成 104，与本次修正不冲突。

## 后端 / 前端**必须同批改**

`tests/test_fixture_mirror.py:26-44` 把 `poi` 与 `sampling` 列为「渲染核心必须集」做**双侧深比较**，
只改一侧 ⇒ `test_living_circle_fixtures_mirror_frontend` 直接判红。本脚本默认两侧一起写。

用法：
    cd backend && .venv/bin/python -m scripts.migrate_poi_conservation --check   # 干跑
    cd backend && .venv/bin/python -m scripts.migrate_poi_conservation           # 落盘
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.living_circle.category_rule import CATEGORY_RULES  # noqa: E402
from app.living_circle.poi import POI_CAP_PER_CAT, check_poi_conservation  # noqa: E402

SCENES = ["kaili", "beijing-jinsong"]
BACKEND_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"
)


def _migrate_poi(poi: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """就地收敛一个 `poi` 块；返回 (poi, 人读差异行)。"""
    lines: List[str] = []
    counts: Dict[str, int] = {}
    for p in poi.get("points") or []:
        key = str(p.get("category"))
        counts[key] = counts.get(key, 0) + 1

    old_in = int(poi.get("in_circle") or 0)
    for c in poi.get("categories") or []:
        cat = str(c.get("category"))
        n = counts.get(cat, 0)
        old = int(c.get("in_circle") or 0)
        ideal = int((CATEGORY_RULES.get(cat) or {}).get("ideal_circle") or 1)
        new_cov = round(min(1.0, n / ideal), 4)
        if old != n or c.get("coverage") != new_cov:
            lines.append(
                f"    {cat:<11} in_circle {old} → {n}"
                f"（该类别 points={n}）  coverage {c.get('coverage')} → {new_cov}"
            )
        c["in_circle"] = n
        c["coverage"] = new_cov

    poi["in_circle"] = sum(int(c.get("in_circle") or 0) for c in poi.get("categories") or [])
    # `total` 是采集口径（含圈外），**不动**。
    poi["truncated"] = {"cap_per_cat": POI_CAP_PER_CAT, "dropped": 0, "categories": []}
    poi["conservation"] = {
        "ok": True,
        "declared_in_circle": poi["in_circle"],
        "actual_points": len(poi.get("points") or []),
    }
    lines.insert(0, f"    （旧 poi.in_circle {old_in} → {poi['in_circle']}）")
    return poi, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只打印差异，不落盘")
    args = ap.parse_args()

    rc = 0
    for key in SCENES:
        paths = {"backend": BACKEND_DIR / f"{key}.json", "frontend": FRONTEND_DIR / f"{key}.json"}
        for label, p in paths.items():
            if not p.exists():
                print(f"❌ 缺少 {label} 夹具：{p}")
                return 1

        texts = {label: p.read_text(encoding="utf-8") for label, p in paths.items()}
        docs = {label: json.loads(t) for label, t in texts.items()}
        locs = {label: (d.get("living_circle") or d) for label, d in docs.items()}

        # 只要求 **`poi` 块**双侧一致：夹具允许「盲区可选元数据单向增补」
        # （`footprint_meta`/`polygon_raw`，见 test_fixture_mirror.py:12），
        # 实测 beijing-jinsong 的前端侧就多这两个字段 ⇒ 不能要求整文件逐字节相同。
        if locs["backend"]["poi"] != locs["frontend"]["poi"]:
            print(f"❌ {key}: 迁移前 `poi` 块双侧已不一致 —— 先修镜像，再迁守恒")
            rc = 1
            continue

        # 序列化**幂等性前置检查**：只有当「读进来再写出去」与原文逐字节相同时，
        # 才允许整文件重写 —— 否则会在 diff 里混入大量与本次修复无关的格式抖动，
        # 让「改了哪几个数字」无法被 review（本项目 diff 要能一眼看懂）。
        bad_roundtrip = [
            label
            for label, raw in texts.items()
            if json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            + ("\n" if raw.endswith("\n") else "")
            != raw
        ]
        if bad_roundtrip:
            print(f"❌ {key}[{'/'.join(bad_roundtrip)}]: 夹具序列化非幂等（重写会引入格式抖动）—— 请人工核对")
            rc = 1
            continue

        poi, lines = _migrate_poi(dict(locs["backend"]["poi"]))
        issue = check_poi_conservation(poi)
        if issue is not None:
            print(f"❌ {key}: 迁移后仍不守恒 —— {issue}")
            rc = 1
            continue

        print(f"[{key}] poi.in_circle={poi['in_circle']}  points={len(poi['points'])}  ✅ 守恒")
        for line in lines:
            print(line)

        if args.check:
            continue
        for label, p in paths.items():
            locs[label]["poi"] = dict(poi)
            out = json.dumps(docs[label], ensure_ascii=False, indent=2)
            out += "\n" if texts[label].endswith("\n") else ""
            p.write_text(out, encoding="utf-8")

    if args.check:
        print("\n（--check 干跑，未写盘）")
    return rc


if __name__ == "__main__":
    sys.exit(main())

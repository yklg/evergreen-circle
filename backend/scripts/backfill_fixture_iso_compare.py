"""笔 B（演示态补齐）：把 `iso_compare` 离线补进两份镜像夹具，让对照环在演示态真的看得见。

**零外呼、零分数变更、零几何重算**：那条环由生产函数从每份夹具**自己的** 1049 个采样点现切
（`idw_from_local` + `IsochroneEngine._ring_zone_at`，与 live 链同一个实现，不在这里另写一份
插值或等值线代码 —— 那正是本仓在消灭的「同一语义多份实现」）。

为什么必须做这一步：夹具是 10-01 代次烘的，没有这一位 ⇒ 图例里那颗折叠标题**整块不出现**
（缺席即不渲染是对的），于是评审用的演示态永远看不到 B 这条。补法沿用 `backfill_fixture_detour.py`
那套两趟式工具（默认 `--check`，任一不过就一份都不写）。

用法：
    .venv/bin/python scripts/backfill_fixture_iso_compare.py --check   # 只核对与试算，不写盘
    .venv/bin/python scripts/backfill_fixture_iso_compare.py --apply   # 全过后写出

四条硬前置（任一不成立就拒绝写）：
 ① 排版保真：`json.dumps(doc, indent=2, ensure_ascii=False)` 必须与原字节相同（行尾换行原样保留）。
 ② 诚实闸：只对 `interpolation == 'idw'` 且 `travel_mode == 'walking'` 的实测场补 ——
    8min 这个阈值出自高龄**步行**窗口，骑行/驾车档在口径表里根本没声明它（`iso_compare_min=None`），
    给它们补一条环等于把步行文献贴到车速上；离线件（`circular_approx`）也不补（恒等式场再切一刀
    是「用估算对照估算」）。
 ③ **复算自证**（这条是本工具独有的，也是最重要的一条）：先用同一套代码把夹具里**已有的四档**
    等时圈重切一遍，面积必须与落库值逐档相符（容差 0.5%）。对不上就说明这份夹具的场不是当前
    代码能复现的（网格、步长或投影某一处不同），那我算出的第八条线也不属于那张场 —— 拒绝写。
    没有这道闸，我可以很顺利地把一条"看起来对"的环烘进演示数据，而它其实来自另一个场。
 ④ 逐字段证明 + 契约自校：改动路径集合必须**恰好等于** `{iso_compare}`；并且产出的那份载荷
    要能过它自己的契约 B16（`_iso_compare_violations == []`）—— 工具不该烘出连自家契约都不认的件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent

FIXTURES: List[Path] = []
for sub, name in (("kaili.json", "kaili.json"),
                  ("kaili-ev2.json", "kaili-ev2.json"),
                  ("beijing-jinsong.json", "beijing-jinsong.json")):
    FIXTURES.append(BACKEND / "app" / "living_circle" / "fixtures" / name)
    FIXTURES.append(PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle" / sub)

sys.path.insert(0, str(BACKEND))
import numpy as np  # noqa: E402

from app.living_circle.caliber import ISO_COMPARE_BASIS, get_caliber  # noqa: E402
from app.living_circle.geo_utils import to_local_xy  # noqa: E402
from app.living_circle.isochrone import (  # noqa: E402
    MODE_PARAMS,
    IsochroneEngine,
    idw_from_local,
)
from app.living_circle.report_contract import _iso_compare_violations  # noqa: E402

ALLOWED_PATHS = {"iso_compare"}


class AlreadyBaked(Exception):
    """该份夹具已带这一位且与现算结果逐字相同 ⇒ 幂等跳过，不是错误。"""
AREA_TOL = 0.005          # 复算四档的容差（0.5%）；超了就说明这份场不是当前代码复现得出来的


def _payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    """夹具既可能是裸 `living_circle` 载荷，也可能裹在报告外壳里 —— 两种都吃。"""
    return doc.get("living_circle", doc)


def _diff_paths(before: Any, after: Any, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            if k not in before or k not in after:
                out.append(f"{prefix}{k}")
            else:
                out.extend(_diff_paths(before[k], after[k], f"{prefix}{k}."))
    elif before != after:
        out.append(prefix.rstrip(".") or "<root>")
    return out


def _field_at(center, study, n, pts, mins):
    """按候选网格重算一次插值场（生产 `idw_from_local`，不另写一份）。"""
    sample_xy = np.array([to_local_xy(center, p[0], p[1]) for p in pts], dtype=float)
    grid_xy, step = IsochroneEngine()._grid_coords(center, study, n)
    return idw_from_local(sample_xy, mins, grid_xy).reshape(n, n), step


def _four_zone_drift(field, n, step, center, study, stored):
    """逐档复算已落库的四档面积，返回 (最大相对漂移, 人话说明)。切不出环 ⇒ (None, 说明)。"""
    worst, notes = 0.0, []
    for minutes, area in sorted(stored.items()):
        again = IsochroneEngine()._ring_zone_at(field, minutes, center, study, step,
                                                (n - 1) // 2, (n - 1) // 2)
        if again is None:
            return None, f"{minutes}min 切不出环"
        drift = abs(again["area_km2"] - area) / max(area, 1e-9)
        notes.append(f"{minutes}min {again['area_km2']} vs {area} ({drift * 100:.2f}%)")
        worst = max(worst, drift)
    return worst, " ".join(notes)


def _insert_after(lc: Dict[str, Any], anchor_key: str, new_key: str, value: Any) -> Dict[str, Any]:
    """按位置插键（`dict.update` 只会追加到末尾，而载荷里 `iso_compare` 该紧挨着 `isochrones`）。

    键序不进任何判据，但进 diff 的可读性 —— 与产出它的生产代码同序，下次人读 diff 才不用
    在两份"内容相同、顺序不同"的 JSON 之间做人工对齐。
    """
    if anchor_key not in lc:
        raise AssertionError(f"夹具里没有锚键 {anchor_key} ⇒ 无法按位置插入 {new_key}")
    out: Dict[str, Any] = {}
    for k, v in lc.items():
        out[k] = v
        if k == anchor_key:
            out[new_key] = value
    return out


def build(f: Path) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
    src = f.read_text(encoding="utf-8")
    doc = json.loads(src)
    trailing = "\n" if src.endswith("\n") else ""

    # ① 排版保真
    re_dumped = json.dumps(doc, indent=2, ensure_ascii=False)
    if re_dumped != src.rstrip("\n"):
        raise AssertionError(
            f"{f.name}: 重新序列化与原文件不一致（长度 {len(re_dumped)} vs {len(src.rstrip())}）"
            "⇒ 夹具写口用的格式与此处不同，硬写会把整份文件重排、diff 看不出改了啥。拒绝。")

    lc = _payload(doc)
    sampling, caliber = lc["sampling"], lc.get("caliber") or {}
    travel_mode = caliber.get("travel_mode") or "walking"

    # ② 诚实闸
    if sampling.get("interpolation") != "idw":
        raise AssertionError(
            f"{f.name}: interpolation={sampling.get('interpolation')!r} 不是实测场 ⇒ 不该补对照环")
    level = get_caliber(travel_mode).iso_compare_min
    if level is None:
        raise AssertionError(
            f"{f.name}: {travel_mode} 档口径表没声明对照阈值 ⇒ 补环等于把步行文献贴到别的速度上")

    center = tuple(lc["scene"]["center"])
    study = float(lc["scene"]["study_radius_m"])
    pts = [(p["lng"], p["lat"]) for p in sampling["points"]]
    mins = [p.get("minutes") for p in sampling["points"]]
    stored = {int(z["minutes"]): float(z["area_km2"]) for z in lc.get("isochrones") or []}
    if not stored:
        raise AssertionError(f"{f.name}: 没有 isochrones 可对账 ⇒ 无法证明复现的是同一张场")

    spec_n = int((sampling.get("spec") or {}).get("grid_n") or 0)
    # 老夹具（`kaili.json` / `beijing-jinsong.json`）连 `spec` 都没有 ⇒ 不猜网格：
    # 把生产 `MODE_PARAMS` 里的候选逐个试，**只有能把已落库四档逐档复算相符的那一个
    # 才算这张场的真网格**。全不对就拒绝写 —— 这条闸比"我记得当年是 66"硬得多。
    candidates = [spec_n] if spec_n > 0 else sorted({int(v["grid_n"]) for v in MODE_PARAMS.values()})
    matched = None
    for n in candidates:
        field, step = _field_at(center, study, n, pts, mins)
        drift, why = _four_zone_drift(field, n, step, center, study, stored)
        if drift is None:
            continue
        if drift <= AREA_TOL:
            if matched and matched[1] != drift:
                raise AssertionError(f"{f.name}: 两个候选网格都复现得出来（{matched[1]} / {drift}）"
                                     "⇒ 无法唯一确定这张场的网格，拒绝")
            matched = (n, drift, field, step, why)
    if not matched:
        detail = "; ".join(
            f"n={n}: " + (_four_zone_drift(_field_at(center, study, n, pts, mins)[0], n,
                                           _field_at(center, study, n, pts, mins)[1],
                                           center, study, stored)[1] or "无环")
            for n in candidates)
        raise AssertionError(
            f"{f.name}: 没有任何候选网格能逐档复现落库四档 ⇒ 这份场不是当前代码复现得出来的。{detail}")
    grid_n, max_drift, field, step, _per = matched
    rc = cc = (grid_n - 1) // 2
    zone = IsochroneEngine()._ring_zone_at(field, level, center, study, step, rc, cc)
    if zone is None:
        raise AssertionError(f"{f.name}: {level}min 档切不出环（几何退化）⇒ 诚实的形态是不补，不是补个假的")
    cmp_block = {
        "minutes": zone["minutes"],
        "geojson": zone["geojson"],
        "area_km2": zone["area_km2"],
        "basis": ISO_COMPARE_BASIS,
        "claim": "caliber_comparison_only",
    }
    if cmp_block["minutes"] in stored:
        raise AssertionError(f"{f.name}: {level}min 与已有档位重合 ⇒ 会变成第五条政策档，拒绝")

    # 幂等：已经烘过 ⇒ 逐字相同就是"无事可做"，不同就是有人手改过夹具（那才是要报警的）。
    # ⚠️ 不能让它掉进下面那条"改动面超出允许集合"的判据里 —— 那会把"已经是对的"报成
    # "少了 iso_compare"，一条假错误；下一个人会去"修"一个没坏的东西。
    already = lc.get("iso_compare")
    if already is not None:
        # 按**盘上形态**比：生产函数给的是元组，JSON 读回来是数组 —— 直接 `==` 会把
        # "已经烘对了"判成"有人手改过"（本工具第一次幂等复跑就是这么假报的）。
        if json.dumps(already, sort_keys=True) == json.dumps(cmp_block, sort_keys=True):
            raise AlreadyBaked(f.name)
        raise AssertionError(
            f"{f.name}: 已存在 iso_compare 但与现算结果不同 ⇒ 有人手改过夹具，"
            f"请核对后再决定（不静默覆盖你的在制品）")

    new_doc = dict(doc)
    new_lc = _insert_after(lc, "isochrones", "iso_compare", cmp_block)
    if "living_circle" in doc:
        new_doc["living_circle"] = new_lc
    else:
        new_doc = new_lc

    # ④ 逐字段证明 + 契约自校
    changed = set(_diff_paths(json.loads(src), new_doc))
    if changed != ALLOWED_PATHS:
        raise AssertionError(
            f"{f.name}: 改动面超出允许集合 ⇒ 多了 {sorted(changed - ALLOWED_PATHS)}、"
            f"少了 {sorted(ALLOWED_PATHS - changed)}")
    issues = _iso_compare_violations(new_lc)
    if issues:
        raise AssertionError(f"{f.name}: 产出的载荷过不了自家契约 B16 ⇒ {issues}")
    return src, trailing, new_doc, cmp_block, grid_n, max_drift


def main() -> int:
    apply = "--apply" in sys.argv
    print("（--check 模式：只核对与试算，不写盘）" if not apply else "（--apply：先全部核对，全过才写）")

    # 两趟：任一不过就一份都不写（写成"边验边写"会让第 5 份失败时前 4 份已落盘 ⇒ 镜像分叉）
    pending: List[Tuple[Path, str]] = []
    errors: List[str] = []
    baked: List[str] = []
    for f in FIXTURES:
        if not f.exists():
            errors.append(f"✗ {f.relative_to(PROJECT)}: 文件不存在")
            continue
        try:
            src, trailing, doc, cmp_block, grid_n, max_drift = build(f)
        except AlreadyBaked as e:
            baked.append(e.args[0])
            continue
        except AssertionError as e:
            errors.append(f"✗ {e}")
            continue
        body = json.dumps(doc, indent=2, ensure_ascii=False) + trailing
        if body == src:
            errors.append(f"✗ {f.name}: 算出的内容与原文逐字相同 ⇒ 本次不会有任何生效")
            continue
        pending.append((f, body))
        lc = _payload(doc)
        areas = {int(z["minutes"]): z["area_km2"] for z in lc["isochrones"]}
        fifteen = areas.get(15) or 0.0
        pct = round(100 * cmp_block["area_km2"] / fifteen, 1) if fifteen else None
        print(f"✓ {f.relative_to(PROJECT)}｜{cmp_block['minutes']}min 环 {cmp_block['area_km2']} km²"
              f"｜网格 n={grid_n} 复算四档逐档相符（最大漂移 {max_drift * 100:.2f}%，容差 {AREA_TOL * 100:.1f}%）"
              f"｜占 15min 圈 {pct}%"
              f"｜环点数 {len(cmp_block['geojson']['coordinates'][0])}"
              f"｜+{len(body) - len(src)} 字节")

    if baked:
        print(f"○ {len(baked)} 份已烘过且逐字相同 ⇒ 幂等跳过：{', '.join(baked)}")
    for line in errors:
        print(line)
    if errors:
        print(f"\n{len(errors)} 份未通过核对 ⇒ **一份都没写**（原子性）。")
        return 1
    if not pending:
        print("\n全部已烘过，本次零写入（幂等）。")
        return 0
    if not apply:
        print(f"\n{len(pending)} 份全部通过核对。加 --apply 才写盘。")
        return 0
    for f, body in pending:
        f.write_text(body, encoding="utf-8")
    print(f"\n已写出 {len(pending)} 份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

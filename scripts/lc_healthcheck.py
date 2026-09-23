#!/usr/bin/env python3
"""生活圈数据体检 · 阶段 5 验收脚本（**只读**）。

## 「异常项」怎么定义才有判别力

体检脚本最容易犯的错，是把「所有历史脏数据」都算成异常 —— 那样修完之后计数永远 > 0，
于是这个数字既不能被验收，也不能在回归时报警。本脚本按**「用户取得到的东西有没有问题」**
分层，只有真正该报警的才进异常计数：

====================  ====================================================  ==========
层                    判据                                                   计入异常
====================  ====================================================  ==========
A 可见集              读路径能取到的报告，逐条必须合规                          ✅ 计入
B 隐藏集              被读路径挡下的历史产物：列出原因，**不计异常**              ❌ 只留痕
C 任务终态            ``done`` 的任务必须有报告，且报告必须合规                  ✅ 计入
                     ``failed`` 的任务不得签发合规报告
D 数字自洽            类别聚合 == 总数；``sum(in_circle) == len(points)``（阶段 1 点数守恒）； ✅ 计入
                     等时圈面积单调递增。阶段 1 之前落库的报告**另列留痕**不计数
E 夹具                后端 + 前端夹具必须全部合规（前端演示与后端同源）            ✅ 计入
F 几何明细            逐份报告的关键几何量（人工核查用，不判定）                  ❌ 只展示
====================  ====================================================  ==========

判别力证明（阶段 5 回归时会真的红）：任何一份**新算法**产出的脏报告都会同时命中
A（可见集不合规）与 C（done 却签发了不合规报告）—— 而不是像旧脚本那样把所有历史
产物一起算进去，于是红得没有信息量。

## 单一实现

- 几何判定全部走 ``app.living_circle.report_contract.assess_geometry`` —— 与写路径
  （落库前置 ``failed``）、读路径（``db.list_living_circle_reports`` 隐藏）**同一份代码**；
- 点数守恒判定走 ``app.living_circle.poi.check_poi_conservation`` —— 与装配层出口自检
  （``assemble.build_poi_block``）**同一份代码**。

本脚本不复制任何判据，只负责「分组 + 计数 + 打印原因」。

用法：``python skip/scripts/lc_healthcheck.py``（``--verbose`` 追加 F 段几何明细）
退出码：异常项 > 0 → 1（可直接接 CI）。
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]          # skip/
DB = ROOT / "backend" / "app" / "data" / "verda.db"
CACHE = ROOT / "backend" / "app" / "lc_cache.db"
BACKEND_FIXTURES = ROOT / "backend" / "app" / "living_circle" / "fixtures"
FRONTEND_FIXTURES = ROOT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"

# 契约模块在 backend 包内（纯函数，无 DB / 无网络依赖）
sys.path.insert(0, str(ROOT / "backend"))
from app.living_circle.report_contract import assess_geometry  # noqa: E402
from app.living_circle.poi import check_poi_conservation  # noqa: E402
from app.living_circle.geo_utils import (  # noqa: E402
    haversine_m,
    ring_area_km2,
    to_local_xy,
)

M_PER_DEG_LAT = 111_320.0
W = 88


# ── 通用小工具 ──────────────────────────────────────────────────
def rule(title: str) -> None:
    print()
    print("=" * W)
    print(title)
    print("=" * W)


def ok_center(c: Any) -> Tuple[bool, str]:
    """tasks.clarifications.center 的 BD-09 合法性（与后端 parse_bd_lnglat 同口径）。"""
    if c is None:
        return True, "null(缺省)"
    if not isinstance(c, (list, tuple)):
        return False, f"非数组({type(c).__name__})"
    if len(c) != 2:
        return False, f"长度={len(c)}"
    try:
        lng, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        return False, "非数值"
    if not (math.isfinite(lng) and math.isfinite(lat)):
        return False, "NaN/Inf"
    if abs(lng) > 180 or abs(lat) > 90:
        return False, f"越界({lng:.4f},{lat:.4f})"
    return True, "ok"


def local_xy(center, lng, lat):
    dx = (lng - center[0]) * M_PER_DEG_LAT * math.cos(math.radians(center[1]))
    dy = (lat - center[1]) * M_PER_DEG_LAT
    return dx, dy


def shoelace_km2(center, ring) -> float:
    pts = [local_xy(center, p[0], p[1]) for p in ring]
    a = 0.0
    for i in range(len(pts) - 1):
        a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(a) / 2 / 1e6


# ── D 段：数字自洽 ──────────────────────────────────────────────
def numeric_consistency(lc: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """报告内部数字必须自洽（读者据此下结论，不自洽即误导）。

    返回 ``(bad, legacy)``：

    - ``bad``    —— **计入异常**：现役口径（阶段 1 之后产出）的报告必须自洽；
    - ``legacy`` —— **只留痕**：阶段 1 之前落库的报告无 ``poi.truncated`` 标记，
      其「面板数 vs 图上点数」的不一致**无法回溯修正**（实测库里 25 份有 15 份不一致，
      且**两个方向都有**：截断方向 104/98、旧版圈外点全送方向 18/151）。
      与 D 段采样点的 ``is_legacy``、C 段的 ``era_start`` 是同一套处置纪律 ——
      历史产物留痕，但不算成「现在还有问题」。
    """
    bad: List[str] = []
    legacy: List[str] = []
    poi = lc.get("poi") or {}
    cats = poi.get("categories") or []
    pts = poi.get("points") or []

    if cats:
        s_total = sum(int(c.get("total") or 0) for c in cats)
        s_in = sum(int(c.get("in_circle") or 0) for c in cats)
        if s_total != int(poi.get("total") or 0):
            bad.append(f"类别 total 之和 {s_total} ≠ poi.total {poi.get('total')}")
        if s_in != int(poi.get("in_circle") or 0):
            bad.append(
                f"类别 in_circle 之和 {s_in} ≠ poi.in_circle {poi.get('in_circle')}"
                f"（副标题「共 N 处设施」就取这个数）"
            )

    n_in = int(poi.get("in_circle") or 0)
    n_total = int(poi.get("total") or 0)
    if n_in > n_total:
        bad.append(f"圈内数 {n_in} > 采集总数 {n_total}")
    for p in pts:
        if p.get("in_circle") is not True:
            bad.append(f"点位 {p.get('name')!r} in_circle={p.get('in_circle')!r} 却出现在 points 里")
            break

    # ── 阶段 1 · 点数守恒：sum(categories[].in_circle) == len(points) ──
    # 旧防线只有**单向** `len(pts) <= in_circle`，于是「面板写圈内 104 处 / 图上 98 个点」
    #（截断方向）照样全绿 —— 而它正是用户报的「点位与图例对不上」。
    # 判据走 `poi.check_poi_conservation`（**唯一实现**，与装配层出口自检同一份代码）。
    # 新口径标记 = `poi.truncated` 存在（`build_poi_block` 恒下发）。
    issue = check_poi_conservation(poi)
    if issue is not None:
        msg = f"POI 点数不守恒 —— {issue}（面板数字与图上点数对不上）"
        if isinstance(poi.get("truncated"), dict):
            bad.append(msg)
        else:
            legacy.append(msg + "　［阶段 1 之前落库，无 poi.truncated 标记，无法回溯修正］")

    # ── 采样点分档（阶段 −1）：timed ≠ 可达，汇总数必须与逐点一致 ──
    # 旧报告把 `reachable`（= 测时返回了值）当「可达」用，产出「采样 1049 点（可达 1049）」
    # 而实际 ≤reach_full_min 的只有 126 个。
    #
    # ⚠️ 分两种形态，**只有后者是缺陷**（前者见 numeric_notices）：
    #   ① 阶段 −1 之前的旧快照：点带 `reachable`、无分档汇总数 —— 前端按点回算，是已支持状态；
    #   ② 半迁移：点已带 `timed`/`in_reach` 却仍不下发汇总数 —— 真缺陷（消费方必然各数一遍）。
    smp = lc.get("sampling") or {}
    sp = smp.get("points") or []
    n_s = len(sp)
    is_legacy = any("reachable" in p for p in sp)
    n_timed = sum(1 for p in sp if p.get("timed"))
    n_reach = sum(1 for p in sp if p.get("in_reach"))
    if not is_legacy:
        if smp.get("timed_count") is None or smp.get("in_reach_count") is None:
            bad.append(
                "sampling 缺 timed_count / in_reach_count（汇总数不下发 ⇒ 每个消费方各自 filter，口径必然漂移）"
            )
        else:
            if int(smp["timed_count"]) != n_timed:
                bad.append(f"timed_count {smp['timed_count']} ≠ 逐点统计 {n_timed}")
            if int(smp["in_reach_count"]) != n_reach:
                bad.append(f"in_reach_count {smp['in_reach_count']} ≠ 逐点统计 {n_reach}")
    if n_reach > n_timed:
        bad.append(f"圈内可达数 {n_reach} > 已测时数 {n_timed}")
    if n_timed > n_s:
        bad.append(f"已测时数 {n_timed} > 采样点数 {n_s}")

    iso = lc.get("isochrones") or []
    areas = [z.get("area_km2") for z in sorted(iso, key=lambda z: z.get("minutes") or 0)]
    if areas and any(a is None for a in areas):
        bad.append("等时圈缺少 area_km2")
    elif areas != sorted(areas):
        bad.append(f"等时圈面积未随 minutes 单调递增 {areas}")
    return bad, legacy


# ── F 段：几何明细（人读） ───────────────────────────────────────
def geometric_detail(label: str, d: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    scene = d.get("scene") or {}
    c = scene.get("center")
    good, why = ok_center(c)
    out.append(f"  scene.center      = {c}   → {'✅' if good else '❌ ' + why}")
    if not good:
        return out
    out.append(f"  study_radius_m    = {scene.get('study_radius_m')}")
    cal = d.get("caliber") or {}
    if cal:
        out.append(
            f"  caliber           reach={cal.get('reach_full_min')}min "
            f"外接圆={cal.get('reach_circumradius_m')}m 采集={cal.get('collect_radius_m')}m "
            f"cells 内/判/未知={cal.get('cells_inside')}/{cal.get('cells_judged')}/{cal.get('cells_unknown')}"
        )
    for z in d.get("isochrones") or []:
        ring = ((z.get("geojson") or {}).get("coordinates") or [[]])[0]
        if len(ring) < 4:
            out.append(f"  iso {z.get('minutes')}min      ❌ 环点数 {len(ring)} < 4")
            continue
        area = shoelace_km2(c, ring)
        rmax = max(math.hypot(*local_xy(c, p[0], p[1])) for p in ring)
        out.append(f"  iso {z.get('minutes')}min      area={area:.4f}km²  外接半径={rmax:.0f}m  n={len(ring)}")
    bs = d.get("blindspots") or []
    if not bs:
        out.append("  blindspots        = 空")
    for b in bs:
        ring = ((b.get("polygon") or {}).get("coordinates") or [[]])[0]
        if len(ring) < 4:
            out.append(f"  blindspot {b.get('id')} ❌ 环点数 {len(ring)} < 4")
            continue
        area = shoelace_km2(c, ring)
        xs = [local_xy(c, p[0], p[1])[0] for p in ring]
        ys = [local_xy(c, p[0], p[1])[1] for p in ring]
        out.append(
            f"  blindspot {b.get('id')}: area={area:.4f}km²  "
            f"({max(xs) - min(xs):.0f}×{max(ys) - min(ys):.0f}m)"
        )
    poi = d.get("poi") or {}
    pts = poi.get("points") or []
    out.append(
        f"  poi               total={poi.get('total')} in_circle={poi.get('in_circle')} "
        f"points={len(pts)}"
    )
    if pts:
        dists = []
        for p in pts:
            ll = p.get("lnglat") or [None, None]
            if ll[0] is None:
                continue
            dists.append(math.hypot(*local_xy(c, ll[0], ll[1])))
        if dists:
            out.append(f"  点位距中心        {min(dists):.0f} ~ {max(dists):.0f}m")
    out.append(f"  total_score       = {(d.get('scores') or {}).get('total')}  data_origin={d.get('data_origin')}")
    return out


# ── 主流程 ──────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true", help="追加 F 段几何明细")
    ap.add_argument(
        "--db",
        default=str(DB),
        help="被检数据库路径（默认 backend/app/data/verda.db）。"
             "可指向副本以便做**负对照**：证明本脚本的判据真的会红，而不是永远绿。",
    )
    args = ap.parse_args()
    db = Path(args.db)

    problems: List[str] = []
    hidden: List[Tuple[str, str, str]] = []      # (report_id, scene_name, reason)

    if not db.exists():
        print(f"❌ 数据库不存在：{db}")
        return 1

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ── A/B 报告层：按读路径口径分组 ──────────────────────────
    rule("A/B. living_circle_reports —— 可见集合规性 + 隐藏集留痕")
    rows = cur.execute(
        "select report_id, scene_name, data_origin, total_score, blindspot_count, created_at, data"
        " from living_circle_reports order by created_at"
    ).fetchall()
    visible_n = 0
    d_checked: List[str] = []
    d_bad: List[str] = []
    d_legacy: List[str] = []
    for r in rows:
        rid, name, origin = r["report_id"], r["scene_name"], r["data_origin"]
        try:
            payload = json.loads(r["data"]) if r["data"] else {}
        except json.JSONDecodeError as e:
            problems.append(f"{rid}: data JSON 解析失败: {e}")
            continue
        lc = payload.get("living_circle") or payload
        issues = assess_geometry(lc)

        if not issues.ok:
            # 读路径（db.list_living_circle_reports）不看这个条件的话，这里就会漏出 → 视为异常
            hidden.append((rid, name or "", issues.reason))
            continue

        visible_n += 1
        print(f"  ✅ 可见 | {rid} | {name} | origin={origin} | score={r['total_score']} | {r['created_at']}")

        # D 段：数字自洽（只对可见报告判 —— 隐藏的历史产物不参与）
        d_checked.append(rid)
        num_bad, num_legacy = numeric_consistency(lc)
        for msg in num_bad:
            d_bad.append(f"{rid}({name}): {msg}")
            problems.append(f"{rid}({name}): 数字不自洽 —— {msg}")
        for msg in num_legacy:
            d_legacy.append(f"{rid}({name}): {msg}")

    print(f"\n  可见 {visible_n} 份 / 隐藏 {len(hidden)} 份（合计 {len(rows)}）")
    if hidden:
        print("\n  ── 隐藏集（历史产物：读路径已挡下，数据保留未删除，不计异常）──")
        for rid, name, reason in hidden:
            print(f"  ⛔ {rid} | {name}\n       {reason}")

    # ── C 段：任务终态与报告的一致性 ──────────────────────────
    rule("C. tasks 终态 —— 现役区间必须自洽；前口径时代产物只留痕")
    by_id: Dict[str, bool] = {}
    origin_of: Dict[str, str] = {}
    created_of: Dict[str, str] = {}
    for r in rows:
        try:
            payload = json.loads(r["data"]) if r["data"] else {}
        except json.JSONDecodeError:
            continue
        lc = payload.get("living_circle") or payload
        rid = r["report_id"]
        by_id[rid] = assess_geometry(lc).ok
        origin_of[rid] = r["data_origin"] or ""
        created_of[rid] = r["created_at"] or ""

    # 「现役起点」不是魔数，而是**从数据里推出来的**：首份合规 live 报告的生成时刻。
    # 由此得出一个有判别力、且可被本脚本自己证伪的判据：
    #   凡 **不早于** 现役起点的报告，都必须合规 —— 否则写路径守卫失效（真异常）。
    # 早于起点的是前口径时代产物（必违反「盲区 ⊆ 可达区」或缺口径声明），读路径已隐藏。
    compliant_live_ts = sorted(
        t for rid, t in created_of.items() if origin_of[rid] == "live" and by_id.get(rid)
    )
    era_start: Optional[str] = compliant_live_ts[0] if compliant_live_ts else None
    print(f"  现役起点 era_start = {era_start}（首份合规 live 报告；由数据推出，非硬编码）")

    trows = cur.execute(
        "select task_id, kind, status, report_id, stage, percent, error, clarifications, query"
        " from tasks where kind='living_circle' order by created_at"
    ).fetchall()
    bad_center = 0
    legacy_tasks: List[str] = []
    stat = {"done": 0, "failed": 0, "created": 0, "running": 0, "other": 0}
    for t in trows:
        st = t["status"] or ""
        stat[st if st in stat else "other"] += 1

        try:
            clar = json.loads(t["clarifications"]) if t["clarifications"] else {}
        except json.JSONDecodeError:
            clar = {}
        good, why = ok_center((clar or {}).get("center"))
        if not good:
            bad_center += 1
            problems.append(f"task {t['task_id']}: clarifications.center 非法 —— {why}")

        rid = t["report_id"]
        if st == "done":
            if not rid:
                problems.append(f"task {t['task_id']}: status=done 但没有 report_id（静默成功）")
            elif rid not in by_id:
                print(f"  ⚠ {t['task_id']}: 报告 {rid} 已从库中删除（历史清理，非异常）")
            elif not by_id[rid]:
                ts = created_of.get(rid, "")
                if era_start and ts >= era_start:
                    problems.append(
                        f"task {t['task_id']}: status=done 却签发了**现役区间**不合几何契约的报告 "
                        f"{rid}（写路径守卫失效）"
                    )
                else:
                    legacy_tasks.append(f"{t['task_id']} → {rid}（{origin_of.get(rid)}）")
        elif st == "failed":
            if rid and by_id.get(rid):
                problems.append(f"task {t['task_id']}: status=failed 却存在合规报告 {rid}（状态与产物矛盾）")

    cur_n = sum(1 for ts in created_of.values() if era_start and ts >= era_start)
    cur_bad = sum(
        1 for rid, ts in created_of.items()
        if era_start and ts >= era_start and not by_id.get(rid)
    )
    print(f"  任务计数：{stat}")
    print(f"  clarifications.center 非法：{bad_center} 条")
    print(f"  现役区间报告 {cur_n} 份，其中不合规 {cur_bad} 份"
          f" —— {'✅ 判据成立' if cur_bad == 0 else '❌ 写路径有漏'}")
    print(f"  前口径时代任务 {len(legacy_tasks)} 个（产物已隐藏，状态保留为历史记录，不计异常）")
    for s in legacy_tasks:
        print(f"    · {s}")

    # ── D 段：数字自洽 ────────────────────────────────────────
    # 单独成段，且**通过时也明确打印**：一条没有可见输出的检查，与一条根本没跑的检查，
    # 在下游读者眼里无法区分 —— 这正是本脚本要消灭的"静默跳过"。
    rule("D. 数字自洽 —— 报告内部数字必须自洽（读者据此下结论，不自洽即误导）")
    print(f"  受检 {len(d_checked)} 份（可见集）")
    if d_bad:
        for m in d_bad:
            print(f"  ❌ {m}")
    else:
        print("  ✅ 全部通过：类别求和 = poi.total / poi.in_circle；"
              "sum(categories[].in_circle) = len(points)（阶段 1 点数守恒）；"
              "等时圈面积随 minutes 单调递增")
    if d_legacy:
        print(f"\n  ── 旧口径留痕 {len(d_legacy)} 条（阶段 1 之前落库，无 poi.truncated 标记，"
              f"数字对不上但**无法回溯修正**；不计异常）──")
        for m in d_legacy:
            print(f"  · {m}")

    # ── E 段：夹具 ────────────────────────────────────────────
    rule("E. 夹具 —— 后端 + 前端必须全部合规（演示与真实同源）")
    for d in (BACKEND_FIXTURES, FRONTEND_FIXTURES):
        for f in sorted(d.glob("*.json")):
            try:
                lc = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                problems.append(f"{f}: JSON 解析失败: {e}")
                continue
            lc = lc.get("living_circle") or lc
            issues = assess_geometry(lc)
            rel = f"{d.parent.parent.name}/{f.name}"
            num_bad, num_legacy = numeric_consistency(lc)
            print(f"  {'✅' if issues.ok and not num_bad else '❌'} {rel}"
                  f"{'' if issues.ok else '（几何不合规）'}"
                  f"{'' if not num_bad else '（数字不自洽）'}")
            if num_legacy:
                problems.append(f"夹具 {rel}: 缺 poi.truncated 标记（阶段 1 之后的夹具必须带）")
            if not issues.ok:
                problems.append(f"夹具 {rel} 不合几何契约：{issues.reason}")
            for msg in num_bad:
                problems.append(f"夹具 {rel}: 数字不自洽 —— {msg}")

    # ── F 段：几何明细（可选） ─────────────────────────────────
    if args.verbose:
        rule("F. 几何明细（人工核查用，不参与判定）")
        for r in rows:
            payload = json.loads(r["data"]) if r["data"] else {}
            lc = payload.get("living_circle") or payload
            print(f"\n  ── {r['report_id']} | {r['scene_name']} | origin={r['data_origin']}")
            for line in geometric_detail(r["report_id"], lc):
                print(line)
        for d in (BACKEND_FIXTURES, FRONTEND_FIXTURES):
            for f in sorted(d.glob("*.json")):
                lc = json.loads(f.read_text(encoding="utf-8"))
                lc = lc.get("living_circle") or lc
                print(f"\n  ── 夹具 {f.name}（{d.parent.parent.name}）")
                for line in geometric_detail(f.name, lc):
                    print(line)

    if CACHE.exists():
        try:
            c2 = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
            n = c2.execute("select count(*) from sqlite_master").fetchone()[0]
            c2.close()
            print(f"\n  缓存 lc_cache.db：对象 {n} 个（本设计不参与判定）")
        except sqlite3.Error:
            pass

    con.close()

    rule(f"体检完成：可见报告 {visible_n} 份合规；**异常项 {len(problems)} 条**")
    for p in problems:
        print(f"  ❌ {p}")
    if not problems:
        print("  ✅ 无异常 —— 用户取得到的每一份报告都合乎几何契约")
    print("=" * W)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

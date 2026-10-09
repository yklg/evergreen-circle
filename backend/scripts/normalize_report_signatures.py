"""规范化存量生活圈报告的章节署名（旅游人设 → 生活圈人设）。

为什么需要这一步：报告 JSON 把**派生值**（专家姓名）当原值烤进了库，而署名解析曾取错域
（`diagnosis_templates._expert()` 走 travel 名册）。代码已修，但读路径不重算 ⇒ 库里旧报告
仍写着「苏明哲·行程策略专家」，且同地点 30 天缓存会继续复用（`living_circle.py:274-285`
命中即复用既有 report_id，连新算的 team 都不落库）。

算法是**结构性直写**，不做姓名反查：章节 id → 席位 id 取自生产注册表
（`app/living_circle/seat_registry.SECTION_SEAT`，与装配代码同源），再要求"当前 author 必须等于
travel 名册里该席位 id 的姓名"才替换。
为什么不能按姓名反查：两本名册存在**交叉重名** —— travel L2-005 也叫「温叙白」，而生活圈
L3-001 才是「温叙白」。按姓名反查会把可达性章正确的 L2-005 席位改成生活圈 L3-001 的人。

用法（默认只读预检）：
    python scripts/normalize_report_signatures.py            # 预检：报数，不写
    python scripts/normalize_report_signatures.py --apply    # 备份后写入
    python scripts/normalize_report_signatures.py --apply --limit 3   # 试点
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DATA = BACKEND / "app" / "data"

# 章节 id → 席位 id 的唯一出口是生产注册表；这份脚本**不再自带一张表**
# （原先这里抄了一份、tests/test_expert_signature_derivation.py 又抄一份，
#  与装配代码三处并存 —— 改一处必漏两处）。
sys.path.insert(0, str(BACKEND))
from app.living_circle.seat_registry import SECTION_SEAT  # noqa: E402


def _roster(fname: str) -> dict[str, dict]:
    return {e["id"]: e for e in json.loads((DATA / fname).read_text(encoding="utf-8"))}


def normalize_report(report: dict, travel: dict, living: dict) -> tuple[dict, list[str], list[str]]:
    """返回（修好的报告, 改动清单, 未命中告警）。幂等：第二次跑改动清单为空。"""
    notes: list[str] = []
    warns: list[str] = []
    rid = report.get("id", "?")
    for sec in report.get("sections") or []:
        seat = SECTION_SEAT.get(sec.get("id", ""))
        if not seat:
            continue
        want_travel = travel[seat]["name"]
        want_living = living[seat]["name"]
        for claim in sec.get("claims") or []:
            cur = claim.get("author")
            if cur == want_living:
                continue                      # 已是对的（含幂等重跑）
            if cur == want_travel:
                claim["author"] = want_living
                notes.append(f"{rid}/{sec['id']}: {want_travel} → {want_living}")
            else:
                warns.append(f"{rid}/{sec['id']}: author={cur!r} 既不是 travel 也不是 living 的席位 {seat} 姓名，未动")
    # 顶层 claims 是 sections 的扁平副本（实测逐条相等）⇒ 用修好的 sections 重建，两处必然同源
    if report.get("claims") is not None:
        report["claims"] = [c for s in (report.get("sections") or []) for c in (s.get("claims") or [])]
    return report, notes, warns


def travel_only_names(travel: dict, living: dict) -> set[str]:
    return {e["name"] for e in travel.values()} - {e["name"] for e in living.values()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只预检）")
    ap.add_argument("--limit", type=int, default=0, help="只处理最新的 N 份（试点用；倒序取，旧报告多数已正确）")
    args = ap.parse_args()

    travel, living = _roster("experts.json"), _roster("experts_living_circle.json")
    only_travel = travel_only_names(travel, living)
    assert only_travel, "两本名册姓名完全相同，判据失去区分力"

    db_path = DATA / "verda.db"
    cache_path = BACKEND / "app" / "lc_cache.db"
    stamp = time.strftime("%Y%m%d-%H%M%S")

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT report_id, data FROM living_circle_reports ORDER BY created_at DESC").fetchall()
    if args.limit:
        rows = rows[: args.limit]

    all_notes: list[str] = []
    all_warns: list[str] = []
    pending: list[tuple[str, str]] = []
    for r in rows:
        report = json.loads(r["data"])
        fixed, notes, warns = normalize_report(report, travel, living)
        all_notes += notes
        all_warns += warns
        if notes:
            pending.append((r["report_id"], json.dumps(fixed, ensure_ascii=False)))

    # lc_cache.db：缓存载荷里同样烤着 author，漏改会让"归位"路径把旧人名写回来
    cache_pending: list[tuple[str, str]] = []
    cache_notes: list[str] = []
    if cache_path.exists():
        ccon = sqlite3.connect(str(cache_path))
        tabs = {t[0] for t in ccon.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "lc_cache" in tabs:
            cols = [c[1] for c in ccon.execute("PRAGMA table_info(lc_cache)")]
            key_col = "k" if "k" in cols else cols[0]
            blob_col = next((c for c in cols if c not in (key_col, "created_at", "expires_at")), cols[-1])
            for cr in ccon.execute(f"SELECT {key_col}, {blob_col} FROM lc_cache").fetchall():
                try:
                    payload = json.loads(cr[1])
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict) or "sections" not in payload:
                    continue
                fixed, notes, warns = normalize_report(payload, travel, living)
                cache_notes += notes
                all_warns += [f"cache:{w}" for w in warns]
                if notes:
                    cache_pending.append((cr[0], json.dumps(fixed, ensure_ascii=False)))
        ccon.close()

    print(f"扫描报告 {len(rows)} 份 ⇒ 待改署名 {len(all_notes)} 处（涉及 {len(pending)} 份报告）")
    print(f"lc_cache 载荷 ⇒ 待改署名 {len(cache_notes)} 处（涉及 {len(cache_pending)} 条缓存）")
    for n in (all_notes + cache_notes)[:12]:
        print("   ", n)
    if len(all_notes) + len(cache_notes) > 12:
        print(f"    …其余 {len(all_notes) + len(cache_notes) - 12} 处略")
    for w in all_warns[:10]:
        print("   ⚠", w)

    if not args.apply:
        print("\n预检模式（未写库）。加 --apply 执行。")
        return 0

    if not all_notes and not cache_notes:
        print("\n无待改项，跳过写入。")
        return 0

    bak = DATA / "_backup" / f"verda-{stamp}-pre-signature-normalize.db"
    bak.parent.mkdir(exist_ok=True)
    shutil.copy2(db_path, bak)
    print(f"\n已备份 → {bak.relative_to(BACKEND.parent)}")
    ckbak = None
    if cache_pending and cache_path.exists():
        ckbak = cache_path.with_name(f"lc_cache-{stamp}-pre-signature-normalize.db")
        shutil.copy2(cache_path, ckbak)
        print(f"已备份 → {ckbak.name}")

    con.execute("BEGIN")
    for rid, blob in pending:
        con.execute("UPDATE living_circle_reports SET data=? WHERE report_id=?", (blob, rid))
    con.commit()
    con.close()

    if cache_pending:
        ccon = sqlite3.connect(str(cache_path))
        cols = [c[1] for c in ccon.execute("PRAGMA table_info(lc_cache)")]
        key_col = "k" if "k" in cols else cols[0]
        blob_col = next((c for c in cols if c not in (key_col, "created_at", "expires_at")), cols[-1])
        for key, blob in cache_pending:
            ccon.execute(f"UPDATE lc_cache SET {blob_col}=? WHERE {key_col}=?", (blob, key))
        ccon.commit()
        ccon.close()

    # 后检：两库里 travel-only 姓名残留必须为 0
    # 后检分两处数：sections 是权威位置，顶层 claims 是它的扁平副本（两份都得干净）
    res_sec = res_top = 0
    vcon = sqlite3.connect(str(db_path))
    for (blob,) in vcon.execute("SELECT data FROM living_circle_reports").fetchall():
        rep = json.loads(blob)
        res_sec += sum(
            1 for s in (rep.get("sections") or []) for c in (s.get("claims") or []) if c.get("author") in only_travel
        )
        res_top += sum(1 for c in (rep.get("claims") or []) if c.get("author") in only_travel)
    vcon.close()
    residual = res_sec + res_top
    print(f"\n后检：travel-only 姓名残留 sections={res_sec} 顶层副本={res_top}（两处都期望 0）")
    print(f"回滚：cp {bak} {db_path}")
    if ckbak:
        print(f"      cp {ckbak} {cache_path}")
    return 0 if residual == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

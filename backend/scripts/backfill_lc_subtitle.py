#!/usr/bin/env python3
"""存量报告副标题回填 —— 只改 ``subtitle`` 一个派生字段。

## 为什么需要它

副标题的缺陷（「共 N 处设施」引 ``poi.total``、``address`` 为空时留悬空分隔符
「昆明市 · ｜综合 …」）修在代码里，**只对新生成的报告生效**。库里已存的报告仍带着旧文案，
而 ``subtitle`` 是用户可见的（报告 slides 封面、资料库列表、打印为 PDF），
所以"修了代码"不等于"用户看到的是对的"。

## 边界（刻意收窄，不做多余动作）

- 只回填**可见报告**（读路径谓词 ``assess_geometry().ok``，与 ``db.list_living_circle_reports`` 同一判据）。
  隐藏的历史产物是"前口径时代"的对照证据，**原文保留、不重写**。
- 只改 ``subtitle`` 键；``sections`` / ``evidence`` / 几何数据一律不碰。
- 公式来自 ``diagnosis_templates.lc_subtitle`` —— 与生成路径**同一实现**，不在这里重写一份。
- 回填前先用 ``VACUUM INTO`` 做一致性快照（自包含，含 WAL），并打印快照路径。

用法::

    cd backend
    .venv/bin/python scripts/backfill_lc_subtitle.py --dry-run   # 先看差异
    .venv/bin/python scripts/backfill_lc_subtitle.py            # 落库
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DB = BACKEND / "app" / "data" / "verda.db"
sys.path.insert(0, str(BACKEND))

from app.core.pipeline.diagnosis_templates import lc_subtitle  # noqa: E402
from app.living_circle.report_contract import assess_geometry  # noqa: E402


def snapshot(src: Path, dst: Path) -> None:
    """一致性快照：``VACUUM INTO`` 而非 copy —— WAL 里未 checkpoint 的提交也要带上。"""
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        if dst.exists():
            dst.unlink()
        con.execute("vacuum into ?", (str(dst),))
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印差异，不写库")
    ap.add_argument("--db", default=str(DB), help="目标数据库（默认 backend/app/data/verda.db）")
    args = ap.parse_args()
    db = Path(args.db)
    if not db.exists():
        print(f"❌ 数据库不存在：{db}")
        return 1

    if not args.dry_run:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = db.parent / "_backup" / f"{db.stem}-{stamp}-pre-subtitle-backfill.db"
        bak.parent.mkdir(parents=True, exist_ok=True)
        snapshot(db, bak)
        print(f"备份（一致性快照）：{bak}\n")

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select report_id, data_origin, data from living_circle_reports order by report_id"
    ).fetchall()

    changed, skipped_hidden, unchanged = 0, 0, 0
    print(f"{'report_id':<20} {'状态':<8} 副标题")
    print("-" * 100)
    for r in rows:
        payload = json.loads(r["data"]) if r["data"] else {}
        lc = payload.get("living_circle") or payload
        if not assess_geometry(lc).ok:
            skipped_hidden += 1
            continue
        old = payload.get("subtitle") or ""
        new = lc_subtitle(lc)
        if old == new:
            unchanged += 1
            print(f"{r['report_id']:<20} {'未变':<8} {new}")
            continue
        changed += 1
        print(f"{r['report_id']:<20} {'改':<8} {old}")
        print(f"{'':<20} {'  →':<8} {new}")
        if not args.dry_run:
            payload["subtitle"] = new
            con.execute(
                "update living_circle_reports set data=? where report_id=?",
                (json.dumps(payload, ensure_ascii=False), r["report_id"]),
            )

    if not args.dry_run and changed:
        con.commit()
    con.close()

    print("-" * 100)
    print(f"可见报告：改 {changed} / 未变 {unchanged}；跳过隐藏历史产物 {skipped_hidden}")
    if args.dry_run:
        print("（--dry-run：未写入）")
    elif not changed:
        print("无需回填。")
    else:
        print("✅ 回填完成（只改了 subtitle）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

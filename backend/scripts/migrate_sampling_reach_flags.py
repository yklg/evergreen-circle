"""一次性夹具迁移：sampling.points[].reachable → timed + in_reach（阶段 −1.1）。

判据**直接调用生产代码** `app.living_circle.isochrone._flag_of`，不另写一份 ——
否则就是本项目正在消灭的「同一语义多份实现」病症复发。

只改字段，不补造点位数据（项目约定）。用法：
    env -u ... .venv/bin/python scripts/migrate_sampling_reach_flags.py [--check]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent
FILES = [
    BACKEND / "app" / "living_circle" / "fixtures" / "kaili.json",
    BACKEND / "app" / "living_circle" / "fixtures" / "beijing-jinsong.json",
    PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle" / "kaili.json",
    PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle" / "beijing-jinsong.json",
]

sys.path.insert(0, str(BACKEND))
from app.living_circle.isochrone import REACH_FULL_MIN, _flag_of, reach_flags  # noqa: E402


def migrate_point(p: dict) -> dict:
    """按原键序重建：idx/lng/lat/minutes/timed/in_reach。"""
    timed, in_reach = _flag_of(p.get("minutes"))
    out: dict = {}
    for k, v in p.items():
        if k == "reachable":
            out["timed"] = timed
            out["in_reach"] = in_reach
        else:
            out[k] = v
    if "timed" not in out:  # 原文件缺 reachable 时补上
        out["timed"] = timed
        out["in_reach"] = in_reach
    return out


def main() -> int:
    check_only = "--check" in sys.argv
    print(f"REACH_FULL_MIN = {REACH_FULL_MIN:g}")
    for f in FILES:
        src = f.read_text(encoding="utf-8")
        doc = json.loads(src)
        lc = doc.get("living_circle", doc)
        pts = lc["sampling"]["points"]
        before_keys = sorted({k for p in pts for k in p})
        new_pts = [migrate_point(p) for p in pts]
        sampling = lc["sampling"]
        sampling["points"] = new_pts
        # 汇总数放进 sampling（与 IsochroneEngine 产出同构）。顺序：points/interpolation/
        # is_scattered/… 保持原样，仅追加两个新键，避免无谓 diff。
        flags = reach_flags(new_pts)
        sampling["timed_count"] = flags.timed_count
        sampling["in_reach_count"] = flags.in_reach_count
        out = json.dumps(doc, indent=2, ensure_ascii=False)

        n_timed = sum(1 for p in new_pts if p["timed"])
        n_in = sum(1 for p in new_pts if p["in_reach"])
        top_keys = sorted(lc.keys())
        stale = [k for k in top_keys if "reachable" in k]
        print(
            f"{f.relative_to(PROJECT)}: points={len(pts)} timed={n_timed} in_reach={n_in} "
            f"| keys {before_keys} -> {sorted({k for p in new_pts for k in p})}"
            + (f" | ⚠️ 顶层遗留 {stale}" if stale else "")
        )
        if not check_only and out != src:
            f.write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

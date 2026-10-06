# -*- coding: utf-8 -*-
"""一次性给生活圈夹具补形状口径键（笔二 S9）。

为什么要有这颗脚本、又为什么它**不进生产读路径**：
  前端第三屏要读 `isochrones[].shape`，而重新跑一次真体检才能产出这个键 —— 24 份 live
  存量件重跑 ≈264 次步行矩阵外呼（每份实测 11 次），`test_reach_calibration.py:444`
  把这条路写成"要花真钱的方向性错误"。环坐标本来就躺在夹具里，用**同一颗生产函数**
  离线回算即可，零外呼。

边界（三条，越界就不是补键而是造第二个真源）：
  1. 只调用 `geo_utils.shape_of`，不在这里抄一遍分箱/分相/圆度公式；
  2. 只写夹具文件，生产读路径绝不 import 本模块；
  3. 发键条件走 `isochrone.shape_emit_for`，与引擎同一颗判据 —— 这里不自己判 mode/档。

用法：python3 scripts/backfill_shape_keys.py [--check]
      --check  只报告"该发而未发/已发但不一致"，不落盘（CI 可用）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.living_circle.geo_utils import shape_of                      # noqa: E402
from app.living_circle.isochrone import shape_emit_for, shape_zone_keys  # noqa: E402

SHAPE_KEY = next(iter(shape_zone_keys()))
PAIRS = [  # (后端夹具, 前端镜像夹具) —— 镜像守卫对 `isochrones` 做深比较，两侧必须同步
    ("kaili.json",),
    ("kaili-ev2.json",),
    ("beijing-jinsong.json",),
]
BACK_DIR = BACKEND / "app" / "living_circle" / "fixtures"
FRONT_DIR = BACKEND.parent / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"


def with_shape(doc: dict) -> tuple[dict, int]:
    """按生产发键条件给该发的档挂 shape，返回（新文档，发键档数）。"""
    center = tuple(doc["scene"]["center"])
    mode = (doc.get("caliber") or {}).get("travel_mode", "walking")
    n = 0
    for zone in doc.get("isochrones") or []:
        minutes = float(zone.get("minutes") or -1)
        if not shape_emit_for(mode, minutes):
            zone.pop(SHAPE_KEY, None)
            continue
        ring = [tuple(p) for p in zone["geojson"]["coordinates"][0]]
        zone[SHAPE_KEY] = shape_of(ring, center, float(zone["area_km2"]))
        n += 1
    doc["isochrones"] = sorted(doc["isochrones"], key=lambda z: float(z["minutes"]))
    return doc, n


def main() -> int:
    check = "--check" in sys.argv
    changed = 0
    for (name,) in PAIRS:
        for folder in (BACK_DIR, FRONT_DIR):
            path = folder / name
            if not path.exists():
                print(f"  跳过（不存在）：{path}")
                continue
            raw = path.read_text(encoding="utf-8")
            doc = json.loads(raw)
            new, n = with_shape(doc)
            out = json.dumps(new, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else "")
            if out == raw:
                print(f"  已一致 {path.name:<22} 形状键 {n} 档")
                continue
            if check:
                print(f"  ❌ 待补 {path.name:<22} 形状键 {n} 档（--check 模式未落盘）")
                changed += 1
                continue
            path.write_text(out, encoding="utf-8")
            print(f"  ✅ 写入 {path.name:<22} 形状键 {n} 档")
            changed += 1
    print(("检查完成：有 %d 份待补" % changed) if check else ("完成：更新 %d 份夹具" % changed))
    return 1 if (check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())

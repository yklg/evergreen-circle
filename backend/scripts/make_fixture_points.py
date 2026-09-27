"""M5.1 · 快照 POI 点位增量采集（只附加 `poi.points`，不动其余权威字段）。

背景：真实百度 POI 检索结果逐次有少量浮动，M5 权威快照（评分 / 等时圈 / 盲区 /
POI 聚合统计）必须保持冻结，不能为了补点位而整包重跑（重跑会让评分/盲区漂移）。
本脚本只做「点位补充」：
  1. 读权威 fixture（data_origin='live'，来自 M5 实跑）；
  2. live 采集 8 类民生 POI（多关键词，复用 CATEGORY_DEFS / clean）；
  3. 用快照自带的 sampling 点构建 IDW 耗时场 → 回填每个点位的 minutes；
  4. **走 `assemble.build_poi_block` 这一唯一出口重构整个 `poi` 块**（阶段 1.1）——
     `points` 定型后，`categories[].in_circle/coverage` 由它派生、`total` 保持采集口径，
     并写入 `truncated`/`conservation`。不再手搓「只写 points」的旁路，
     否则本脚本产出的夹具会**绕过守恒契约**（旧版正是这样造出 104 ≠ 98 的样本）。
  5. 覆写前后端 fixture（镜像一致：`poi` 块两侧逐字段相同）。

用法：cd backend && .venv/bin/python -m scripts.make_fixture_points
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.living_circle.assemble import build_poi_block  # noqa: E402
from app.living_circle.baidu_client import BaiduClient  # noqa: E402
from app.living_circle.caliber import get_caliber  # noqa: E402
from app.living_circle.data_source import bind_evidence, load_poi  # noqa: E402
from app.living_circle.geo_utils import to_local_xy  # noqa: E402
from app.living_circle.isochrone import idw_for_points  # noqa: E402
from app.living_circle.poi import check_poi_conservation  # noqa: E402
from app.living_circle.scope import SpatialScope  # noqa: E402

SCENES = ["kaili", "beijing-jinsong"]

BACKEND_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"


async def augment_one(client: BaiduClient, lc: Dict[str, Any]) -> Dict[str, Any]:
    center = tuple(lc["scene"]["center"])
    # 空间口径绑定：可达区按 caliber.reach_full_min 从等时圈族里**按 minutes 选环**，
    # 采集半径 = scope.collect_radius_m（不再硬编码 2000，也不再用 15min 圈当「圈内」）。
    caliber = get_caliber((lc.get("caliber") or {}).get("travel_mode", "walking"))
    scope = SpatialScope.from_iso(caliber, center, float(lc["scene"].get("study_radius_m") or 2500), lc)
    scope.invariant()

    sample_pts = lc["sampling"]["points"]
    sample_xy = np.array([to_local_xy(center, sp["lng"], sp["lat"]) for sp in sample_pts])
    sample_minutes: List[Optional[float]] = [sp.get("minutes") for sp in sample_pts]

    collected = await load_poi(client, center, scope.collect_radius_m, scope=scope)
    per_category, _triads = collected.per_category, collected.triads
    # 重刷夹具必须一并绑定实测证据 —— 否则新夹具的 `caliber` 缺 evidence_* 字段，
    # 读侧契约与前端举证会拿到「旧口径形状的新数据」。
    scope = bind_evidence(scope, collected)

    times_by_cat: Dict[str, List[Optional[float]]] = {}
    for cat, items in per_category.items():
        if not items:
            times_by_cat[cat] = []
            continue
        query_xy = np.array([to_local_xy(center, it["lng"], it["lat"]) for it in items])
        times_by_cat[cat] = idw_for_points(sample_xy, sample_minutes, query_xy)

    lc["poi"] = build_poi_block(
        per_category, times_by_cat, scope, center, lc["poi"].get("categories") or []
    )
    issue = check_poi_conservation(lc["poi"])
    if issue is not None:
        raise SystemExit(f"❌ 夹具 `poi` 块不守恒（脚本绝不产出违规样本）：{issue}")
    return lc


async def main() -> None:
    ak = get_settings().baidu_server_ak
    if not ak:
        raise SystemExit("BAIDU_SERVER_AK 未配置（backend/.env）")
    client = BaiduClient(ak=ak)
    try:
        for key in SCENES:
            for d in (BACKEND_DIR, FRONTEND_DIR):
                p = d / f"{key}.json"
                if not p.exists():
                    raise SystemExit(f"缺少权威快照: {p}")
            lc = json.loads((BACKEND_DIR / f"{key}.json").read_text(encoding="utf-8"))
            assert lc.get("data_origin") == "live", f"{key} 非权威快照（data_origin={lc.get('data_origin')}）"
            before = {k: lc.get(k) for k in ("scores", "blindspots", "isochrones", "sampling")}
            lc = await augment_one(client, lc)
            after = {k: lc.get(k) for k in ("scores", "blindspots", "isochrones", "sampling")}
            assert before == after, f"{key}: 权威字段被改动！中止"
            text = json.dumps(lc, ensure_ascii=False, indent=2)
            for d in (BACKEND_DIR, FRONTEND_DIR):
                (d / f"{key}.json").write_text(text, encoding="utf-8")
            print(f"[{key}] ✅ 附加 poi.points {len(lc['poi']['points'])} 条（POI 聚合保持 {lc['poi']['total']}）")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
    print("FIXTURE POINTS DONE")

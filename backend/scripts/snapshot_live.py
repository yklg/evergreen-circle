"""M5 · 真实百度 AK 双社区实跑，生成真实 fixture 快照（覆写 F0 手绘 fixture）。

用法：cd backend && .venv/bin/python -m scripts.snapshot_live  （或 .venv/bin/python scripts/snapshot_live.py）

流程：以 data_mode='live' 驱动 living_circle_pipeline（真实批量算路 + POI 采集），
捕获完整 Report 的 living_circle 载荷，写入：
  - backend/app/living_circle/fixtures/{kaili,beijing-jinsong}.json
  - frontend/src/mocks/fixtures/livingCircle/{kaili,beijing-jinsong}.json
快照 data_origin='live' / interpolation='idw'（真实路网测时），可离线一键演示同一批真实结果。

串行执行：避免个人 AK QPS 叠加；pipeline 内置 request_guard 限流/退避。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 直接以脚本方式运行时可 import app 包（backend 目录入 path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import db  # noqa: E402
from app.core.pipeline.living_circle import create_living_circle_task, living_circle_pipeline  # noqa: E402

SCENES = [
    # key, scene_name, center [lng, lat] BD-09, city, address
    ("kaili", "凯里老街", [107.9758, 26.5734], "贵州·凯里", "凯里市西门街道老街片区（大阁山脚下）"),
    ("beijing-jinsong", "北京劲松", [116.4637, 39.8832], "北京·朝阳", "朝阳区劲松街道劲松小区（劲松地铁站西侧）"),
]

BACKEND_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"


def _iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _assert_snapshot_is_this_scene(name: str, center, lc: dict) -> None:
    """回读到的载荷必须**真的是本次这个场景的当前口径产物**，否则拒绝写夹具。

    为什么脚本要自己把关：它拿的是 pipeline `done` 里的 report_id 再回读 DB —— 中间任何
    「内容与 id 错配」都会把别的东西当成本次实跑结果**静默固化进夹具**（前后端两份镜像一起
    坏，测试还全绿，因为两侧写的是同一份错数据）。实测过一次：邻近缓存命中时 DB 仍指一份
    史前载荷（sampling 用 `reachable` 字段、collect_margin=0），夹具当场被写回旧 schema。

    三条判据各自拦一种复发：
      - 场景名：邻近命中服务的是邻居的内容（名字是邻居的）⇒ 说明本次根本没重算；
      - 中心点：同上，且防「键前缀扫 + 从值里读 center」那条邻近路径悄悄漂到别处；
      - 口径版本：夹具若缺 `scope_policy_version` ⇒ 等于把 D2 旧口径重新冻结成"事实源"。
    """
    from app.living_circle.geo_utils import haversine_m
    from app.living_circle.scope import SCOPE_POLICY_VERSION

    scene = lc.get("scene") or {}
    got_name = scene.get("name")
    got_center = scene.get("center") or []
    ver = (lc.get("caliber") or {}).get("scope_policy_version")
    problems = []
    if got_name != name:
        problems.append(f"场景名不符：回读到 {got_name!r}，本次请求 {name!r}（多半是邻近缓存命中，本次没真跑）")
    if len(got_center) == 2 and center and haversine_m(tuple(center), tuple(got_center)) > 1.0:
        problems.append(f"中心点不符：回读 {got_center} 距请求 {center} 超过 1m")
    if ver != SCOPE_POLICY_VERSION:
        problems.append(f"口径版本不符：回读 {ver!r} ≠ 当前 {SCOPE_POLICY_VERSION!r}（旧口径载荷不得写进夹具）")
    if problems:
        raise RuntimeError(
            f"{name}: 快照校验失败，已拒绝写夹具（先清 app/lc_cache.db 里同中心的旧/邻近缓存行再重跑）：\n  - "
            + "\n  - ".join(problems)
        )
    print(f"[{name}] 快照校验通过：served_from={lc.get('served_from') or 'fresh'} 口径 {ver}")


async def _run_one(key: str, name: str, center, city: str, address: str) -> dict:
    task_id = create_living_circle_task({
        "scene_name": name,
        "city": city,
        "address": address,
        "center": center,
        "study_radius_m": 2500.0,
        "mode": "standard",
        "data_mode": "live",
    })
    print(f"[{name}] task={task_id} 开始真实实跑（批量算路 + POI 采集，串行限流）…")
    report_id = None
    async for ev in living_circle_pipeline(task_id):
        if ev["type"] == "progress":
            print(f"  [{name}] {ev['data'].get('stage')} {ev['data'].get('percent')}%")
        if ev["type"] in ("report_ready", "done"):
            report_id = ev["data"].get("report_id") or ev["data"].get("reportId")
    if not report_id:
        raise RuntimeError(f"{name}: 未产生报告（检查 AK / 网络）")
    rep = db.get_living_circle_report(report_id)
    lc = rep["living_circle"]
    _assert_snapshot_is_this_scene(name, center, lc)
    # 统一快照时间戳（可复现性：快照固定 generated_at，避免每次 diff 全文件漂移）
    lc["generated_at"] = "2026-09-19T12:00:00.000Z"
    scene = lc["scene"]
    print(f"[{name}] ✅ 报告 {report_id}："
          f"15min 等时圈 {(next((z['area_km2'] for z in lc['isochrones'] if z['minutes']==15), None))} km²，"
          f"POI {lc['poi']['total']}（圈内 {lc['poi']['in_circle']}），盲区 {len(lc['blindspots'])}，"
          f"评分 {lc['scores']['total']}；{lc['data_origin']}/{lc['sampling']['interpolation']}")
    return lc


async def main() -> None:
    results = {}
    for key, name, center, city, address in SCENES:
        lc = await _run_one(key, name, center, city, address)
        results[key] = lc
        for d in (BACKEND_DIR, FRONTEND_DIR):
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.json").write_text(json.dumps(lc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{name}] 快照已写入 backend + frontend fixtures")

    print("\n===== 摘要（供文档引用）=====")
    for key, lc in results.items():
        z = {zz["minutes"]: round(zz["area_km2"], 2) for zz in lc["isochrones"]}
        print(f"{key}: origin={lc['data_origin']} interp={lc['sampling']['interpolation']} "
              f"areas={z} poi={lc['poi']['total']}/{lc['poi']['in_circle']} "
              f"bs={len(lc['blindspots'])} score={lc['scores']['total']}")


if __name__ == "__main__":
    asyncio.run(main())
    print("SNAPSHOT DONE")
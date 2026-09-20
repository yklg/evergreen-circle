"""阶段 4 · 存量 live 报告重算（**真数据验收**，不覆写夹具）。

## 为什么要重算而不是只标记 stale

标记 stale 只能说明「旧产物不可信」；要证明「新算法在**同一条真实输入**上不再犯同样的错」，
必须拿旧事故的原始入参重跑一遍。本脚本只跑那两个**尚未被新算法覆盖**的场景：

============================  ==========================================  ==================================
场景                           旧产物（已隐藏）                              本脚本要验证的验收门
============================  ==========================================  ==================================
昆明坐标 + 「北京劲松」名称       `lc-e307a459` / `lc-d3cfa371`（151 点 88%   阶段 2：必须产出 `name_center_mismatch`
                              圈外，城市却是「北京·朝阳」）                 告警 + 报告带同源标记 + 城市来自逆地理
迤栖村                          `lc-c796c62d` / `lc-275690af`（iso=[]、        阶段 3：无路网 ⇒ 任务必须 `failed`，
                              poi=[]、0 分、1 处 29km² 盲区）               **不得**再签成 done

凯里老街 / 北京劲松（正常坐标）已在阶段 1b 修完后由 `scripts/snapshot_live.py` 重算并落库
（`lc-2220ad8e` / `lc-8748f92c`），本脚本不重复调用，避免产生重复报告。

用法：``cd backend && .venv/bin/python -m scripts.recompute_legacy_live``
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import db  # noqa: E402
from app.core.pipeline.living_circle import (  # noqa: E402
    create_living_circle_task,
    living_circle_pipeline,
)
from app.living_circle.report_contract import staleness_reason  # noqa: E402

SCENES = [
    {
        "key": "kumming-mismatch",
        "scene_name": "北京劲松",
        "center": [102.7596, 25.0295],   # 旧事故里那个「昆明」坐标
        "city": "",                      # 留空：必须由后端逆地理补，不得沿用旧报告的「北京·朝阳」
        "address": "",
        "why": "旧产物 lc-d3cfa371 名称=北京劲松 / 坐标=昆明 / 城市=北京·朝阳（三字段三来源）",
        "expect": "mismatch",
    },
    {
        "key": "yiqi",
        "scene_name": "云南省玉溪市易门县六街镇迤栖村",
        "center": [102.16211, 24.669598],
        "city": "",
        "address": "",
        "why": "旧产物 lc-c796c62d isochrones=[] / poi=[] / 0 分，却 status=done",
        "expect": "failed_or_valid",
    },
]


async def _run(scene: dict) -> dict:
    task_id = create_living_circle_task({
        "scene_name": scene["scene_name"],
        "city": scene["city"],
        "address": scene["address"],
        "center": scene["center"],
        "study_radius_m": 2500.0,
        "mode": "standard",
        "data_mode": "live",
    })
    print(f"\n{'=' * 92}\n[{scene['key']}] task={task_id}\n  输入：name={scene['scene_name']!r} center={scene['center']}")
    print(f"  旧事故：{scene['why']}")

    warns, errors, report_id = [], [], None
    async for ev in living_circle_pipeline(task_id):
        t = ev["type"]
        if t == "progress":
            print(f"    · {ev['data'].get('stage'):>8} {ev['data'].get('percent')}%")
        elif t == "warn":
            warns.append(ev["data"])
            print(f"    ⚠ warn: {ev['data']}")
        elif t == "error":
            errors.append(ev["data"])
            print(f"    ✖ error: {ev['data']}")
        elif t == "message":
            txt = (ev["data"].get("text") or "")
            if "质检未通过" in txt:
                print(f"    ✖ {txt}")
        elif t in ("report_ready", "done"):
            report_id = ev["data"].get("report_id") or report_id
            print(f"    · {t}: report_id={ev['data'].get('report_id')} status={ev['data'].get('status')}")

    task = db.get_task_full(task_id)
    out = {
        "key": scene["key"],
        "task_id": task_id,
        "status": task["status"],
        "error": task["error"],
        "report_id": report_id,
        "warns": warns,
        "errors": errors,
    }
    print(f"  → 终态：status={task['status']!r} error={task['error']!r} report={report_id}")

    if report_id:
        lc = db.get_living_circle_report(report_id)["living_circle"]
        scene_meta = lc.get("scene") or {}
        print(f"  报告：{report_id}")
        print(f"    scene.name={scene_meta.get('name')!r} center={scene_meta.get('center')} city={scene_meta.get('city')!r}")
        print(f"    name_source={scene_meta.get('name_source')!r} mismatch={scene_meta.get('name_center_mismatch')!r} "
              f"dist={scene_meta.get('name_center_distance_m')!r} ref={scene_meta.get('name_ref_center')!r}")
        print(f"    iso={len(lc.get('isochrones') or [])} poi.points={len((lc.get('poi') or {}).get('points') or [])} "
              f"poi.total={((lc.get('poi') or {}).get('total'))} in_circle={((lc.get('poi') or {}).get('in_circle'))} "
              f"blindspots={len(lc.get('blindspots') or [])} score={(lc.get('scores') or {}).get('total')}")
        print(f"    caliber={json.dumps(lc.get('caliber') or {}, ensure_ascii=False)}")
        print(f"    几何契约：{staleness_reason(lc) or '✅ 合规'}")
        out["scene"] = scene_meta
        out["contract"] = staleness_reason(lc) or "ok"
    return out


async def main() -> int:
    results = [await _run(s) for s in SCENES]

    print(f"\n{'=' * 92}\n阶段 4 重算 · 验收判定\n{'=' * 92}")
    bad = 0
    for r in results:
        if r["key"] == "kumming-mismatch":
            hit = any(w.get("code") == "name_center_mismatch" for w in r["warns"])
            marked = bool((r.get("scene") or {}).get("name_center_mismatch"))
            ok = hit and marked
            print(f"  阶段 2（名称坐标同源）: warn={'✅' if hit else '❌'} "
                  f"报告标记={'✅' if marked else '❌'} → {'通过' if ok else '不通过'}")
            bad += 0 if ok else 1
        elif r["key"] == "yiqi":
            if r["status"] == "failed":
                print(f"  阶段 3（静默空壳封堵）: 任务 failed ✅（error={r['error']!r}）→ 通过")
            elif r["status"] == "done" and r.get("contract") == "ok":
                print("  阶段 3（静默空壳封堵）: 该场景本次取到了真实数据、且报告合规 ✅ "
                      "→ 通过（守卫未被触发，但产物本身合格）")
            else:
                print(f"  阶段 3（静默空壳封堵）: status={r['status']} 契约={r.get('contract')} ❌ → 不通过")
                bad += 1

    print(f"\n  结论：{'✅ 全部通过' if bad == 0 else f'❌ {bad} 项不通过'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

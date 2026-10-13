# -*- coding: utf-8 -*-
"""区域交通时段暴露度（第五维）· 取数与聚合。

**唯一生产者**：`fetch_traffic_exposure`。它只做两件事 —— 一次 `/traffic/v1/around` 调用
（经 `BaiduClient._get` ⇒ 自动过 CallGuard 的并发/限速/退避/日额度），把响应聚合成
`sampling.traffic` 这一块。

三条实测边界（出处 `capability_manifest.json` 的 `traffic_service`，2026-10-13）：
  · 坐标参数一律 `lat,lng`；反序直接回「bounds参数错误」。
  · **走 around 不走 bound**：bound 端点有面积上限（1.81km 的框报「bounds范围过大」），
    而 around 的 500/1000/1500/2000m 连续四个半径全部可用。
  · 返回**不含几何**，只有路段名/方向/起止点 ⇒ 做不了「环内过滤」。
    所以这一维的尺是 **中心点 + R 米的圆域**，R 取该档可达区的外接半径
    （`scope.reach_circumradius_m`）。**圆域 ≠ 可达区**（环不规则）：屏上与正文必须
    写明是哪把尺（§7.1 两把尺纪律的第三例），措辞出口见 `exposureSentence`。

口径（本模块即住所，`caliber.TRAFFIC_CALIBER_VERSION = "tv-1"` 指的就是这一套）：
  · `peak_window`：典型高峰窗口，来自 `caliber.traffic_peak_window`（只步行档有值）。
  · 档位→倍数表：`MULTIPLIER_TABLE`（声明值，**未标定**——`CALIBRATED = False`）。
    标定路径 = 一次双时刻实测（同点位早高峰/平峰各跑一遍 routematrix），与 `detour_k`
    的反标定同型；标定前只许写"按档位映射"，不许写"实测行程时间"。
  · `exposure_index = Σ tier_share[t] × mult[t]`，按 `congestion_distance` 加权。
  · 第五维分 = `100 × (range_max − index) / (range_max − range_min)`，clamp 到 [0,100]。

⚠️ 这里**不许**出现路段名/方向/起止点的渲染 —— 项目方 2026-10-13 拍板「只用聚合，不点名路段」
（口径风险：路段级清单离「取底层路网」更近；返回里的 `road_traffic[].road_name` 与
`section_desc` 一律**不进载荷**）。
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict

# 档位→倍数表：**声明值，未标定**（`CALIBRATED = False`）。
# 键 = 百度 `evaluation.status` / `congestion_sections[].status` 的取值（1 最畅、4 最堵）；
# 名称用中性词，避免与判盲那把尺的五态（reachable/blocked/absent/unknown/missing）混用。
MULTIPLIER_TABLE: Dict[int, float] = {1: 1.00, 2: 1.15, 3: 1.60, 4: 2.40}
TIER_NAMES: Dict[int, str] = {1: "畅通", 2: "缓行", 3: "拥堵", 4: "严重拥堵"}
MULTIPLIER_TABLE_VERSION = "tm-1"
CALIBRATED = False  # 标定完成后改 True 并把实测依据写进 `basis`
BASIS = (
    "倍数表为**声明值**（2026-10-13 出厂），未做双时刻实测标定：标定需同点位早高峰/平峰各跑一次"
    "routematrix。口径表如实标注这一点，屏上措辞只许说『按档位映射』，不许说『实测行程时间』。"
)

# 端点与超时（计划步骤 3 的写死值）
TRAFFIC_PATH = "/traffic/v1/around"
TIMEOUT_S = 8.0
RETRIES = 1  # 5xx/超时最多补一次；4xx 与权限错一律不重试（CallGuard 的退避只认临时故障）


def exposure_range() -> tuple[float, float]:
    """倍数表的取值上下界 —— 第五维打分用的那根线性映射的两端（唯一出处）。"""
    vals = sorted(MULTIPLIER_TABLE.values())
    return vals[0], vals[-1]


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    """把一次 around 响应聚合成 exposure 读数。**不保留任何路段名/方向**（拍板纪律）。

    聚合口径：以路段为单位，每条被点名的拥堵段按其 `congestion_distance`（米）与
    `status`（档位）投票。没有 `congestion_sections` 的路段不计票（它没有档位读数）。
    """
    ev = body.get("evaluation") or {}
    ev_status = ev.get("status")
    shares: Dict[str, float] = {TIER_NAMES[k]: 0.0 for k in TIER_NAMES}
    dist_by_tier: Dict[int, float] = {k: 0.0 for k in TIER_NAMES}
    total_dist = 0.0
    sections = 0
    for road in body.get("road_traffic") or []:
        for sec in road.get("congestion_sections") or []:
            st, dist = sec.get("status"), sec.get("congestion_distance")
            if st not in MULTIPLIER_TABLE:
                continue  # 未知档位：丢弃但**计数**（零容忍由契约判据负责，见 report_contract）
            if not _finite(dist) or dist <= 0:
                continue
            dist_by_tier[int(st)] += float(dist)
            total_dist += float(dist)
            sections += 1
    unknown_codes = sorted({sec.get("status") for road in body.get("road_traffic") or []
                            for sec in road.get("congestion_sections") or []
                            if sec.get("status") not in MULTIPLIER_TABLE},
                           key=lambda x: str(x))
    unknown = sum(1 for road in body.get("road_traffic") or []
                  for sec in road.get("congestion_sections") or []
                  if sec.get("status") not in MULTIPLIER_TABLE)
    if total_dist > 0:
        for k, v in dist_by_tier.items():
            shares[TIER_NAMES[k]] = round(v / total_dist, 6)
    index = sum(shares[TIER_NAMES[k]] * MULTIPLIER_TABLE[k] for k in MULTIPLIER_TABLE)
    lo, hi = exposure_range()
    score = 100.0 * (hi - index) / (hi - lo) if hi > lo else 0.0
    return {
        "region": "circle",          # 尺的语义显式进载荷：圆域，不是可达区
        "evaluation_status": ev_status if _finite(ev_status) else None,
        "tier_share": shares,
        "congested_distance_m": round(total_dist, 1),
        "sections_count": sections,
        "unknown_tier_sections": unknown,
        # 看不懂的档位值**原样列出**（不是只计数）：契约拒签时要能点名"百度给了什么"，
        # 否则拿到违规消息的人只知道"有个档位不认识"，不知道去更新哪张表。
        "unknown_tier_codes": unknown_codes,
        "exposure_index": round(index, 6),
        "exposure_score": round(max(0.0, min(100.0, score)), 3),
    }


async def fetch_traffic_exposure(client: Any, *, center: tuple, radius_m: float,
                                 caliber: Any) -> Dict[str, Any]:
    """一次圆域路况查询 → `sampling.traffic` 块。**失败一律降级为 `coverage="absent"`**。

    不抛异常：这是一次"能拿就拿"的取数 —— 拿不到只该影响第五维与那一章，不该阻断体检
    （计划步骤 3 的降级口径）。返回的块里 `coverage` 是唯一的状态位，读数键在 absent 时**整块不发**。
    """
    block: Dict[str, Any] = {
        "coverage": "absent",
        "region": "circle",
        "peak_window": getattr(caliber, "traffic_peak_window", None),
        "radius_m": round(float(radius_m), 1),
        "multiplier_table": {TIER_NAMES[k]: MULTIPLIER_TABLE[k] for k in sorted(MULTIPLIER_TABLE)},
        "multiplier_table_version": MULTIPLIER_TABLE_VERSION,
        "calibrated": CALIBRATED,
        "basis": BASIS,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # 半径上界保护：实测只验到 2000m；超过就按 2000 截断并把实际请求值写进载荷（可复算）。
    req_radius = min(float(radius_m), 2000.0)
    params = {"center": f"{center[0]:.6f},{center[1]:.6f}", "radius": f"{int(round(req_radius))}"}
    try:
        body = await client._get(TRAFFIC_PATH, params)
    except Exception as exc:  # noqa: BLE001 —— 任何取数异常都归 absent，不让它冒到编排层
        block["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return block
    if not isinstance(body, dict) or body.get("status") != 0:
        block["error"] = str((body or {}).get("message", "no-status"))[:200]
        return block
    parsed = _parse(body)
    if parsed["sections_count"] == 0 and parsed["evaluation_status"] is None:
        # 响应成功但没有任何可聚合的量：这不是"0 暴露"，是"没量到" ⇒ 保持 absent
        block["error"] = "响应里没有可聚合的档位读数"
        return block
    block.update(parsed)
    block["coverage"] = "ok"
    block.pop("error", None)
    return block

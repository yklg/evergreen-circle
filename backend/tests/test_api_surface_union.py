"""T-11 · M1 树合并的 API 表面并集保护网（融合 W1 波次）。

守护什么：三跳合并的 M1 是「零行为变更树合并」，59 个冲突文件选边时
main.py 若误取他侧版本，会**静默丢掉**当前侧独有的 7 个 /api/life-circle/*
端点或任一既有核心端点。本测试把「既有路由全集」钉死：M1 前后必须一致。

注意：research-types 等改造侧新端点**不属于** M1 全集（flip/M3 才挂），
本测试在 flip 后随外壳 v2 扩展，不在此提前断言。

长期保留：M3 后演化为两域端点注册表契约测试。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# 当前侧（常青圈 main）已发布的路由全集：(方法, 路径)。
# Life-circle 7 个为 skip 独有，是本测试最核心的防丢失对象。
REQUIRED_ROUTES: set[tuple[str, str]] = {
    ("GET", "/health"),
    # 任务生命周期
    ("POST", "/api/tasks"),
    ("POST", "/api/tasks/{task_id}/clarify"),
    ("GET", "/api/tasks/{task_id}/clarify/stream"),
    ("GET", "/api/tasks/{task_id}/stream"),
    ("GET", "/api/tasks/{task_id}/status"),
    ("GET", "/api/tasks/running"),
    ("POST", "/api/tasks/{task_id}/cancel"),
    # 报告 / 证据 / 反馈
    ("GET", "/api/reports"),
    ("GET", "/api/reports/{report_id}"),
    ("DELETE", "/api/reports/{report_id}"),
    ("POST", "/api/reports/{report_id}/brief"),
    ("POST", "/api/reports/{report_id}/refine"),
    ("POST", "/api/reports/{report_id}/refine-evidence"),
    ("POST", "/api/reports/{report_id}/feedback"),
    ("GET", "/api/reports/{report_id}/trace"),
    ("GET", "/api/tasks/{task_id}/trace"),
    ("GET", "/api/evidences"),
    # 专家 / 模型 / 设置
    ("GET", "/api/experts"),
    ("GET", "/api/experts/workload"),
    ("GET", "/api/experts/integrity"),
    ("GET", "/api/experts/{eid}"),
    ("GET", "/api/llm/ping"),
    ("GET", "/api/llm/models"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/prefs"),
    ("PUT", "/api/prefs"),
    # 仪表盘 / 订阅 / 搜索
    ("GET", "/api/dashboard"),
    # 报告中心双 tab 改造：情报中心整屏聚合独立成端点（dashboard 已瘦到两键，
    # 两者不再共用一份重载荷）。注册进本清单，防后续树合并选边时静默丢掉。
    ("GET", "/api/intel"),
    ("GET", "/api/subscriptions"),
    ("POST", "/api/subscriptions"),
    ("DELETE", "/api/subscriptions/{sub_id}"),
    ("GET", "/api/search"),
    # ── life-circle 域 7 端点（skip 独有，选边事故最高发区；以 main.py 实际路由为准）──
    # 第 7 条是报告中心「唯一归档 + 删除」补的 DELETE：删除能力要收进归档面，
    # 就不能让生活圈侧只有读端点而没有删端点（调研报告侧早有 DELETE /api/reports/{id}）。
    ("GET", "/api/life-circle/regions"),
    ("GET", "/api/life-circle/map-config"),
    ("GET", "/api/life-circle"),
    ("GET", "/api/life-circle/compare"),
    ("GET", "/api/life-circle/{report_id}"),
    ("GET", "/api/life-circle/{report_id}/share"),
    ("DELETE", "/api/life-circle/{report_id}"),
}


def _actual_routes() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for m in methods:
            if m in {"HEAD", "OPTIONS"}:
                continue
            out.add((m, path))
    return out


def test_required_route_surface_all_present():
    """M1 选边后既有路由一个不丢（含 life-circle 全集）。"""
    actual = _actual_routes()
    missing = sorted(REQUIRED_ROUTES - actual)
    assert not missing, f"M1 合并丢失既有路由（选边事故）：{missing}"


def test_life_circle_surface_complete():
    """life-circle 端点单独再钉一道，避免从并集增删时被连带放松。"""
    actual = _actual_routes()
    lc = {r for r in REQUIRED_ROUTES if r[1].startswith("/api/life-circle")}
    assert len(lc) == 7, f"防护清单本身被改动：期望 7 个 LC 路由，实际 {len(lc)}"
    missing = sorted(lc - actual)
    assert not missing, f"life-circle 端点丢失：{missing}"


def test_duplicate_route_method_conflicts():
    """同 (方法,路径) 被重复注册时 FastAPI 后者静默覆盖——并集合并期专门抓这类事故。"""
    seen: dict[tuple[str, str], int] = {}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for m in methods:
            if m in {"HEAD", "OPTIONS"}:
                continue
            seen[(m, path)] = seen.get((m, path), 0) + 1
    dups = {f"{m} {p}": n for (m, p), n in seen.items() if n > 1}
    assert not dups, f"存在重复注册路由（合并并集冲突）：{dups}"

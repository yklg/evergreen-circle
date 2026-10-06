"""4a 探针的离线守卫：请求形状、选点确定性、以及"不许误烧额度"。

为什么要有这个文件：`scripts/probe_baidu.py` 的 `timeaxis`/`rowfields` 两组**花真实配额**。
第一次真实运行就因为我把它发送的 `destinations` 写成 `lng,lat`（正确的是 `lat,lng`），
13 次调用全部 `status=2 destinations is invalid`、零行数据 —— 钱花了、数没拿到，
而且探针"跑完了"这件事本身不构成任何证据。这类事故只能由**不发请求的形状断言**挡住：
把 `fetch` 换成记账假件，URL 就是被测对象。

三条判据各自的防漂移目标：
1. 坐标顺序 —— 生产 `measure_matrix` 的形参是 `(lng, lat)`、在内部才倒过来，
   探针少倒一次就全批作废；断言按**发出的字面串**判，不按注释判。
2. 边界选点的确定性与分层 —— 20 个点必须是"in_reach 各 10、方位铺开、两次调用逐位一致"。
   点数或分档塌了，误差率就是在偏样本上算的（而回执里照样写着 n=20）。
3. 默认组不含花额度的组 —— 这条一旦被改，任何人 `python scripts/probe_baidu.py`
   都会静默烧掉一次完整运行的额度。
"""
import importlib.util
import math
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_baidu.py"


def _load_probe():
    """按路径加载探针脚本（它是脚本不是包；`main()` 只在 `__main__` 下跑，import 无副作用）。"""
    spec = importlib.util.spec_from_file_location("probe_baidu_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recording_fetch(captured: list):
    """假 `fetch`：记下 URL、回一份最小可用响应（一 origin 一行）。"""
    def fetch(url: str, timeout: float = 12.0) -> dict:
        captured.append(url)
        return {"ms": 1.0, "data": {"status": 0, "message": "ok",
                                      "result": [{"duration": {"value": 600},
                                                  "distance": {"value": 800}}]}}
    return fetch


def test_matrix_request_sends_both_origins_and_destinations_as_lat_lng(monkeypatch):
    """`lat,lng` 是这一族接口的字面顺序，origins 与 destinations **必须同序**。

    判据看的是 URL 里那两个参数的**字面串**：形参名、注释、"看起来对"都不算数。
    """
    pb = _load_probe()
    captured: list = []
    monkeypatch.setattr(pb, "fetch", _recording_fetch(captured))

    # 中心点 BD-09：lng=107.9758, lat=26.5734（与出厂实跑快照同一点）
    out = pb._matrix_once("TESTAK", "walking", [(107.9758, 26.5734)], (26.5734, 107.9758))
    assert out["status"] == 0
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0]).query)
    assert qs["origins"][0] == "26.5734,107.9758", qs
    assert qs["destinations"][0] == "26.5734,107.9758", qs
    assert "TESTAK" in captured[0] and "output=json" in captured[0]


def test_matrix_path_is_read_from_the_same_table_as_production(monkeypatch):
    """探针打的 URL 必须与生产 `caliber.api.matrix_path` 同源 —— 否则能力结论不适用。

    "百度有没有时刻这根轴"是对**我们在用的那条端点**的回答；探针若另打一条
    （比如 directionlite 或 v1 矩阵），结论对生产链一句都不成立。
    """
    from app.living_circle.caliber import get_caliber


    pb = _load_probe()
    captured: list = []
    monkeypatch.setattr(pb, "fetch", _recording_fetch(captured))
    for mode in ("walking", "riding", "driving"):
        cal = get_caliber(mode)
        assert cal.api, f"{mode} 未配置 API 能力"
        assert pb.MATRIX_PATHS[mode] == cal.api.matrix_path, (mode, pb.MATRIX_PATHS[mode])


def test_boundary_sample_is_stratified_deterministic_and_refuses_thin_bands():
    """20 点必须"in_reach 各 10、方位铺开、逐位可复跑"，且带内点数不足时**返回空**而非凑数。

    凑数是这里最坏的失败形态：回执会照样写 n=20，而误差率其实是在 8 个同侧点上算的。
    """
    pb = _load_probe()
    rng = 45.0

    def pt(i, lng, lat, minutes, in_reach):
        return {"idx": i, "lng": lng, "lat": lat, "minutes": minutes,
                "timed": True, "in_reach": in_reach}

    center = [107.9758, 26.5734]
    pts = []
    i = 0
    for flag in (True, False):
        for b in range(8):                      # 8 个 45° 方位 × 4 个距离档
            for k in range(4):
                ang = math.radians(b * rng + 10)
                dist = 0.004 + 0.001 * k
                pts.append(pt(i, center[0] + dist * math.cos(ang),
                              center[1] + dist * math.sin(ang),
                              (17.0 + k) if flag else (21.0 + k), flag))
                i += 1
    lc = {"caliber": {"reach_full_min": 20.0}, "scene": {"center": center},
          "sampling": {"points": pts}}

    picked, got_center = pb._boundary_points(lc, want=20)
    assert got_center == center
    assert len(picked) == 20, len(picked)
    assert sum(1 for p in picked if p["in_reach"]) == 10
    assert sum(1 for p in picked if not p["in_reach"]) == 10
    angles = {int(math.degrees(math.atan2(p["lat"] - center[1], p["lng"] - center[0])) // rng)
              for p in picked}
    assert len(angles) >= 4, f"样本挤在 {len(angles)} 个方位桶里：{sorted(angles)}"
    assert all(16.0 <= p["minutes"] <= 24.0 for p in picked)
    # 确定性：同输入两次调用逐位一致（无随机数 ⇒ 误差率可复跑）
    again, _ = pb._boundary_points(lc, want=20)
    assert [p["idx"] for p in again] == [p["idx"] for p in picked]

    # 带内点数不足 ⇒ 明确拒绝，而不是返回可用点数
    thin = {"caliber": {"reach_full_min": 20.0}, "scene": {"center": center},
            "sampling": {"points": pts[:12]}}
    got, _ = pb._boundary_points(thin, want=20)
    assert got == [], f"点数不足却返回了 {len(got)} 个 —— 探针会拿偏样本自称 n=20"


def test_quota_spending_groups_are_not_in_the_default_run(monkeypatch):
    """默认组里**不许**出现 `timeaxis` / `rowfields`：它们花真实额度，必须显式点名。

    断的是字面默认值，不是文档承诺：一旦有人把新组并进默认列表，任何一次
    `python scripts/probe_baidu.py` 都会静默烧掉一整轮（本探针首跑 = 14 次调用）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if 'groups = sys.argv[1:]' in l)
    assert "timeaxis" not in line and "rowfields" not in line, line
    for name in ("timeaxis", "rowfields"):
        assert f'if "{name}" in groups' in src, f"{name} 组没挂进 CLI"


def test_negative_controls_are_declared_not_improvised():
    """阴性对照键与候选参数表必须**存在于数据里**，否则所有"没变化"都读不出含义。

    百度对未知键静默忽略（实测 `probe_deadbeef_4a=1` ⇒ status=0、零变化），所以
    "换了参数值没变"本身不是证据；必须有那枚垃圾参数对照在场，才能把阴性结论打折成
    "未观察到可观测差异"。候选参数同理：空表 ⇒ 能力核实一句"没差异"是空转。
    """
    pb = _load_probe()
    assert pb.DEADBEEF, "阴性对照键丢了"
    assert len(pb.CANDIDATE_PARAMS) >= 3, sorted(pb.CANDIDATE_PARAMS)
    assert all(isinstance(v, dict) and len(v) == 1 for v in pb.CANDIDATE_PARAMS.values())

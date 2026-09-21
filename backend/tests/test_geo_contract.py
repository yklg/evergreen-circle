"""阶段 0a · 跨层坐标契约守卫（先红后绿）。

本域 ``LngLat = Tuple[float, float]`` 是**裸元组**：BD-09 经纬度、百度墨卡托米、
局部平面米 **三者类型同形**，typing / TypeScript 都拦不住 —— 喂错坐标系是「类型正确」的。

历史事故（已 CDP 复现）：BMapGL ``dragend`` 的 ``e.point`` 是**墨卡托平面坐标（米）**
``(11440230.81, 2860409.52)``，被当作经纬度穿过 API → 落库 → 报告 ``scene.center``
→ 前端再次渲染坏地图。**一次写库，之后每次打开都必现**（自我强化闭环）。

⇒ 契约不能靠类型，只能靠**值域**。本用例把「合法」的判据从
「长度 2 + isFinite」（旧防线形状，**逐条放行墨卡托米**）收紧到语义级。

跑红纪律：在未给 ``CreateTaskBody.center`` 挂 ``field_validator`` 的代码上，
``test_task_body_rejects_mercator`` / ``test_task_body_rejects_short_list``
与两条 HTTP 用例必须失败 —— 那是「防线真的存在」的证据。
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.living_circle.geo_utils import parse_bd_lnglat
from app.main import CreateTaskBody, app

client = TestClient(app)

# BMapGL dragend 实测值（百度墨卡托平面坐标，单位米）——「类型正确、语义错误」的标本
MERCATOR = [11440230.814822754, 2860409.5195051003]
KAILI = [107.9758, 26.5734]


# ── 1. parse_bd_lnglat：值域契约的唯一实现 ──────────────────────
@pytest.mark.parametrize(
    "raw, why",
    [
        (MERCATOR, "百度墨卡托米（历史事故值）"),
        ([1.0], "长度 1 —— 旧实现会放行，并在 center[1] 抛 IndexError"),
        ([], "长度 0"),
        ([1.0, 2.0, 3.0], "长度 3"),
        (["107.9", "26.5"], "字符串分量"),
        ([None, None], "None 分量"),
        ([True, False], "bool 分量（bool 是 int 子类，须显式排除）"),
        ([math.inf, 0.0], "inf"),
        ([0.0, math.nan], "nan"),
        ([181.0, 0.0], "经度越界"),
        ([-181.0, 0.0], "经度越界（负）"),
        ([0.0, 91.0], "纬度越界"),
        ([0.0, -91.0], "纬度越界（负）"),
        ("107.9758,26.5734", "字符串（不是序列）"),
        (107.9758, "标量"),
        (None, "None"),
    ],
)
def test_parse_bd_lnglat_rejects(raw, why):
    assert parse_bd_lnglat(raw) is None, f"应拒绝：{why}"


@pytest.mark.parametrize(
    "raw",
    [KAILI, (107.9758, 26.5734), [107, 26], [-180.0, -90.0], [180.0, 90.0], [0.0, 0.0]],
)
def test_parse_bd_lnglat_accepts(raw):
    got = parse_bd_lnglat(raw)
    assert got is not None
    assert isinstance(got, tuple) and len(got) == 2
    assert got[0] == float(raw[0]) and got[1] == float(raw[1])


# ── 2. API 入参：脏坐标不许进库（唯一的写入口关）────────────────
def test_task_body_rejects_mercator():
    """墨卡托米必须被 422 拦下 —— 这是 bug 的注入点。"""
    with pytest.raises(ValidationError):
        CreateTaskBody(query="北京劲松", type="living_circle", center=MERCATOR)


def test_task_body_rejects_short_list():
    """``[1.0]`` 必须被拦下（旧实现在 ``center[1]`` 抛 IndexError）。"""
    with pytest.raises(ValidationError):
        CreateTaskBody(query="x", type="living_circle", center=[1.0])


def test_task_body_accepts_legal_center():
    body = CreateTaskBody(query="凯里老街", type="living_circle", center=KAILI)
    assert body.center == KAILI


def test_task_body_accepts_missing_center():
    """center 是可选的（纯地名输入走后端地理编码兜底）。"""
    assert CreateTaskBody(query="凯里老街", type="living_circle").center is None


def test_post_task_http_422_on_mercator():
    resp = client.post(
        "/api/tasks",
        json={"query": "北京劲松", "type": "living_circle", "center": MERCATOR},
    )
    assert resp.status_code == 422, resp.text


def test_post_task_http_422_on_short_list():
    resp = client.post(
        "/api/tasks",
        json={"query": "北京劲松", "type": "living_circle", "center": [1.0]},
    )
    assert resp.status_code == 422, resp.text


def test_post_task_http_ok_on_legal_center():
    resp = client.post(
        "/api/tasks",
        json={"query": "凯里老街", "type": "living_circle", "center": KAILI},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["taskId"].startswith("lc-")


def test_research_task_still_works_without_center():
    """旧路径零回归：不带 center 的研究型任务照常创建。"""
    resp = client.post("/api/tasks", json={"query": "竞品调研", "mode": "quick"})
    assert resp.status_code == 200, resp.text


# ── 3. 坐标系归一：WGS-84 → BD-09（浏览器原生定位的降级路径）────────
# 浏览器 `navigator.geolocation` 给的是 **WGS-84**，与 BD-09 相差约 600m —— 与 15 分钟
# 生活圈同量级。旧实现在这条路上直接把 WGS-84 当 BD-09 用，中心静默偏移。
WGS84 = [116.3975, 39.9087]  # 天安门（WGS-84）


def _patch_ak(monkeypatch, ak: str) -> None:
    """把 `settings.baidu_server_ak` 固定为 `ak`（`_to_bd09` 在调用点才 import，能生效）。"""
    import app.core.config as cfg

    class _S:
        baidu_server_ak = ak
        baidu_max_qps = 3.0  # 镜像 Settings 配额档位契约（`_default_guard` 消费）
        baidu_max_concurrency = 2

    monkeypatch.setattr(cfg, "get_settings", lambda: _S())


def _patch_geoconv(monkeypatch, result):
    """替换 `geoconv`，并记录调用参数（断言 from_/to 编号没写反）。"""
    from app.living_circle import baidu_client as bc

    seen: dict = {}

    async def fake_geoconv(self, coords, from_=1, to=5):
        seen["coords"], seen["from"], seen["to"] = coords, from_, to
        return result

    async def fake_aclose(self):
        return None

    monkeypatch.setattr(bc.BaiduClient, "geoconv", fake_geoconv)
    monkeypatch.setattr(bc.BaiduClient, "aclose", fake_aclose)
    return seen


def test_bd09_center_passes_through_unchanged():
    """coord_sys 缺省 bd09 → 坐标原样入库（不引入任何隐式转换）。"""
    resp = client.post(
        "/api/tasks",
        json={"query": "凯里老街", "type": "living_circle", "center": KAILI, "city": "贵州·凯里"},
    )
    assert resp.status_code == 200, resp.text
    from app.core import db

    clar = db.get_task_full(resp.json()["taskId"])["clarifications"]
    assert clar["center"] == KAILI


def test_wgs84_center_without_ak_is_rejected(monkeypatch):
    """缺 AK 时**拒绝**而不是照抄：错中心一旦落库，每次打开都复现。"""
    _patch_ak(monkeypatch, "")
    resp = client.post(
        "/api/tasks",
        json={"query": "天安门", "type": "living_circle", "center": WGS84, "coord_sys": "wgs84"},
    )
    assert resp.status_code == 422, resp.text
    assert "WGS-84" in resp.json()["detail"]


def test_wgs84_center_converted_via_geoconv(monkeypatch):
    """有 AK 时经 geoconv 转换成 BD-09 后才落库（落库值必须是转换后的）。"""
    converted = [(116.4036, 39.9152)]  # 模拟 geoconv 返回的 BD-09
    seen = _patch_geoconv(monkeypatch, converted)
    _patch_ak(monkeypatch, "dummy-ak-32-chars-0000000000000x")
    resp = client.post(
        "/api/tasks",
        json={"query": "天安门", "type": "living_circle", "center": WGS84, "coord_sys": "wgs84"},
    )
    assert resp.status_code == 200, resp.text
    # 转换入参必须是原始 WGS-84，且 from_=1(WGS-84) / to=5(BD-09 ll)
    assert seen["coords"] == [(WGS84[0], WGS84[1])]
    assert (seen["from"], seen["to"]) == (1, 5)
    from app.core import db

    clar = db.get_task_full(resp.json()["taskId"])["clarifications"]
    assert clar["center"] == [converted[0][0], converted[0][1]]


def test_wgs84_center_rejected_when_geoconv_returns_garbage(monkeypatch):
    """转换服务返回非坐标 → 502，绝不把「看起来像坐标的值」写进库。"""
    _patch_geoconv(monkeypatch, [])
    _patch_ak(monkeypatch, "dummy-ak-32-chars-0000000000000x")
    resp = client.post(
        "/api/tasks",
        json={"query": "天安门", "type": "living_circle", "center": WGS84, "coord_sys": "wgs84"},
    )
    assert resp.status_code == 502, resp.text

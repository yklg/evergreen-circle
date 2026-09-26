"""场景档（居住 / 游客）的口径与缓存隔离守卫。

第一片 D1 / D2 / D11 的可执行形式。为什么这是根因级而不是加个参数：

* `caliber_payload_key` 今天是 **5 段手工拼接串**（scene|center|radius|profile|mode），
  历史上漏传 `travel_mode` 就造成过"选骑行却拿到步行报告"的串缓存
  （`core/pipeline/living_circle.py:110-123` 的注释就是那次教训）。场景档若同样漏进键，
  **社区体检会命中景点体检的缓存**（反之亦然），而两者判表完全不同 —— UI 上看不出来。
* 邻近复用（`data_source.py:298 find_recent_report_near(data_mode, center, 500m)`）是
  **第二条**取数路径，同样必须带场景，否则精确缓存隔离了、邻近命中照样串。
* `capability_manifest.json` 只按出行方式记实测。索引升二维后，若游客档拿不到自己的
  探针条目却"顺手"继承 walking 的 `measured=True`，就是在**没有实测的地方声称实测** ——
  直接打穿本项目「口径可举证」的立身之本。

计划编号：G-01 / G-03，TC-01 / TC-02 / TC-04（D1 投影层的守恒面在
`test_scenario_category_completeness.py`）。
全部为 **登记缺口的 xfail(strict)**：功能落地后若变 XPASS，会强制摘标记，防止"标记长住"。
"""
import inspect

import pytest

from app.living_circle import caliber
from app.living_circle.assemble import assemble_living_circle
from app.living_circle.repository import Repository


@pytest.mark.xfail(strict=True, reason="D2：caliber_payload_key 尚无 scenario 维度")
def test_scenario_is_a_cache_key_dimension():
    """同一中心、同一出行方式，不同场景 ⇒ 键必须不同。"""
    key_home = caliber.caliber_payload_key(
        "大理古城", (100.170478, 25.700801), 2500, "standard", "walking", scenario="residential"
    )
    key_visit = caliber.caliber_payload_key(
        "大理古城", (100.170478, 25.700801), 2500, "standard", "walking", scenario="visitor"
    )
    assert key_home != key_visit, "两场景共用了同一个缓存键 ⇒ 会串档"


@pytest.mark.xfail(strict=True, reason="D2：键由手工拼接串构成，未收敛为身份值对象")
def test_cache_key_is_derived_from_an_identity_value_object():
    """判据指向结构而非段数：加维度不应靠"再拼一段 + 改一处计数"来保证。

    本仓已有三处各自复刻键格式（`test_caching_datasource.py:58` 自认的已知脆弱点）。
    D2 落地后应存在 `CheckIdentity`，键由它派生。
    """
    assert hasattr(caliber, "CheckIdentity"), "身份值对象尚未落地"
    fields = set(inspect.signature(caliber.CheckIdentity).parameters)
    assert {"scenario", "travel_mode", "sample_profile", "data_mode"} <= fields, (
        f"身份对象字段不全：{sorted(fields)}"
    )


@pytest.mark.xfail(strict=True, reason="D2：邻近复用查询未带场景维度")
def test_nearby_cache_lookup_carries_the_scenario():
    """≤500m 邻近命中是第二条取数路径，必须与精确缓存同样隔离。

    真实接缝：``data_source.py:298`` 调 ``repo.find_recent_report_near(data_mode, center, 500)``，
    实现体在 ``repository.py:267``，扫描前缀只有 ``{data_mode}:report:`` ⇒ 两档报告同前缀，
    社区档会直接捞到景点档的邻近结果（判表完全不同，UI 上看不出来）。
    """
    params = set(inspect.signature(Repository.find_recent_report_near).parameters)
    assert "scenario" in params, f"邻近查询参数缺 scenario：{sorted(params)}"


@pytest.mark.xfail(strict=True, reason="D11：caliber 索引仍是一维，游客档无法声明自己的实测状态")
def test_unprobed_scenario_mode_combination_is_not_measured():
    """未探明的 (scenario, travel_mode) 组合必须 `measured=False`，且**不得**继承邻近档。"""
    visitor = caliber.get_caliber("walking", scenario="visitor")
    assert visitor.measured is False, "游客档没有自己的探针，却声称实测"
    assert visitor.scenario == "visitor", "口径对象未携带场景，举证无法区分两档"


@pytest.mark.xfail(strict=True, reason="D1：assemble 尚无场景维度，游客档无法按档投影")
def test_assemble_accepts_a_scenario_without_touching_the_stored_set():
    """守恒不变量与场景无关 ⇒ 组装层必须**先按全集落库**，投影只发生在展示层。

    本仓已有 `test_poi_conservation.py` 的守恒出口，但守恒**抓不到**整类被裁（见
    `test_scenario_category_completeness.py` 的实测记录）⇒ 场景维度落地时必须
    同时补类别集完整性守卫，否则「投影层」与「组装层」谁裁的类别无法分辨。
    """
    params = set(inspect.signature(assemble_living_circle).parameters)
    assert "scenario" in params, f"组装层参数缺 scenario：{sorted(params)}"

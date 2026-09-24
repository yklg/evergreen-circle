"""舆情 (spot × platform) 双维聚合契约（M2c，plan 改钉③）。

不变量：
- by_platform 旧形状 {plat: {pos,neu,neg}} 不回归（全局面板/声量图数据源）；
- by_spot 只收录带 spot_id 的评论（实体直引，不做名称二次匹配），样本降序、占比和=100；
- 无评论 → 空结构含 by_spot 键（读兼容不 KeyError）。

LLM 边界：monkeypatch sentiment.chat_json 返回 None → 逐条情感走规则兜底，
用例不耦合模型输出。
"""
import pytest

from app.core import sentiment as S


@pytest.fixture(autouse=True)
def _rule_only(monkeypatch):
    monkeypatch.setattr(S, "chat_json", lambda *a, **k: None)


def _comments():
    rows = [
        {"text": "风景很好，值得去", "platform": "douyin"},
        {"text": "排队太久，劝退", "platform": "xiaohongshu"},
        {"text": "古城夜景很美，值得去", "platform": "douyin",
         "spot_id": "大理_spot_1", "spot_name": "大理古城"},
        {"text": "商业化严重，踩坑", "platform": "xiaohongshu",
         "spot_id": "大理_spot_1", "spot_name": "大理古城"},
        {"text": "环海骑行很舒服", "platform": "bilibili",
         "spot_id": "大理_spot_2", "spot_name": "洱海廊道"},
    ]
    for i, c in enumerate(rows):
        c.setdefault("url", f"https://s{i}.example.com/p")
        c.setdefault("title", f"口碑{i}")
        c.setdefault("destination", "大理")
    return rows


def test_empty_result_carries_by_spot_key():
    out = S.analyze_sentiment("大理", [])
    assert out["by_spot"] == [] and out["by_platform"] == {}


def test_by_platform_old_shape_not_regressed():
    out = S.analyze_sentiment("大理", _comments())
    assert set(out["by_platform"]) <= set(S.PLATFORM_ORDER)
    for plat, counts in out["by_platform"].items():
        assert set(counts) == {"pos", "neu", "neg"}
    total = sum(sum(c.values()) for c in out["by_platform"].values())
    assert total == out["sample_size"] == 5  # 含 spot 补充采集的评论，全局口径合并


def test_by_spot_groups_by_entity_with_pct_and_platforms():
    out = S.analyze_sentiment("大理", _comments())
    spots = {g["spot_id"]: g for g in out["by_spot"]}
    assert set(spots) == {"大理_spot_1", "大理_spot_2"}, "无 spot_id 评论不进 by_spot"
    g1 = spots["大理_spot_1"]
    assert g1["spot_name"] == "大理古城" and g1["sample"] == 2
    assert g1["pos"] + g1["neu"] + g1["neg"] == 100
    assert g1["pos"] == 50 and g1["neg"] == 50  # 规则兜底：一赞一贬
    assert g1["by_platform"] == {"douyin": 1, "xiaohongshu": 1}
    # 样本降序、同样本按 spot_id 稳定序（可复现）
    assert [g["spot_id"] for g in out["by_spot"]] == ["大理_spot_1", "大理_spot_2"]


def test_by_spot_deterministic_across_runs():
    first = S.analyze_sentiment("大理", _comments())["by_spot"]
    second = S.analyze_sentiment("大理", _comments())["by_spot"]
    assert first == second


# ── 逐景点补充采集接线（orchestrator._collect_spot_comments）──────────

def test_collect_spot_comments_filters_dedupes_and_orders(monkeypatch):
    """TC-P03：景点名相关性硬门槛（题不对版必剔）、seen_urls 去重、
    按（榜单名次 × 平台序）确定性展平，评论挂 spot_id/spot_name。"""
    import asyncio

    from app.core import orchestrator as O

    def fake_multi_search(queries, *, num=10, site=None, freshness="noLimit"):
        q = queries[0]
        if "古城" in q:
            return [
                {"url": "https://a1.example/x", "title": "大理古城夜游记", "snippet": "大理古城很好逛"},
                {"url": "https://off.example/x", "title": "汽水音乐推荐", "snippet": "完全不相关"},
                {"url": "https://dup.example/x", "title": "大理古城二刷", "snippet": "大理古城值得去"},
            ]
        if "洱海" in q:
            return [{"url": "https://b1.example/x", "title": "洱海廊道骑行", "snippet": "洱海廊道风景好"}]
        return []

    monkeypatch.setattr(O, "multi_search", fake_multi_search)
    spots = [{"spot_id": "大理_spot_1", "name": "大理古城（含崇圣寺）"},
             {"spot_id": "大理_spot_2", "name": "洱海廊道"}]
    seen = {"https://dup.example/x"}  # 基础采集已收 → 不得重复入样
    out = asyncio.run(O._collect_spot_comments(
        spots, ["douyin", "xhs"], " 云南", 2, "oneYear", "大理", seen))

    urls = [c["url"] for c in out]
    assert "https://off.example/x" not in urls, "题不对版评论必须被剔除"
    assert "https://dup.example/x" not in urls, "seen_urls 去重必须生效"
    # 名次×平台序展平：spot1 先于 spot2；跨平台重复 URL 只保留首次归属
    assert urls == ["https://a1.example/x", "https://b1.example/x"]
    assert all(c["destination"] == "大理" for c in out)
    assert out[0]["spot_id"] == "大理_spot_1" and out[0]["spot_name"] == "大理古城（含崇圣寺）"
    assert out[0]["platform"] == "douyin"

    # 补充采集样本进入双维聚合：by_spot 覆盖两个冻结实体
    senti = S.analyze_sentiment("大理", out)
    assert {g["spot_id"] for g in senti["by_spot"]} == {"大理_spot_1", "大理_spot_2"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

"""目的地集合政策 + 搜索角度正交化 的契约（《目的地集合政策 + 搜索角度正交化》§5.4）。

守护的不变量（每条用例回溯其一，编号见计划 §5.4 差距矩阵）：
- 判据唯一：勾选 / 原文提及 / 三跳兜底四条取数路径共用 `_usable_destination`（G1）。
- 来源唯一：目的地集合 = 勾选 ∪ 原文提及，模型候选只是待验证的池子（G15）。
- 角度正交：角度不含地名；天数角度至多 1 条且短语必出自用户原文（G5/G6/G9、M8）。
- 图集与文案按目的地数自适应，且不改动注册表共享元组（G7、INV-01）。
- 兜底链逐跳可观测；模型不可用类异常一律转抛，不伪装成「自动识别」（G12/G13、EX-03）。

运行：backend/ 下 `pytest tests/test_destination_policy.py -q`
"""
import pytest

from app.core import db
from app.core import orchestrator as O
from app.core import research_types as RT
from app.core import trace
from app.core.llm import LLMModelUnavailable

TYPES = ["guide", "assessment"]
ONE_CITY_QUERY = "我想去上海玩三天"
NO_CITY_QUERY = "我想去个没去过的安静小城玩三天"


class _PlanLLM:
    """可编程的计划 LLM 假件：按 purpose 分发并记录调用；未知 purpose 一律 raise。

    与 test_two_type_pipeline 的 mock 同一契约（TC-X0）：静默 `return None` 会让新增
    调用点悄悄走兜底分支，用例照绿却什么都没测。
    """

    def __init__(self, plan=None, retry=None, raises=None):
        self.plan = plan or {}
        self.retry = retry
        self.raises = raises or {}          # {purpose 前缀: 异常实例}
        self.purposes: list = []
        self.retry_calls = 0

    def __call__(self, messages, temperature=0.3, max_tokens=2048, model=None, *, purpose=""):
        self.purposes.append(purpose)
        for prefix, exc in self.raises.items():
            if purpose.startswith(prefix):
                raise exc
        if purpose == "拆解调研计划（目的地/维度/搜索角度）":
            return dict(self.plan)
        if purpose == O._DEST_RETRY_PURPOSE:
            self.retry_calls += 1
            return self.retry
        raise AssertionError(f"未预期的 LLM 调用 purpose：{purpose!r}")


def _install(monkeypatch, **kw) -> _PlanLLM:
    fake = _PlanLLM(**kw)
    monkeypatch.setattr(O, "chat_json", fake, raising=False)
    return fake


# ── G1 · 判据的字符等价类 ──────────────────────────────────
@pytest.mark.parametrize("name,ok", [
    ("上海", True), ("上海市", True), ("乌镇", True), ("Lake Como", True),
    ("大理洱源", True), ("lhasa", True), ("目的地", True),
    ("", False), ("   ", False), ("沪", False),                    # 空 / 纯空白 / 单字
    ("　", False), ("🙂", False), ("12345", False),                 # 全角空格 / emoji / 纯数字串
    ("我想去上海玩三天", False),                                      # 注入式整句需求
    ("上海与杭州", False), ("上海和杭州", False), ("大理、丽江", False),
    ("上海/杭州", False), ("北京vs上海", False), ("北京VS上海", False),
    ("对比两个城市", False), ("攻略", False), ("怎么玩才省钱", False),
])
def test_usable_destination_equivalence_classes(name, ok):
    assert O._usable_destination(name) is ok, name


@pytest.mark.parametrize("n,ok", [
    (1, False), (2, True), (O._MAX_DEST_NAME_LEN, True), (O._MAX_DEST_NAME_LEN + 1, False),
])
def test_usable_destination_length_window_is_inclusive(n, ok):
    """边界：**闭**区间 [2, _MAX_DEST_NAME_LEN]；越界一律拒（长度用 len() 而非字节数）。"""
    assert O._usable_destination("阿" * n) is ok


def test_judge_is_shared_by_all_destination_sources():
    """兜底链与主路径共用同一判据：不存在「换条路径即复现历史缺陷」。"""
    bad = "我想去上海玩三天"
    assert O._usable_destination(bad) is False
    assert O._checked_destinations({"destinations": [bad]}) == []
    assert O._destination_set(bad, {}, [bad]) == ([], "")


# ── G2 · 核心名剥离 ────────────────────────────────────────
@pytest.mark.parametrize("name,core", [
    ("上海市", "上海"), ("上海", "上海"), ("乌镇", "乌镇"),
    ("吉林省", "吉林省"),            # 只剥「市」，否则省级地名被误并到市
    ("市", "市"),                    # 剩余不足 2 字不剥
    ("  大理市  ", "大理"),
])
def test_core_name_strips_only_city_suffix(name, core):
    assert O._core_name(name) == core


def test_core_name_is_idempotent():
    for name in ("上海市", "上海", "吉林省", "Lake Como", "市"):
        once = O._core_name(name)
        assert O._core_name(once) == once


# ── G3 · 原文提及判定 ──────────────────────────────────────
def test_mentioned_in_text_is_one_directional():
    """只做「候选名 ⊆ 原文」的单向判定：反向包含会让「海」命中「上海」。"""
    assert O._mentioned_in_text("海", ONE_CITY_QUERY) is False
    assert O._mentioned_in_text("上海", "我想去上海市") is True
    assert O._mentioned_in_text("上海市", "我想去上海") is True
    assert O._mentioned_in_text("上海", "我想去杭州") is False
    assert O._mentioned_in_text("大理", "") is False
    assert O._mentioned_in_text(None, ONE_CITY_QUERY) is False


def test_mentioned_in_text_is_case_insensitive_for_ascii():
    assert O._mentioned_in_text("lake como", "A TRIP TO LAKE COMO") is True
    assert O._mentioned_in_text("LAKE COMO", "a trip to lake como") is True


# ── G4 · 天数只认原文 ──────────────────────────────────────
@pytest.mark.parametrize("text,phrase", [
    (ONE_CITY_QUERY, "三天"),
    ("大理 丽江 5 天亲子游攻略", "5 天"),
    ("国庆去 3天 行吗", "3天"),
    ("这周末想去走走", "周末"),
    ("十五天环线游", "十五天"),
    ("我想去上海玩", ""),
    ("", ""),
])
def test_days_from_text_returns_source_phrase(text, phrase):
    got = O._days_from_text(text)
    assert got == phrase
    assert not phrase or phrase in text, "天数短语必须是原文片段本身（M8：可溯源）"


def test_days_from_text_prefers_deterministic_value():
    """数字写法优先于中文数词与模糊「周末」，同句多表达时不取模糊值。"""
    assert O._days_from_text("3天 或者周末都行") == "3天"
    assert O._days_from_text(None) == ""


# ── G5/G6/G9 · 角度正交化 ──────────────────────────────────
def _angles(spec, raw, dests, days="", max_angles=7, origin="", focus_kw=()):
    return O._orthogonal_angles(raw, dests, days, spec, max_angles, origin, focus_kw)


def _has_days(angle: str) -> bool:
    return any(p.search(angle) for p in O._DAY_PATTERNS)


@pytest.mark.parametrize("rtype", TYPES)
def test_orthogonal_angles_never_mutates_registry(rtype):
    """回落注册表角度时必须返回新列表：spec 是模块级共享元组，就地改会跨任务污染。"""
    spec = RT.type_spec(rtype)
    before = spec["angles"]
    out = _angles(spec, [f"{d} 攻略" for d in ("大理", "丽江")], ["大理", "丽江"], "")
    assert set(out) <= set(before), "角度全被剔除时必须回落到注册表角度"
    out.append("临时追加项")
    assert spec["angles"] == before and isinstance(spec["angles"], tuple)


def test_orthogonal_angles_drops_place_names():
    spec = RT.type_spec("guide")
    raw = ["大理 古城", "丽江 束河", "交通攻略", "住宿推荐"]
    out = _angles(spec, raw, ["大理", "丽江"], "")
    assert out == ["交通攻略", "住宿推荐"]


def test_orthogonal_angles_keeps_registry_dimension_words():
    """维度词「行程路线」不含地名/天数，不被误伤（与注册表角度是否含它无关）。"""
    spec = RT.type_spec("guide")
    assert _angles(spec, ["行程路线", "大理 古城"], ["大理"], "") == ["行程路线"]


def test_orthogonal_angles_tolerates_junk_input():
    spec = RT.type_spec("guide")
    out = _angles(spec, [None, 3, "", "   ", "交通攻略"], ["大理"], "")
    assert out == ["交通攻略"]
    assert _angles(spec, [], ["大理"], "") == list(spec["angles"])[:7]
    assert _angles(spec, None, ["大理"], "") == list(spec["angles"])[:7]


def test_days_angle_exactly_one_and_traceable():
    """天数角度恰好 1 条、短语出自原文；模型角度里塞的天数一律被剔（M8）。"""
    spec = RT.type_spec("guide")
    phrase = O._days_from_text(ONE_CITY_QUERY)
    out = _angles(spec, ["5天行程", "三天两晚", "行程路线", "交通攻略"], ["上海"], phrase)
    days_lines = [a for a in out if _has_days(a)]
    assert days_lines == ["三天行程"], out
    assert phrase in days_lines[0]


def test_days_angle_at_most_one_even_with_many():
    spec = RT.type_spec("guide")
    out = _angles(spec, ["3天行程", "五天四晚", "两日", "交通攻略"], ["上海"], "3天")
    assert [a for a in out if _has_days(a)] == ["3天行程"]


def test_days_angle_absent_when_query_has_no_days():
    spec = RT.type_spec("guide")
    out = _angles(spec, ["交通攻略", "住宿推荐"], ["上海"], "")
    assert not [a for a in out if _has_days(a)]


def test_days_angle_skipped_for_type_without_template():
    """assessment 未配 days_angle_tpl → 有天数也不生成，且不抛（缺省容忍）。"""
    spec = RT.type_spec("assessment")
    assert "days_angle_tpl" not in spec
    out = _angles(spec, ["交通攻略", "住宿推荐"], ["上海"], "三天")
    assert not [a for a in out if _has_days(a)]


def test_days_angle_reserves_a_slot():
    """为天数角度预留一格：夹到 max_angles 时它不被前面的角度挤掉。"""
    spec = RT.type_spec("guide")
    out = _angles(spec, ["交通攻略", "住宿推荐", "门票与价格", "避坑指南"], ["上海"], "三天", 3)
    assert len(out) == 3 and "三天行程" in out


# ── C2 · 天数判据双源：原文优先，问卷答案只补原文的缺 ──────────
def test_days_angle_from_answer_when_query_silent(monkeypatch):
    """TC-D1：query 没写天数、答案勾了「3-5 天」→ 天数角度照样生成，短语取自答案。"""
    _, out, _ = _plan(monkeypatch, "我想去上海玩", {"days": "3-5 天"}, plan={
        "subject": "上海", "destinations": ["上海"], "search_angles": ["交通攻略"]})
    assert [a for a in out["angles"] if _has_days(a)] == ["5 天行程"]


def test_days_angle_query_wins_over_answer(monkeypatch):
    """TC-D2：原文写了 5 天、答案却勾 10 天以上 → 原文优先（显式说过就以它为准）。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {"days": "10 天以上"}, plan={
        "subject": "大理", "destinations": ["大理"], "search_angles": ["交通攻略"]})
    days_lines = [a for a in out["angles"] if _has_days(a)]
    assert days_lines == ["5 天行程"] and "10 天" not in "".join(out["angles"])


def test_days_answer_without_pattern_is_silent(monkeypatch):
    """答案可能是「还没定」这类模糊语：抽不出原文短语就不生成角度，不编天数。"""
    _, out, _ = _plan(monkeypatch, "我想去上海玩", {"days": "还没定"}, plan={
        "subject": "上海", "destinations": ["上海"], "search_angles": ["交通攻略"]})
    assert not [a for a in out["angles"] if _has_days(a)]


# ── C3 · origin 答案 → 城际交通角度（与天数角度同型机制）───────
@pytest.mark.parametrize("raw,expected", [
    ("北京", "北京"),
    ("  北京市  ", "北京市"),
    ("", ""), ("还没定", ""), ("本地", ""), ("待定", ""),
    ("我想从北京出发去大理玩三天", ""),           # 整句不是地名（判据拒）
    ("阿" * 20, ""),                              # 超长乱码
])
def test_origin_answer_gate(raw, expected):
    """消费点闸门：skip 词组整串精确匹配 + 复用 `_usable_destination`，一个判据不另起炉灶。"""
    assert O.origin_answer({"origin": raw}) == expected


def test_origin_answer_missing_key_is_safe():
    assert O.origin_answer({}) == "" and O.origin_answer(None) == ""


def test_origin_angle_exactly_one_via_plan(monkeypatch):
    """TC-O1：填「北京」→ 角度集中恰 1 条城际交通角度，来自注册表模板。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {"origin": "北京"}, plan={
        "subject": "大理", "destinations": ["大理"], "search_angles": ["交通攻略", "住宿推荐"]})
    intercity = [a for a in out["angles"] if "城际" in a]
    assert intercity == ["北京出发 城际交通方式 耗时 票价"]


@pytest.mark.parametrize("origin", ["", "还没定", "本地", "我想从北京出发"])
def test_origin_angle_absent_for_skip_answers(monkeypatch, origin):
    """TC-O2：空/skip 词组/整句 → 0 追加，绝不生成「还没定出发 城际交通…」脏检索词。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {"origin": origin}, plan={
        "subject": "大理", "destinations": ["大理"], "search_angles": ["交通攻略"]})
    assert not [a for a in out["angles"] if "城际" in a]


def test_origin_angle_skipped_for_type_without_tpl(monkeypatch):
    """TC-O3：assessment 未配 origin_angle_tpl（其 origin 题是 plan_text 档位题）→ 不注入不抛。"""
    spec = RT.type_spec("assessment")
    assert "origin_angle_tpl" not in spec
    assert not [a for a in _angles(spec, ["交通可达性"], ["上海"], "", origin="北京")
                if "城际" in a]


def test_origin_and_days_angles_both_reserve_slots():
    """TC-O4：两条确定性角度各占一格，截断时都不被模型角度挤掉。"""
    spec = RT.type_spec("guide")
    out = _angles(spec, ["交通攻略", "住宿推荐", "门票与价格"], ["大理"], "三天", 4, "北京")
    assert len(out) == 4 and "三天行程" in out and any("城际" in a for a in out)


# ── C4 · focus 勾选：取证前置 + 角度稳定排序 ──────────────────
def test_plan_focus_questionnaire_preferred(monkeypatch):
    """TC-F1：问卷勾选的维度排在前、LLM 抽取并入其后（显式通道优先）。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {"focus": ["交通路线"]}, plan={
        "subject": "大理", "destinations": ["大理"], "focus": ["美食"],
        "search_angles": ["住宿推荐", "交通攻略"]})
    assert out["focus"] == ["交通路线", "美食"]
    assert out["angles"][0] == "交通攻略", "勾选维度的匹配角度必须前置（截断前排序）"


def test_plan_focus_falls_back_to_llm(monkeypatch):
    """TC-F2：未勾选 → LLM 抽取照旧；两者皆空才落默认维度表。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {}, plan={
        "subject": "大理", "destinations": ["大理"], "focus": ["口碑"],
        "search_angles": ["交通攻略"]})
    assert out["focus"] == ["口碑"]
    _, out2, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {}, plan={
        "subject": "大理", "destinations": ["大理"], "search_angles": ["交通攻略"]})
    assert out2["focus"] == ["交通", "住宿", "预算", "口碑"]


def test_focus_sort_is_stable_and_truncation_favors_hits():
    """TC-F3：命中关键词的前置且互保持原序；夹到 max_angles 时先保命中项。"""
    spec = RT.type_spec("guide")
    raw = ["门票与价格", "住宿推荐", "交通攻略", "美食打卡"]
    out = _angles(spec, raw, ["大理"], "", 2, focus_kw=("交通", "路线"))
    assert out == ["交通攻略", "门票与价格"]
    out_all = _angles(spec, raw, ["大理"], "", 4, focus_kw=("交通", "路线"))
    assert out_all == ["交通攻略", "门票与价格", "住宿推荐", "美食打卡"]


# ── G7 · 图集 / 分析键按目的地数自适应 ──────────────────────
@pytest.mark.parametrize("rtype", TYPES)
@pytest.mark.parametrize("n", [0, 1, 2, 6, 7])
def test_adaptive_sets_are_subsets_and_gated_by_n(rtype, n):
    spec = RT.type_spec(rtype)
    charts = RT.charts_for(rtype, n)
    keys = RT.analysis_keys_for(rtype, n)
    assert set(charts) <= set(spec["charts"])
    assert set(keys) <= set(spec["analysis_keys"])
    assert ("donut" in charts) is (n >= 2)
    assert ("share_estimate" in keys) is (n >= 2)
    assert ("radar" in charts) is ("radar" in spec["charts"])   # 单目的地保留雷达（决策 5.2）


@pytest.mark.parametrize("rtype", TYPES)
def test_titles_follow_destination_count(rtype):
    spec = RT.type_spec(rtype)
    assert "对比" not in RT.radar_title(rtype, 1)
    assert "对比" not in RT.cost_bar_title(rtype, 1)
    assert RT.radar_title(rtype, 2) == spec["radar_title"]
    assert RT.cost_bar_title(rtype, 2) == spec["cost_bar"]["title"]


# ── G15 · 集合运算：并集只增不减、去重保序、上限 ───────────────
def test_destination_set_union_dedupe_and_cap():
    query = "大理和丽江香格里拉西双版纳腾冲昆明上海"
    dests, source = O._destination_set(
        query, {"destinations": ["丽江", "大理"]},
        ["大理", "丽江", "香格里拉", "西双版纳", "腾冲", "昆明", "上海"])
    assert source == "clarify"
    assert dests[:2] == ["丽江", "大理"], "勾选在前，其余按原文提及顺序并入"
    assert len(dests) == O._MAX_DESTINATIONS, "超限截断"
    assert all(O._usable_destination(d) for d in dests)


def test_destination_set_never_shrinks_below_checks():
    """用户没在原文提的勾选项照样纳入（并集只增不减）。"""
    dests, source = O._destination_set("随便安排一下", {"destinations": ["厦门"]},
                                       ["厦门", "泉州"])
    assert dests == ["厦门"] and source == "clarify"


def test_destination_set_dedupe_by_core_name():
    assert O._destination_set(ONE_CITY_QUERY, {}, ["上海", "上海市"])[0] == ["上海"]


def test_destination_set_rejects_unmentioned_candidates():
    """历史症状直证：模型自扩的五城里，用户没点名的一个都不留。"""
    assert O._destination_set(ONE_CITY_QUERY, {},
                              ["上海", "杭州", "苏州", "南京", "厦门"]) == (["上海"], "query")


def test_destination_set_empty_when_nothing_qualifies():
    assert O._destination_set(ONE_CITY_QUERY, {}, ["杭州", "苏州"]) == ([], "")


# ── G10/G16 · 计划层：采纳与降级 ────────────────────────────
def _plan(monkeypatch, query, clar=None, rtype="guide", **kw):
    """跑一次 `_plan_research`，连带返回该任务的 trace span（降级可观测性）。"""
    fake = _install(monkeypatch, **kw)
    task_id = "t_policy_plan"
    trace.cleanup(task_id)
    out = O._plan_research(query, clar or {}, 7, rtype, task_id)
    return fake, out, [s for s in trace.get_trace(task_id)
                       if s["purpose"] == O._DEST_PLAN_STEP]


def test_plan_ignores_model_self_expanded_destinations(monkeypatch):
    """首屏症状修复：query 只提上海、模型返 5 城 → 只 1 地，且不误判为降级。"""
    _, out, spans = _plan(monkeypatch, ONE_CITY_QUERY, plan={
        "subject": "上海", "destinations": ["上海", "杭州", "苏州", "南京", "厦门"],
        "focus": ["交通"], "search_angles": ["交通攻略", "住宿推荐"]})
    assert out["destinations"] == ["上海"]
    assert out["degraded"] is False and out["dest_source"] == "query"
    assert spans == [], "非降级路径不写降级 span（G16 反向面）"


def test_plan_days_angle_comes_from_query_not_model(monkeypatch):
    """模型给的 search_angles 里带天数 → 丢弃，只保留原文那一条（M8）。"""
    _, out, _ = _plan(monkeypatch, ONE_CITY_QUERY, plan={
        "subject": "上海", "destinations": ["上海"], "search_angles": ["5天行程", "交通攻略"]})
    assert [a for a in out["angles"] if _has_days(a)] == ["三天行程"]


def test_plan_keeps_multi_destination_behaviour(monkeypatch):
    """多目的地路径与本期改造前一致（assessment 不受单目的地约束）：原文点名的两城都在，角度里没有地名。
    guide 档的多目的地终点闸门见 test_guide_single_dest.py（G24）。"""
    _, out, _ = _plan(monkeypatch, "大理 丽江 5 天亲子游攻略", rtype="assessment", plan={
        "subject": "大理", "destinations": ["大理", "丽江"],
        "search_angles": ["大理 古城", "交通攻略", "住宿推荐"]})
    assert out["destinations"] == ["大理", "丽江"]
    assert not [a for a in out["angles"] if "大理" in a or "丽江" in a]
    assert out["dest_source"] == "query" and out["degraded"] is False


def test_plan_respects_checked_destinations(monkeypatch):
    """勾选是显式通道：只出现在勾选项里的目的地被纳入（guide 单目的地闸门下用 assessment 验此不变量）。"""
    _, out, _ = _plan(monkeypatch, "大理 5 天亲子游攻略", {"destinations": ["丽江"]}, rtype="assessment", plan={
        "subject": "大理", "destinations": ["大理", "丽江"]})
    assert out["destinations"] == ["丽江", "大理"] and out["dest_source"] == "clarify"


def test_plan_degrades_to_fallback_and_traces(monkeypatch):
    """计划拿不到目的地 → degraded=True + 恰好一条 trace 留痕（报告 payload 不含该字段由集成用例守）。"""
    fake, out, spans = _plan(monkeypatch, NO_CITY_QUERY, plan={
        "subject": "大理", "destinations": ["大理", "丽江"], "search_angles": ["交通攻略"]},
        retry={"destination": "候选小城"})
    assert out["degraded"] is True
    assert out["destinations"] == ["候选小城"] and out["dest_source"] == "retry"
    assert fake.retry_calls == 1
    assert len(spans) == 1 and "降级" in spans[0]["decision"]


def test_plan_llm_failure_degrades_with_reason_in_trace(monkeypatch):
    """计划 LLM 抛非模型类异常 → 走兜底且 trace 记下异常（不静默伪装成功）。"""
    _, out, spans = _plan(monkeypatch, NO_CITY_QUERY, raises={"拆解调研计划": ValueError("坏 JSON")},
                          retry={"destination": "候选小城"})
    assert out["degraded"] is True
    assert len(spans) == 1
    assert "ValueError" in spans[0]["prompt"], "降级原因（计划 LLM 异常）必须留在决策日志里"


# ── G12 · 三跳兜底链逐跳 ───────────────────────────────────
def test_hop1_uses_cached_subject_without_llm(monkeypatch):
    db.save_discovery_cache(db._query_hash(ONE_CITY_QUERY),
                            {"subject": "上海", "candidates": ["上海"]})
    fake = _install(monkeypatch)
    assert O._fallback_destination(ONE_CITY_QUERY, "guide", "") == ("上海", "cache")
    assert fake.purposes == [], "hop1 命中不得再花任何 LLM 调用"


def test_hop1_rejects_unusable_subject_and_falls_to_static_table(monkeypatch):
    """缓存里躺着整句需求时不得照抄（M5）：判据拒它，改由静态地名表给干净 subject。"""
    db.save_discovery_cache(db._query_hash(ONE_CITY_QUERY),
                            {"subject": ONE_CITY_QUERY, "candidates": []})
    _install(monkeypatch)
    assert O._fallback_destination(ONE_CITY_QUERY, "guide", "") == ("上海", "static")


def test_cache_read_error_is_traced_and_continues(monkeypatch):
    def boom(_hash):
        raise RuntimeError("缓存内容损坏")

    monkeypatch.setattr(db, "get_discovery_cache", boom)
    _install(monkeypatch)
    task_id = "t_policy_cache"
    trace.cleanup(task_id)
    assert O._fallback_destination(ONE_CITY_QUERY, "guide", task_id) == ("上海", "static")
    spans = [s for s in trace.get_trace(task_id) if s["purpose"] == O._DEST_PLAN_STEP]
    assert spans and "hop1" in spans[0]["decision"], "读失败必须留痕而不是静默跳过"
    trace.cleanup(task_id)


def test_hop3_retries_exactly_once(monkeypatch):
    fake = _install(monkeypatch, retry={"destination": "候选小城"})
    task_id = "t_policy_retry"
    trace.cleanup(task_id)
    assert O._fallback_destination(NO_CITY_QUERY, "guide", task_id) == ("候选小城", "retry")
    assert fake.purposes.count(O._DEST_RETRY_PURPOSE) == 1
    trace.cleanup(task_id)


def test_all_hops_miss_returns_empty_with_fallback_source(monkeypatch):
    fake = _install(monkeypatch, retry=None)
    assert O._fallback_destination(NO_CITY_QUERY, "guide", "") == ("", "fallback")
    assert fake.retry_calls == 1, "只在前两跳都 miss 时才触发第三跳，且恰好一次"


# ── G13 · 兜底链不吞模型不可用（禁止遮盖症状）──────────────────
def test_hop3_model_unavailable_is_reraised(monkeypatch):
    _install(monkeypatch, raises={O._DEST_RETRY_PURPOSE: LLMModelUnavailable("fast 档不可用")})
    with pytest.raises(LLMModelUnavailable):
        O._fallback_destination(NO_CITY_QUERY, "guide", "")


def test_plan_model_unavailable_is_reraised(monkeypatch):
    _install(monkeypatch, raises={"拆解调研计划": LLMModelUnavailable("没配模型")})
    with pytest.raises(LLMModelUnavailable):
        O._plan_research(ONE_CITY_QUERY, {}, 7, "guide", "")


def test_empty_fast_model_name_does_not_break_chain(monkeypatch):
    """G17：llm_model_fast 为空串（未配置）时兜底链仍按契约走完，不崩。"""
    monkeypatch.setattr(O, "_model", lambda tier: "")
    _install(monkeypatch, retry={"destination": "候选小城"})
    assert O._fallback_destination(NO_CITY_QUERY, "guide", "") == ("候选小城", "retry")


# ── M7/S7 · 档位属用户显式选择，问卷只下发事实量 ─────────────────
def test_mode_config_is_not_rewritten_by_orchestration():
    assert [O.MODE_CONFIG[m]["max_angles"] for m in ("quick", "deep", "expert")] == [4, 6, 9]
    assert [O.MODE_CONFIG[m]["fetch_per_destination"] for m in ("quick", "deep", "expert")] == \
        [6, 12, 16]
    for mode in ("quick", "deep", "expert"):
        budget = O._budget_facts(mode)
        assert budget["max_angles"] == O.MODE_CONFIG[mode]["max_angles"]
        assert budget["mode_label"] == O.MODE_CONFIG[mode]["label"]


def test_task_mode_falls_back_to_deep_like_run_pipeline():
    tid = O.create_task("大理攻略", "", "", "guide")["taskId"]
    assert O._task_mode(tid) == "deep"                      # meta 里 _mode 为空串
    O.submit_clarify(tid, {"_mode": "expert", "_type": "guide"})
    assert O._task_mode(tid) == "expert"
    O.submit_clarify(tid, {"_mode": "不存在的档位", "_type": "guide"})
    assert O._task_mode(tid) == "deep"


def test_enhanced_questions_carry_workload_facts_per_mode():
    baseline = O._fallback_clarify_questions("大理攻略", "guide")
    scope = {"subject": "大理", "domain": "旅游", "candidates": ["大理", "丽江"]}

    def dest_q(mode):
        qs = {q["id"]: q for q in
              O._build_enhanced_questions(scope, baseline, O._budget_facts(mode))}
        return qs["destinations"]

    assert dest_q("quick")["workload"]["max_angles"] == 4
    assert dest_q("deep")["workload"]["max_angles"] == 6
    no_budget = {q["id"]: q for q in O._build_enhanced_questions(scope, baseline)}
    assert "workload" not in no_budget["destinations"], "未下发 budget 时该题不带 workload 键"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

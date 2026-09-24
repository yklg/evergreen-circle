"""专家团队指派（`orchestrator._dispatch_experts`）的契约与降级可见性测试。

背景（真实故障，见 ~/.qoder-cn/plans/quiet-shore-pike.md）：experts.json 有 48 位专家，
但 `expert_stats` 表只有 6 行、3 份报告的 `experts` 字段全等于
`["L3-001","L2-001","L2-002","L1-025","L1-030","L3-003"]` —— 即
`orchestrator.py:1288-1295` 的硬编码兜底名单。traces 实证真组队从未成功：
span `sp_dc3935abad` 的 `completion_tokens=1999/2000`、decision 带「输出被截断
（推理 1835 tok）」，3 条指派 span 里 2 条 response 完全为空。失败原因被
`except Exception: pass` 吞掉，兜底名单于是伪装成「指挥官选了这 6 个人」。

钉住的不变量：
- INV-E1 组队结果 ⊆ 48 人池：幻觉 id 必被丢弃，全非法时不得放行；
- INV-E3 兜底不得伪装：产出不可用/调用出错时必须带 `degraded` 原因，且留观测；
- INV-E5 团队规模契约：prompt 明写「1×L3 + 1-2×L2 + 3-6×L1」，须有代码兑现；
- INV-E6 观测不得变成新失败面：降级读数缺失时退化为安全值；
- MIG-01 约束：`degraded` 只走运行流（trace/SSE），**不得进报告 payload**。

本文件生成时**新发现的第三重根因 R3**（原计划与 brisk-pond-finch 都未覆盖，
现由 Stage A 第 6 项修掉）：
`llm._extract_json` 的兜底正则原本先试 `\\[.*\\]` 再试 `\\{.*\\}`，且 `.*` 贪婪。
只要模型在合法 JSON 外面加一句寒暄，整体解析失败后这条正则会把对象里的
`members` 数组整段抓走 → `chat_json` 返回 **list 而非 dict** →
`_dispatch_experts` 的 `isinstance(data, dict)` 不成立 → 又落回同 6 人。
它独立于截断路径：模型**没有失败**也会走这条路，根因落在
「边界类型 `Optional[Any]` 过于模糊 + 候选优先级错」。见 TC-E06a / TC-E06b。

标注约定：Stage A 已实施，本文件全部为正式断言（无 xfail 标记）。
若将来再次退化，请修实现而不是把标记加回来。

种子：test_llm_truncation_observe.py（同族「有读数必须有消费者」）、
      test_model_unavailable.py（typed error 分类）、
      test_report_read_compat.py::test_legacy_report_has_no_plan_fallback_fields（MIG-01）。
运行：backend/ 下 `pytest tests/test_expert_dispatch_degraded.py -q`
"""
import json

import pytest

import app.core.db as db
import app.core.llm as llm
import app.core.trace as trace
from app.core import orchestrator as O
from app.core.llm import LLMModelUnavailable
from app.data import load_experts

# 已知病症样本：修复前每次调研实际出镜的 6 个人（原 orchestrator.py 的字面量兜底）。
# 保留它的意义不是「当作正确答案」，而是供断言「降级结果不得等于它」。
LEGACY_FALLBACK_6 = ["L3-001", "L2-001", "L2-002", "L1-025", "L1-030", "L3-003"]

# 一份合法且**非兜底**的团队（这 6 个 id 都真实存在于 experts.json，
# 且 L1-012/L1-003/L1-004/L2-003 从未在 7 轮真实调研里出镜过 —— traces 里 LLM 实际
# 选出的就是它们）。层级配比 1×L3 + 1×L2 + 3×L1 满足 _TEAM_QUOTA，故为「健康样本」。
GOOD_TEAM = {
    "lead": "L3-001",
    "members": [
        {"id": "L3-001", "reason": "统筹"},
        {"id": "L2-003", "reason": "客群研究"},
        {"id": "L1-012", "reason": "亲子适龄"},
        {"id": "L1-003", "reason": "古镇调研"},
        {"id": "L1-004", "reason": "气候季节"},
    ],
}
GOOD_IDS = [m["id"] for m in GOOD_TEAM["members"]]


def _patch_chat_json(monkeypatch, payload, exc=None):
    """替换 orchestrator 命名空间里的 chat_json，返回调用记录。"""
    seen = {"n": 0, "kwargs": {}, "messages": None}

    def fake(messages, **kwargs):
        seen["n"] += 1
        seen["kwargs"] = kwargs
        seen["messages"] = messages
        if exc is not None:
            raise exc
        return payload

    monkeypatch.setattr(O, "chat_json", fake)
    return seen


def _patch_finish(monkeypatch, value):
    """Stage A 的判定接缝：dispatch 应读 last_finish_reason()（orchestrator 已 import）。"""
    monkeypatch.setattr(O, "last_finish_reason", lambda: value)


# ── ① 现状绿钉：组队结果必须 ⊆ 48 人池（INV-E1）────────────────
def test_tc_e04a_hallucinated_ids_are_dropped(monkeypatch):
    """LLM 混入不存在于 experts.json 的 id 时，只保留真实 id，不得放行幻觉。

    现状 `:1279` 已正确过滤 → 本钉必须真过（绿），防未来有人把校验改成宽松匹配。
    """
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, {
        "lead": "L9-999",
        "members": [
            {"id": "L9-999", "reason": "幻觉"},
            {"id": "", "reason": "空串"},
            {"id": None, "reason": "缺 id"},
            {"id": "L1-012", "reason": "真实"},
        ],
    })
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    got = [m["id"] for m in out["members"]]
    assert got == ["L1-012"], f"幻觉/空 id 混进了团队：{got}"
    assert out["lead"] in {e["id"] for e in load_experts()}, "lead 也必须落在真实池内"



# ── ② Stage A 降级三态契约 ─────────────────────────────────
def test_tc_e01_truncated_output_must_not_disguise_as_decision(monkeypatch):
    """产出不可读（截断实锤）⇒ 必须标 degraded，且不得静默返回旧兜底 6 人。

    这正是 48 位专家永远轮不到人的那一条：traces 里 finish_reason=length、
    response 为空，代码穿过 `except Exception: pass` 返回固定名单，全程无人知晓。
    """
    _patch_finish(monkeypatch, "length")
    _patch_chat_json(monkeypatch, None)
    out = O._dispatch_experts("大理 5 天亲子游", ["大理"], ["交通", "住宿"])
    got = [m["id"] for m in out["members"]]
    assert out.get("degraded"), f"降级未被标记，出镜者伪装成真组队：{got}"
    assert out["degraded"] == "llm_output_unusable"
    assert got != LEGACY_FALLBACK_6 or out["degraded"], "兜底名单必须伴随可见原因"


def test_tc_e02_typed_llm_error_must_be_classified(monkeypatch):
    """chat 抛 LLMModelUnavailable 时须分类记录为 llm_error，而非 `except Exception: pass`。

    项目已有 typed error（llm.py:23/27）与 test_model_unavailable.py 的分类测试，
    但 dispatch 这一层把它们全作废了 —— 有分类、无消费者。
    """
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, None, exc=LLMModelUnavailable("model not found"))
    out = O._dispatch_experts("成都调研", ["成都"], ["预算"])
    assert out.get("degraded") == "llm_error"
    assert out.get("degraded_reason"), "降级原因必须可追溯，不得只留一个布尔"


def test_tc_e03_healthy_team_has_no_degradation(monkeypatch):
    """正常产出必须无降级（防误报：标记失真就没人信它了，同 I2 的教训）。"""
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, GOOD_TEAM)
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    assert [m["id"] for m in out["members"]] == GOOD_IDS
    assert "degraded" in out, "契约键必须恒存在（成功路径也带 degraded=None，防下游两条读法分叉）"
    assert out["degraded"] is None


def test_tc_e04b_all_ids_invalid_must_degrade(monkeypatch):
    """LLM 返回的 id 全部非法时判降级，而不是悄悄换成硬编码名单。"""
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, {
        "lead": "L9-001",
        "members": [{"id": "L9-001", "reason": "x"}, {"id": "nope", "reason": "y"}],
    })
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    assert out.get("degraded"), "全非法被当成正常组队放行了"


def test_tc_e05b_degradation_must_leave_observability(monkeypatch):
    """降级必须留 trace span，决策回放里能看到「这次是规则兜底」。"""
    _patch_finish(monkeypatch, "length")
    _patch_chat_json(monkeypatch, None)
    trace.set_context("t_e05b", "L3-001", "orchestrator", "指派专家团队")
    try:
        O._dispatch_experts("大理", ["大理"], ["交通"])
        spans = trace.drain("t_e05b")
    finally:
        trace.clear_context()
    assert spans, "降级路径没有任何 span，回放里看不出这次没真组队"
    assert any("截断" in (s.get("decision") or "") for s in spans)


# ── ③ 畸形样本参数化（外部经验 E2）──────────────────────────────
def _wrap(payload):
    return json.dumps(payload, ensure_ascii=False)


def test_tc_e06a_prose_wrapped_object_is_misparsed_as_array():
    """R3 根因钉（纯函数层，不走管线）：带寒暄的 JSON 对象必须解析成 dict。

    曾经的行为：`_extract_json('好的，以下是结果：\\n{...}\\n希望有帮助')` 返回 **list**
    （贪婪的 `\\[.*\\]` 先命中，把对象里的 members 数组整段抓走）→
    `_dispatch_experts` 的 `isinstance(data, dict)` 落空 → 静默换成兜底 6 人。
    该路径上模型**没有失败**（无截断、无异常、答案完整），所以它独立于思考 token
    吃预算那条根因，是「48 位专家只用那几个」的第三条独立成因。

    现状：候选按起始位置排序（同起点对象优先），对象响应回到 dict。
    """
    team = {"lead": "L3-001", "members": [{"id": "L3-001", "reason": "统筹"},
                                          {"id": "L1-012", "reason": "亲子"}]}
    raw = "好的，以下是结果：\n" + json.dumps(team, ensure_ascii=False) + "\n希望有帮助"
    got = llm._extract_json(raw)
    assert isinstance(got, dict), f"容器类型错配，实际返回 {type(got).__name__}：{got}"
    assert got.get("lead") == "L3-001", "寒暄包裹的合法对象必须原样解析出来"


def test_tc_e06b_prose_wrapped_team_reaches_dispatch(monkeypatch):
    """R3 的下游后果：合法且完整的团队被丢弃，出镜者退回兜底 6 人。

    与 TC-E01 的关键区别：这里 LLM **没有**失败（无截断、无异常），纯粹是我们
    自己的解析边界把它丢了。所以本钉无法靠「加 degraded 标记」变绿，
    必须真修候选优先级（或让 chat_json 带期望容器类型）。
    """
    monkeypatch.setattr(llm, "chat", lambda messages, **kw:
                        "好的，以下是结果：\n" + json.dumps(GOOD_TEAM, ensure_ascii=False)
                        + "\n希望有帮助")
    _patch_finish(monkeypatch, "stop")   # 正常收尾：没有任何截断可以辩解
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    got = [m["id"] for m in out["members"]]
    assert got == GOOD_IDS, f"模型完整答对了却仍落回兜底：{got}"


@pytest.mark.parametrize(
    "raw, expect_members, expect_degraded",
    [
        # 多余字段：schema 外的键应被忽略且不影响组队
        (_wrap({**GOOD_TEAM, "coupon": "X"}), GOOD_IDS, None),
        # 少说话：缺 members 必填键 —— 不得用默认值兜住
        ('{"lead":"L3-001"}', None, True),
        # 类型漂移：id 是 int 而非 str —— 不得隐式转换后放行
        (_wrap({"lead": "L3-001", "members": [{"id": 1025, "reason": "类型错"}]}), None, True),
        # 非法 JSON：截断的 '{' —— 本 bug 的真实形态
        ("{", None, True),
    ],
    ids=["多余字段", "缺必填键", "类型漂移", "截断非法JSON"],
)
def test_tc_e06_malformed_samples(monkeypatch, raw, expect_members, expect_degraded):
    """契约层门禁：畸形样本的处置必须可判定，畸形不得被默认值静默填平。

    走真实 `chat_json` → `_extract_json`（只 patch 最内层 `llm.chat`），因此同时覆盖语法层。
    注意注入点必须是 `app.core.llm.chat`：`chat_json` 在其自身模块命名空间里调 `chat`，
    patch `orchestrator.chat` 不会影响它（会静默走真网络 → 落回兜底，测了个假路径）。
    「多说话」一类不在本表内 —— 它由 TC-E06a/E06b 单独钉为 R3 根因。
    """
    monkeypatch.setattr(llm, "chat", lambda messages, **kw: raw)
    _patch_finish(monkeypatch, "length" if expect_degraded else "stop")
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    got = [m["id"] for m in out["members"]]
    if expect_degraded:
        assert out["degraded"] == "llm_output_unusable", (
            f"畸形产出被静默兜底或误标：degraded={out.get('degraded')!r} members={got}")
        assert out["degraded_reason"], "降级必须带可追溯原因"
    else:
        assert got == expect_members, f"可解析的畸形样本被错误降级：{got}"
        assert out["degraded"] is None


# ── ④ 团队规模契约（INV-E5：prompt 写了但代码一行没校验）────────
@pytest.mark.parametrize(
    "bad_members",
    [
        # 0 位 L3：无决策层统筹，违反「必须含 1 位 L3」
        [{"id": "L2-003", "reason": "a"}, {"id": "L1-012", "reason": "b"}],
        # 3 位 L2：超出「1-2 位 L2 策略顾问」
        [{"id": "L3-001", "reason": "a"}, {"id": "L2-001", "reason": "b"},
         {"id": "L2-002", "reason": "c"}, {"id": "L2-003", "reason": "d"},
         {"id": "L1-012", "reason": "e"}, {"id": "L1-003", "reason": "f"},
         {"id": "L1-004", "reason": "g"}],
        # 2 位 L1：低于「3-6 位 L1 执行专家」
        [{"id": "L3-001", "reason": "a"}, {"id": "L2-001", "reason": "b"},
         {"id": "L1-012", "reason": "c"}, {"id": "L1-003", "reason": "d"}],
    ],
    ids=["无L3", "L2超编", "L1不足"],
)
def test_tc_e07_team_composition_is_enforced(monkeypatch, bad_members):
    """prompt 承诺的层级配比必须由代码兑现，违规不得原样放行。"""
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, {"lead": bad_members[0]["id"], "members": bad_members})
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    assert out.get("degraded") == "spec_violation", "配比违规被静默接受"
    assert [m["id"] for m in out["members"]] != [m["id"] for m in bad_members] or out["degraded"]


# ── ⑤ lead 归属与去重（IN-01 / INV-02）────────────────────────
def test_tc_e08_lead_must_be_a_member(monkeypatch):
    """lead 不在 members 内时须归一并留痕，而不是取 `members[0]` 或放任悬空。"""
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, {
        "lead": "L3-002",  # 真实存在于池中，但不在本次团队里
        "members": [{"id": "L3-001", "reason": "a"}, {"id": "L1-012", "reason": "b"}],
    })
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    assert out["lead"] in [m["id"] for m in out["members"]], "lead 悬空于团队之外"


def test_tc_e09_duplicate_member_ids_deduped(monkeypatch):
    """同一专家重复指派须去重且保序（否则 expert_stats 的 missions 会被虚增）。"""
    _patch_finish(monkeypatch, "stop")
    _patch_chat_json(monkeypatch, {
        "lead": "L3-001",
        "members": [{"id": "L1-012", "reason": "a"}, {"id": "L1-012", "reason": "重复"},
                    {"id": "L1-003", "reason": "c"}],
    })
    out = O._dispatch_experts("大理", ["大理"], ["交通"])
    got = [m["id"] for m in out["members"]]
    assert got == ["L1-012", "L1-003"], f"未去重：{got}"


# ── ⑥ 现状绿钉：名册必须全量进 prompt（INV-E1 的输入侧）─────────
def test_tc_e11_full_roster_reaches_prompt(monkeypatch):
    """48 位专家必须全部出现在指派 prompt 里。

    这是「只用了那几个」的第一嫌疑点（名册被切片），实测现状正确 ——
    留成绿钉，防未来有人为了省 token 给 roster 加 [:N]，那会让根因永久潜伏。
    """
    seen = _patch_chat_json(monkeypatch, GOOD_TEAM)
    _patch_finish(monkeypatch, "stop")
    O._dispatch_experts("大理", ["大理"], ["交通"])
    blob = json.dumps(seen["messages"], ensure_ascii=False)
    pool = [e["id"] for e in load_experts()]
    assert len(pool) == 48, "名册规模变了要同步本钉（前端硬编码文案另计）"
    missing = [i for i in pool if i not in blob]
    assert not missing, f"名册被截断，这些专家永远不可能被选中：{missing}"


# ── ⑦ MIG-01 约束：报告持久化边界不因降级契约而扩（现状绿钉）─────
def test_tc_e05a_report_persistence_boundary_unchanged():
    """钉住 Stage A 的实现边界：降级属于运行流，报告持久化结构不得跟着扩。

    按 `orchestrator.py:3744-3745` 的真实形状落库（`experts`= id 列表、
    `dispatch`= 成员列表），读回后必须保持该形状：
      - reports 表不得多出降级列（降级只存在于 trace 与运行中 SSE）；
      - `dispatch` 仍是列表，不是把 `_dispatch_experts` 的返回字典整个塞进来。
    与 test_report_read_compat.py::test_legacy_report_has_no_plan_fallback_fields 同源。
    """
    dispatch = {
        "lead": "L3-001",
        "members": [{"id": "L3-001", "reason": "r"}, {"id": "L1-012", "reason": "r"}],
        "degraded": "llm_output_unusable",
        "degraded_reason": "输出被截断（推理吃光预算）",
    }
    members = [m["id"] for m in dispatch["members"]]
    # 复刻编排层落库形状：只取 members，不整包塞 dispatch 返回值
    report = {
        "id": "r_e05a", "title": "T", "query": "q", "destinations": ["大理"],
        "created_at": "2026-09-22T00:00:00",
        "experts": members, "dispatch": dispatch["members"],
        "toc": [], "sections": [], "charts": [], "evidence": [], "claims": [],
        "glossary": [],
    }
    db.save_report(report)
    try:
        got = db.get_report("r_e05a")
        assert got is not None
        assert got["experts"] == members
        assert isinstance(got["dispatch"], list) and got["dispatch"][0]["id"] == "L3-001"
        assert "degraded" not in got, "报告 payload 顶层被扩了降级字段，违反 MIG-01"
        cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(reports)")}
        assert not [c for c in cols if "degrad" in c.lower()], "reports 表不得为降级加列"
    finally:
        # 本文件其它用例不依赖 reports；仍主动清掉，避免污染后续按 COUNT 聚合的用例
        db._connect().execute("DELETE FROM reports WHERE report_id='r_e05a'")
        db._connect().execute("DELETE FROM evidences WHERE report_id='r_e05a'")
        db._connect().commit()



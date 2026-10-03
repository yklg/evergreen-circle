"""片 A（#86）：measure 那两句话只报**生效规格**，不抄档位常数。

被验的真实出口 = `app/core/pipeline/living_circle.py` 的 STEP_MEASURE 事件映射
（`:331` 发起句 / `:347-358` 生效句）。规格的权威来源是 `isochrone.compute` 产出的
`iso["sampling"]["spec"]` ⇒ 本文件要么在**引擎出口处改写那几颗值**（证明文案读的是 spec 不是常数），
要么**完全不干预**、拿引擎真产的 spec 对文案（证明默认档读数没变味）。两种都在真实出口上，
测试里不重抄一份生产映射。

零真实调用：live 分支由 `PipelineStubBaidu` 顶替（驱动件从 `test_pipeline_living_circle` 复用，
与本仓既有先例同形，见 `test_degrade_chain.py:64`）。

降级那支的存在理由是 `fine_m is None` 有**两种成因**（quick 的名义加密步长==粗扫步长、
precise 被预算削平）—— 把它说成"放弃边界加密带"对 quick 是假话，而 quick 的上限恒
`2 次 × chunk 100 = 200 点 < 双阶段点数`，**任何 `baidu_max_qps` 下都走这支**（2026-10-03 纯函数
在 3.0/3.5/5.0/8.0 四档逐一验过）。
"""
import re

from app.core.pipeline.living_circle import create_living_circle_task
from app.living_circle.isochrone import IsochroneEngine

from test_pipeline_living_circle import (
    KAILI_CENTER,
    PipelineStubBaidu,
    _live_params,
    _live_source,
    _run_pipeline,
)

SPEC_PREFIX = "IDW 插值生成耗时场"
SINGLE_STAGE_KEY = "退回单阶段粗网格"
TWO_STAGE_KEY = "内加密"

# 间距数字的形状：`400m` / `62.5m`。发起句发在规格产出**之前** ⇒ 一个都不许出现（出现即谎）。
_SPACING = re.compile(r"\d+(?:\.\d+)?\s*m\b")


def _drive_measure_msgs(monkeypatch, suffix: str, profile: str = "standard", **spec_over) -> list:
    """跑一趟真实 live 分支，返回 measure 阶段的全部 message 文本（按发出顺序）。

    `spec_over` 为空 ⇒ 不碰引擎，拿它真产出的规格（默认档那条锚走这半边）。
    """
    if spec_over:
        orig = IsochroneEngine.compute

        async def _patched(self, *args, **kwargs):
            iso = await orig(self, *args, **kwargs)
            iso["sampling"]["spec"].update(spec_over)
            return iso

        monkeypatch.setattr(IsochroneEngine, "compute", _patched)
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    events = _run_pipeline(create_living_circle_task(
        _live_params(scene_name=f"凯里老街-文案A-{suffix}", sample_profile=profile)))
    return [e["data"]["text"] for e in events
            if e["type"] == "message" and e["data"].get("stage") == "measure"]


def _pair(msgs: list) -> tuple:
    """(发起句, 生效句)。

    发起句按**发出顺序**取第一条 —— 依据是结构事实：`:331` 发在取证循环之前，循环里第一类
    measure 消息才是生效规格句。⚠️ 不按文案内容认：变异对照要的就是"只换文案时只有 T1 红"，
    若按我这句新措辞的前缀去找，改文案会让五条一起 `StopIteration`（第一轮实测正是这样，
    于是"前置条件坏"被读成"判据红"）。生效句仍按前缀认，但拿 assert 兜住，让失败种类是
    一条明确的判据红而不是解释器异常。
    """
    assert msgs, "measure 阶段一条 message 都没发出去"
    spec_hits = [m for m in msgs if m.startswith(SPEC_PREFIX)]
    assert len(spec_hits) == 1, f"生效规格句应恰有一条，实测 {len(spec_hits)} 条：{msgs}"
    return msgs[0], spec_hits[0]


def test_a_t1_lead_message_carries_no_spacing_number_at_all(monkeypatch):
    """T1（否证面）：发起句在规格产生之前发出 ⇒ 间距数字一个都不能有，也不许提"加密"。

    反向对照：改回旧文案「粗扫 400m 网格 → 15min 边界带加密 → …」本条必红
    （`400m` 命中 `_SPACING`，且"加密"出现）。
    """
    lead, _ = _pair(_drive_measure_msgs(monkeypatch, "t1"))
    assert _SPACING.search(lead) is None, f"发起句替自己没算过的规格作证：{lead!r}"
    assert "加密" not in lead, f"此刻还不知道会不会加密，文案已承诺：{lead!r}"


def test_a_t2_two_stage_note_reads_the_spec_not_the_profile_constant(monkeypatch):
    """T2（双阶段支 · 同源）：生效句报出的三个数**逐字等于**我在引擎出口注入的那几颗值。

    故意用现实中不存在的数（333/111/123–456）⇒ 文案若抄档位常数（standard 的 400/150）立刻对不上。
    """
    _, spec_msg = _pair(_drive_measure_msgs(
        monkeypatch, "t2", coarse_m=333.0, fine_m=111.0, fine_band=[123.0, 456.0], degraded=False))
    assert "粗扫 333m + 边界带 123–456m 内加密 111m" in spec_msg, spec_msg
    assert "400m" not in spec_msg and "150m" not in spec_msg, f"文案仍在报档位常数：{spec_msg}"


def test_a_t3_degraded_note_reads_both_step_numbers_from_spec(monkeypatch):
    """T3（降级支 · 同源）：格距与采样间距两个数同样来自 spec，且这支**不得出现"加密"**字样。

    「放弃边界加密带」是旧写法：它对 quick 说了假话（那档从没加密带可放弃）⇒ 本条同时是
    对那句旧文案的反证（含"加密"即红）。
    """
    _, spec_msg = _pair(_drive_measure_msgs(
        monkeypatch, "t3", degraded=True, fine_m=None, fine_band=None,
        grid_step_m=88.8, sample_step_m=77.7))
    assert SINGLE_STAGE_KEY in spec_msg, spec_msg
    assert "插值格距 88.8m vs 采样间距 77.7m" in spec_msg, spec_msg
    assert "加密" not in spec_msg, f"没被放弃过的东西被说成放弃了：{spec_msg}"


def test_a_t4_quick_never_claims_a_band_it_did_not_have(monkeypatch):
    """T4（真实可达态 · 不注入）：quick 档走降级支，文案不得宣称"加密"。

    这条**完全不碰引擎** —— quick 的上限恒 200 点 < 双阶段点数，任何预算下都降级，
    所以它是"引擎自己产 degraded=True 时文案说的是什么"的现场读数，不是我造的状态。
    """
    _, spec_msg = _pair(_drive_measure_msgs(monkeypatch, "t4", profile="quick"))
    assert SINGLE_STAGE_KEY in spec_msg, spec_msg
    assert TWO_STAGE_KEY not in spec_msg, f"quick 从没加密带，却报出内加密：{spec_msg}"


def test_a_t5_default_profile_reports_the_engine_s_own_standard_reading(monkeypatch):
    """T5（默认档锚值 · 不注入）：standard 双阶段那四个数由引擎真产并逐字上屏。

    这条是"改文案没把默认路径说变味"的锚。期望值有**两处独立来源**，不是我抄的常数：
    2026-10-03 真跑存量 `lc-4402e0d0` 的 `living_circle.sampling.spec`
    （`coarse_m=400.0 / fine_m=150.0 / fine_band=[400.0,2500.0] / degraded=false`），
    以及本趟**未经任何顶替**的引擎产出。两处对齐才写死这一句。
    """
    _, spec_msg = _pair(_drive_measure_msgs(monkeypatch, "t5"))
    assert "（粗扫 400m + 边界带 400–2500m 内加密 150m）" in spec_msg, spec_msg
    assert SINGLE_STAGE_KEY not in spec_msg, f"默认档被说成预算受限：{spec_msg}"

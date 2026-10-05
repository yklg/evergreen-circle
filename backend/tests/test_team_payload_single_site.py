"""报告 payload 里 `team` 键必须只有一个构造点（批 4′ 判据，与 `_team_payload` 同笔）。"""
from pathlib import Path
def test_team_payload_has_a_single_construction_site():
    """粗报 / 缓存命中 / 精报三条路径的 `team` 必须由同一个构造点产出。

    历史形状是三处各写一份字典，其中精报那份写 `reasons: []` ⇒ 精报替换粗报后
    逐人指派理由被清空。这里钉"不许再有手写的那份字面量"，比钉行为更早暴露分叉。
    """
    src = Path(__file__).resolve().parent.parent / "app" / "core" / "pipeline" / "living_circle.py"
    text = src.read_text(encoding="utf-8")
    assert '["team"] = {' not in text, "又出现手写的 team 字典，绕过了 _team_payload()"
    assert text.count("_team_payload(") >= 4, "构造点定义 + 三处调用（粗报/命中/精报）应当齐全"


def test_team_payload_copies_its_inputs():
    """构造点不得把调用方的列表别名进报告 —— 报告落库后还要被就地注入过。"""
    from app.core.pipeline.living_circle import _team_payload

    ids, reasons = ["L3-001"], ["理由"]
    payload = _team_payload(ids, reasons)
    ids.append("L2-001")
    assert payload == {"expert_ids": ["L3-001"], "reasons": ["理由"]}

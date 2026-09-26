"""`make_claim` 置信阶梯守卫（铁律 1「无证据不立论」的可执行形式）。

背景：此前全仓**没有任何一条**测试覆盖 `app.core.models.make_claim`，而它是「论点必须
挂出处」的唯一计算入口。第二片（体检报告加厚）要把生活圈报告接上真实证据底座并逐章
撰写——阶梯本身没有守卫，等于把未验证的规则放大到每一章正文。

判据（现实现，`models.py::make_claim`）：

===================  ==========================  ==================
输入                  置信度                      cross_validated
===================  ==========================  ==================
无 evidence_ids       unverified                  False
仅 1 条证据           low                         False
≥2 条但同一信源组     medium                      False
independent_groups≥2  high                        True
===================  ==========================  ==================

**不可回退点**：high 只能由「独立信源组」触发，**不能靠堆证据条数** —— 同一事实的转载
再多也只算一组（`Evidence.source_group` 口径，替换了早先按域名近似的实现）。若哪天有人
把 `independent_groups` 改回 `len(evidence_ids)`，`test_many_evidences_in_one_group_never_reach_high`
会立刻红。
"""
from app.core.models import make_claim


def _claim(evidence_ids, independent_groups=0):
    return make_claim(
        "c-lc-medical-1",
        "医疗配置达标：圈内 100% 覆盖",
        "coverage",
        evidence_ids,
        "L3-003",
        independent_groups=independent_groups,
    )


def test_no_evidence_is_unverified_and_keeps_ids_empty():
    claim = _claim([])
    assert claim.confidence == "unverified"
    assert claim.cross_validated is False
    # 无证据时不得伪造任何 id 回填（这是「unverified」能被审计到的前提）
    assert claim.evidence_ids == []


def test_single_evidence_is_low():
    claim = _claim(["e-1"], independent_groups=1)
    assert claim.confidence == "low"
    assert claim.cross_validated is False
    assert claim.evidence_ids == ["e-1"]


def test_many_evidences_in_one_group_never_reach_high():
    """同组堆条数最多 medium —— 防转载冒充多源交叉验证。"""
    claim = _claim(["e-1", "e-2", "e-3", "e-4"], independent_groups=1)
    assert claim.confidence == "medium"
    assert claim.cross_validated is False


def test_two_independent_groups_are_high_and_cross_validated():
    claim = _claim(["e-1", "e-2"], independent_groups=2)
    assert claim.confidence == "high"
    assert claim.cross_validated is True


def test_independent_groups_alone_without_evidence_is_still_unverified():
    """证据为空时，声称「有两个独立信源」不成立 —— 空证据优先于组数。"""
    claim = _claim([], independent_groups=5)
    assert claim.confidence == "unverified"


def test_field_author_and_claim_type_survive_the_ladder():
    """加厚层的口径绑定与逐章署名依赖这三项原样透传，不能被置信度计算吞掉。"""
    claim = _claim(["e-1"])
    assert claim.field == "coverage"
    assert claim.author == "L3-003"
    assert claim.claim_type == "mixed"  # 默认值：旧数据兼容口径

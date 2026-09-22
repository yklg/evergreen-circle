"""S-B1 · 住宿价位带数值判据（N5）：_price_bounds 等价类 + coerce_stay_options 校验链。

不变量：数值只从给定文本/给定字段解析，解析不出留 None（不造数）；LLM 显式产出优先，
缺失才由 price_range 自由文本派生；产出倒挂一律否决。
运行：backend/ 下 `pytest tests/test_schemas_stay_price.py -q`
"""
import pytest

from app.core import schemas as S


@pytest.mark.parametrize("text,lo,hi", [
    ("300-500", 300, 500),               # 显式区间
    ("300~500 元/晚", 300, 500),          # 波浪号 + 单位噪声
    ("300到500", 300, 500),              # 中文连接词
    ("约800起", 800, None),               # 下限语义
    ("500以内", None, 500),              # 上限语义
    ("人均￥260", 260, 260),             # 单值 → 两端同值
    ("价格面议", None, None),             # 乱码/无数字：不造数
    ("500-300", None, None),             # 区间倒挂：判据否决
    ("", None, None), (None, None, None),
])
def test_price_bounds_equivalence_classes(text, lo, hi):
    assert S._price_bounds(text) == (lo, hi)


def test_coerce_prefers_llm_fields_and_rejects_inverted():
    raw = [{"destination": "大理", "areas": [
        {"area": "A", "price_range": "300-600 元/晚", "price_min": 320, "price_max": 580},
        {"area": "B", "price_range": "约400起"},                       # 文本派生兜底
        {"area": "C", "price_range": "免费", "price_min": 900, "price_max": 100},  # 倒挂否决
    ]}]
    out = S.coerce_stay_options(raw)[0]["areas"]
    assert (out[0]["price_min"], out[0]["price_max"]) == (320, 580), "LLM 显式产出原样保留"
    assert (out[1]["price_min"], out[1]["price_max"]) == (400, None), "缺字段按文本判据派生"
    assert (out[2]["price_min"], out[2]["price_max"]) == (None, None), "倒挂产出不得进价位带"

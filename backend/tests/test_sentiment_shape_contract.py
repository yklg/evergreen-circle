"""舆情产物单形态守卫（实施计划 §25：sentiment 写入不得出现 flat 形状）。

历史上舆情在不同引擎里至少有三种形态：报告级裸数值（`sentiment: 0.72`）、
裸数组（`[0.6, 0.3, 0.1]`）与嵌套结构。flip 后前端只认 SentimentResult 一种
嵌套形态，本测试把「单一形态」钉在三个层面：

1. **生产者契约**：analyze_sentiment 无论有样/空样都返回**同一组键**的 dict
   （空样走 _empty_result，键集不变、sample_size=0）；overall 永远是
   {pos,neu,neg} 对象——不允许空样降级成 []/0/None 逼前端判类型。
2. **装配边界静态守卫**：pipeline/research/** 内报告 dict 的 "sentiment"
   条目只许**转发变量名**（唯一来源 analyze_sentiment），不许写字面量
   （数字/数组/字符串字面量即 flat 回潮）。
   注：评论对象上的 `c["sentiment"]="pos"|"neu"|"neg"` 是逐条**标签字符串**，
   属另一层契约（评论字段，不是报告聚合），不在本规则作用域。
3. **端到端落库形态**：全 mock 管线产出的落库报告 report["sentiment"] 必须是
   含全部契约键的 dict（防止管线/读层把结构拍平）。

运行：backend/ 下 `pytest tests/test_sentiment_shape_contract.py -q`
"""
import ast
from pathlib import Path

from app.core import sentiment as sentiment_mod
from app.core.sentiment import analyze_sentiment

_RESEARCH_DIR = Path(__file__).resolve().parents[1] / "app" / "core" / "pipeline" / "research"

# SentimentResult 契约键（有样/空样同构；新增键可以，少键即红——前端按此渲染）
SENTIMENT_RESULT_KEYS = frozenset({
    "overall", "overall_count", "by_platform", "by_destination", "by_spot",
    "keywords", "timeline", "camps", "voices", "highlights", "sample_size",
})
_OVERALL_KEYS = frozenset({"pos", "neu", "neg"})


def _comments(n: int):
    return [
        {"text": f"真实评价{i}：体验很好，交通方便，值得再来" if i % 2 == 0
                else f"避坑评价{i}：排队太久，体验一般",
         "platform": "douyin", "url": f"https://example.com/c/{i}",
         "title": f"评价标题{i}"}
        for i in range(n)
    ]


def test_empty_sample_keeps_full_nested_shape():
    """无评论 ⇒ 空结构而非 flat 值：同一组键 + sample_size=0（前端零分支判型）。"""
    result = analyze_sentiment("大理", [])
    assert isinstance(result, dict)
    assert set(result.keys()) == SENTIMENT_RESULT_KEYS
    assert result["sample_size"] == 0
    assert isinstance(result["overall"], dict)
    assert set(result["overall"].keys()) == _OVERALL_KEYS
    assert isinstance(result["by_platform"], dict)
    for key in ("by_destination", "by_spot", "camps", "voices", "highlights",
                "keywords", "timeline"):
        assert isinstance(result[key], list), f"{key} 必须恒为 list（空样空表，不换类型）"


def test_nonempty_sample_keeps_same_nested_shape(monkeypatch):
    """有样 ⇒ 与空样同键集；overall 三值为 int 且和归一到 100（±2 取整容差）。"""
    # 钉死规则分类，避免用例依赖 LLM 可用性
    monkeypatch.setattr(sentiment_mod, "_llm_classify", lambda destination, comments: False)
    result = analyze_sentiment("大理", _comments(8))

    assert isinstance(result, dict)
    assert set(result.keys()) == SENTIMENT_RESULT_KEYS
    assert result["sample_size"] == 8
    assert set(result["overall"].keys()) == _OVERALL_KEYS
    assert all(isinstance(v, int) for v in result["overall"].values())
    # _normalize_pct 归一后三分比之和恒为 100（空样全 0 另由上一用例覆盖）
    assert sum(result["overall"].values()) == 100
    assert isinstance(result["by_platform"], dict)
    # 聚合绝不退化为裸数值/裸数组（flat 形态的直接判据）
    assert not isinstance(result, (int, float, list))


def _report_sentiment_entries():
    """静态扫：research 包内报告 dict 上的 "sentiment" 字面量键条目。"""
    out = []
    for p in sorted(_RESEARCH_DIR.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "sentiment":
                    out.append((p.name, key.lineno, value))
    return out


def test_report_sentiment_entries_only_forward_producer_variable():
    """装配层的 report["sentiment"] 只许转发变量（analyze_sentiment 产物），
    不许出现数字/数组/字符串等字面量——flat 形状只能从装配层混进来。"""
    bad = []
    for name, lineno, value in _report_sentiment_entries():
        if not isinstance(value, ast.Name):
            bad.append(f"{name}:{lineno} -> {ast.dump(value, annotate_fields=False)[:80]}")
    assert not bad, (
        "报告级 sentiment 必须转发 analyze_sentiment 的 dict 产物，"
        f"以下位置写成了字面量（flat 回潮）：\n  " + "\n  ".join(bad)
    )


def test_persisted_report_sentiment_is_full_nested_dict(monkeypatch):
    """端到端：落库报告的 sentiment 是含全部契约键的嵌套 dict（管线与 db 读层都不许拍平）。"""
    from test_two_type_pipeline import _install_fakes, _run_pipeline

    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline("guide")

    sentiment = report["sentiment"]
    assert isinstance(sentiment, dict), (
        f"报告级 sentiment 必须是 dict，实际 {type(sentiment).__name__}（flat 回潮）")
    assert SENTIMENT_RESULT_KEYS <= set(sentiment.keys()), (
        f"落库 sentiment 缺契约键：{sorted(SENTIMENT_RESULT_KEYS - set(sentiment.keys()))}")
    assert isinstance(sentiment["overall"], dict)

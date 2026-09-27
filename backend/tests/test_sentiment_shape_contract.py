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
4. **口径注册成对**：方法论块的舆情键（sentiment_samples/corpus/doc_kind_counts/
   low_sample）在生产端（engine）与消费端（assemble）必须成对出现，且逐项带出。
5. **阈值单一真相源（TC-20）**：样本量判据处不得出现裸数字；两个阈值常量各管一层、
   不得相等，出图侧只许引用 MIN_SPOT_SENT_SAMPLE，前端只读 low_sample。

运行：backend/ 下 `pytest tests/test_sentiment_shape_contract.py -q`
"""
import ast
from pathlib import Path

from app.core import sentiment as sentiment_mod
from app.core.sentiment import analyze_sentiment

_RESEARCH_DIR = Path(__file__).resolve().parents[1] / "app" / "core" / "pipeline" / "research"
_APP_CORE = Path(__file__).resolve().parents[1] / "app" / "core"
_SENTIMENT_PY = _APP_CORE / "sentiment.py"
_CHARTS_BUILD_PY = _RESEARCH_DIR / "charts_build.py"
# 跨端静态守卫：前端呈现层也在这次「单一阈值口径」的约束范围内
_SENTIMENT_PANEL_TSX = (_APP_CORE.parents[2] / "frontend" / "src" / "components"
                        / "VSentimentPanel.tsx")

# SentimentResult 契约键（有样/空样同构；新增键可以，少键即红——前端按此渲染）
# corpus_size / doc_kind_counts / low_sample：舆情语料的口径披露字段（词云口碑化修复步骤 4）。
# 显式加进冻结集合而非放宽成子集判断——`==` 的少键检测能力就是这个闸的价值所在。
SENTIMENT_RESULT_KEYS = frozenset({
    "overall", "overall_count", "by_platform", "by_destination", "by_spot",
    "keywords", "timeline", "camps", "voices", "highlights", "sample_size",
    "corpus_size", "doc_kind_counts", "low_sample",
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


def test_sample_gate_uses_constants_not_bare_numbers():
    """TC-20（I6）：样本量判据处不得出现裸数字 —— 阈值只能引用两个常量。

    为什么单独守这条：`MIN_SENT_SAMPLE`（全局舆情）与 `MIN_SPOT_SENT_SAMPLE`（逐景点出图门）
    是两个**不同**的口径（计划 v4/P0-3：共用一个阈值会让 expert 档逐景点云几乎全缺位）。
    散落字面量的后果不是报错，是两处悄悄长回同一个数，而 D4 的选择被静默推翻。
    """
    targets = [_SENTIMENT_PY, _CHARTS_BUILD_PY]
    bad = []
    for path in targets:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if "sample" not in seg.lower():
                continue
            operands = [node.left] + list(node.comparators)
            for operand in operands:
                if isinstance(operand, ast.Constant) and isinstance(operand.value, int):
                    bad.append(f"{path.name}:{node.lineno} 拿 {operand.value!r} 直接比样本量：{seg.strip()[:70]}")
    assert not bad, (
        "样本量判据出现裸数字（必须引用 MIN_SENT_SAMPLE / MIN_SPOT_SENT_SAMPLE）：\n  "
        + "\n  ".join(bad))


def test_sample_gate_constants_are_declared_once():
    """两个阈值各管一层：常量必须存在、互不相等，且 sentiment.py 里只定义一次。"""
    assert sentiment_mod.MIN_SENT_SAMPLE != sentiment_mod.MIN_SPOT_SENT_SAMPLE, (
        "两个阈值相等 ⇒ 计划 v4/P0-3 的分层设计已被悄悄合并回一个口径")
    src = _SENTIMENT_PY.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(_SENTIMENT_PY))
    defined = [t.id for node in tree.body if isinstance(node, ast.Assign)
               for t in node.targets if isinstance(t, ast.Name) and t.id.endswith("_SAMPLE")]
    assert defined.count("MIN_SENT_SAMPLE") == 1
    assert defined.count("MIN_SPOT_SENT_SAMPLE") == 1
    # 出图门必须真的被 charts_build 引用（否则常量只是装饰）；
    # 而全局阈值不得出现在那里 —— 用 AST 而非文本搜索：注释里提到常量名是正当的。
    referenced = _referenced_names(_CHARTS_BUILD_PY)
    assert "MIN_SPOT_SENT_SAMPLE" in referenced, "逐景点出图门没引用常量 ⇒ 阈值形同虚设"
    assert "MIN_SENT_SAMPLE" not in referenced, "全局阈值被复制到出图侧 ⇒ 第二处口径"


def _referenced_names(path: Path) -> set:
    """一个文件里出现过的名字（含 import 别名），排除注释与 docstring 的干扰。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {(a.asname or a.name) for a in node.names}
    return names


def test_frontend_sentiment_panel_reads_low_sample_flag():
    """前端呈现层同样不得自带阈值：只读后端 `low_sample`，不比较数字。"""
    src = _SENTIMENT_PANEL_TSX.read_text(encoding="utf-8")
    assert "low_sample" in src, "面板没读 low_sample ⇒ 后端降级判据在前端断链"
    import re

    bad = re.findall(r"(sample_size|review_sample|corpus_size)\s*[<>]=?\s*\d", src)
    assert not bad, f"前端自带样本量阈值（第二处口径）：{bad}"


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


# ── 口径注册：方法论块必须带舆情口径，且生产者/消费者键名成对 ──

# 冻结集合：新增口径键必须同时改生产端、消费端与本集合，三处一起动才可能过闸。
# 曾因「只改消费端」被评审判为 P0（新键恒为 0 = 注册了个寂寞）。
METHODOLOGY_SENTIMENT_KEYS = frozenset({
    "sentiment_samples", "sentiment_corpus",
    "sentiment_doc_kind_counts", "sentiment_low_sample",
})


def _sentiment_keys_written(path: Path) -> frozenset:
    """扫源码里以 `"sentiment_*":` 形式写出的键（生产端 objective_meta 与消费端 dict 字面量）。"""
    import re

    return frozenset(re.findall(r'"(sentiment_[a-z_]+)"\s*:', path.read_text(encoding="utf-8")))


def test_methodology_sentiment_keys_are_paired_producer_consumer():
    """engine（写 objective_meta）与 assemble（读 om.get）的舆情口径键必须成对。"""
    produced = _sentiment_keys_written(_RESEARCH_DIR / "engine.py")
    consumed = _sentiment_keys_written(_RESEARCH_DIR / "assemble.py")
    assert produced == METHODOLOGY_SENTIMENT_KEYS, f"生产端键集漂移：{sorted(produced)}"
    assert consumed == METHODOLOGY_SENTIMENT_KEYS, f"消费端键集漂移：{sorted(consumed)}"


def test_methodology_carries_sentiment_caliber():
    """方法论块逐项带出四个口径键（前端不显示等于没注册，此处先把后端 emit 钉住）。"""
    from app.core.pipeline.research.assemble import _build_methodology

    om = {"sentiment_samples": 7, "sentiment_corpus": 25,
          "sentiment_doc_kind_counts": {"review": 7, "flight": 3},
          "sentiment_low_sample": True}
    m = _build_methodology(om, [])
    assert m["sentiment_samples"] == 7, "口碑条数，不是检索条数"
    assert m["sentiment_corpus"] == 25
    assert m["sentiment_doc_kind_counts"] == {"review": 7, "flight": 3}
    assert m["sentiment_low_sample"] is True
    assert "可核验用户口碑" in m["note"], "口径必须在 note 里可读到，不能只躺在数值键里"
    # objective_meta 缺失（旧调用）时不得抛，且退化为 0/空而非 None 类型突变
    empty = _build_methodology(None, [])
    assert empty["sentiment_samples"] == 0 and empty["sentiment_doc_kind_counts"] == {}
    assert empty["sentiment_low_sample"] is False

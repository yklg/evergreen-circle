"""评价短语抽取（词云口碑化架构修复计划 · 步骤 3）。

## 为什么不是「词频统计」

`wordfreq.top_words` 回答的是「哪些字串出现得多」，而口碑词云要回答「这些人觉得怎么样」。
两者在真实语料上是冲突的：地名与页面 chrome 词天然高频（`大理` 309 次），评价词天然低频
（`风景如画`/`热情好客` 各 1 次）。所以任何「按出现次数取 Top N + 频次门槛」的做法，
效果都等于专门筛掉评价词、保留地名。

本模块因此换掉三件事：**判定单位**（词性/模式而非词频）、**计数口径**（文档频次而非
出现次数）、**准入门槛**（评价类 min_count=1）。

## 三条硬约束（都在 test_opinions.py 里有对应守卫）

1. **只在 token 序列上匹配，绝不对字符流跑正则。** 实测对字符流跑正则会切出
   `有美`/`到美丽`/`光秀丽`/`分美` 这类跨界碎片；以 `posseg` 词元为最小单位、
   短语=相邻词元的拼接，碎片问题在结构上不可能出现。
2. **实体硬排除，不靠黑名单堆。** `jieba.posseg` 会把地名标成成语：`攀枝花` → `i`。
   所以「i 类即评价」不成立，必须由调用方传入 `exclude_entities`（目的地名 +
   冻结景点名）做双向子串剔除。
3. **词性白名单不充分。** `出片`→`v`、`商业化`→`n`、`值得去`→`值得`+`去`、
   `人太多`→`人`+`太`+`多`、`不舒服`→`不`+`舒服`。故取「词性 ∪ 评价词表 ∪ 词元模式」
   三源合一。

## 不编造原则

- 短语一律是原文中**连续词元的原样拼接**，可在来源文本中逐字定位；不做同义归并、
  不造词表外的词形。
- 极性只认词表：命中 `POS_TOKENS` 记 pos、命中 `NEG_TOKENS` 记 neg，**其余一律 neu**。
  「古朴」「幽静」这类未被词表覆盖的形容词不猜极性 —— 词云照出，只是不着色。
- jieba 缺失时 `_cut_tagged` 返回空 ⇒ 不出词，与 `wordfreq` 的「词云缺位，不编造词」同纪律。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

try:  # 依赖缺失是边界场景（部署未 pip install）：降级为「不出词」，不抛不造词
    import jieba.posseg as _posseg

    _posseg.setLogLevel(60)  # 静音分词日志，避免污染服务 stdout
    _HAS_JIEBA = True
except ImportError:  # pragma: no cover - 取决于部署形态
    _posseg = None  # type: ignore[assignment]
    _HAS_JIEBA = False


def _cut_tagged(text: str) -> List[Tuple[str, str]]:
    """分词+词性接缝（测试可 monkeypatch 注入确定性 `(词, 词性)` 序列）。

    返回形如 `[("很","d"), ("舒服","a")]`。jieba 缺失或空文本 → 空表。
    """
    if not _HAS_JIEBA or not text:
        return []
    return [(w.word, w.flag) for w in _posseg.cut(text) if w.word.strip()]


# ── 词表 ────────────────────────────────────────────────
# 极性词表的**单一真相源**：`sentiment._rule_sentiment`（LLM 失败兜底的情感判据）与
# 本模块的评价抽取共用同一张表。历史上它是 sentiment._POS/_NEG 两份列表，
# 收敛后不再存在第二套口径。
POS_TOKENS = frozenset("""
好 强 喜欢 推荐 优秀 值得 值得去 香 爱了 性价比 流畅 丝滑 靠谱 出片 惊艳 vlog 美 舒服
不虚此行 方便 干净 安静 清静 浪漫 温暖 亲切 热情 古朴 幽静 恬静 轻松 惬意 悠闲 秀丽
清新 宜人 适宜 适合 好吃 美味 壮观 震撼 美丽 漂亮 好看 好拍 出片 值得去 自由 慢 原生态
不错 原汁原味 烟火气 人少 景美 值得再来 流连忘返
""".split())

NEG_TOKENS = frozenset("""
差 贵 卡 失望 垃圾 退 坑 难用 bug 缺点 拉胯 翻车 不值 宰客 踩坑 排队 人挤 照骗 劝退
避雷 排队久 拥挤 喧闹 嘈杂 偏僻 破旧 脏乱 商业化 敷衍 强制 捆绑 不推荐 不值 名不副实
性价比低 停车难
""".split())

# 描述性但非评价性：形态上像形容词，语义上只是客观陈述，进词云等于凑数。
# 冻结表 —— 新增必须同时补测试说明（由 validate_lexicon 的漂移守卫把守）。
DESCRIPTIVE_BLACKLIST = frozenset("""
明显 明确 所有 完整 较大 天然 敞篷 自驾游 即兴 座位数 相关 主要 重要 常见 一般 单独
直接 实际 基本 初步 官方 最新 热门 著名 有名 大型 小型 市级 省级
""".split())

# 与词性无关的评价词白名单：posseg 把它们标成 n/v，只靠词性会整批漏掉。
OPINION_LEXICON = frozenset({
    "出片", "商业化", "性价比", "踩坑", "避坑", "宰客", "照骗", "劝退", "翻车", "拉胯",
    "排队", "人挤", "人流", "拥挤", "喧闹", "烟火气", "原生态", "网红", "打卡",
    "不值", "值得去", "名不副实", "停车难", "敷衍",
})

# 词元模式用的功能词类。
# 注意：程度副词按**词面**匹配而非词性 —— jieba 把「很」在「地方很偏僻」里标成 `zg`
# （特殊状形词），只认 `d` 会整批漏掉。
_DEGREE = frozenset("很 太 非常 特别 比较 有点 挺 格外 十分 真 最 超级 巨 蛮 相当".split())
_NEGATION = frozenset("不 没 未 无 别 莫".split())
_VALVE = frozenset("值得 适合 推荐 喜欢 爱 向往 享受 期待 怀念".split())
# 轻动词：构成「值得去 / 推荐去 / 适合住」这类评价短语的后半。刻意不收「避开」「需要」
# 这类实义动词，否则 [不]+[动词] 会把「不需要理由」「不结婚」当评价（实测漏出过）。
_LIGHT_VERBS = frozenset("去 逛 玩 吃 住 拍 看 骑 走 待 行 游 赏".split())
_DEICTIC = frozenset("得 到 极了 死了 不行".split())
_ADJ_FLAGS = ("a", "ad", "an")
# 只取成语 `i`。`l`（习用语）实测混入 `合不`/`一路上`/`自然风光` 这类非评价词形，
# 地名与评价成语的混淆另由 exclude_entities 承担（见模块 docstring 约束 2）。
_IDIOM_FLAGS = ("i",)

_WORD_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·\-]{1,}$")
_MIN_PHRASE_CHARS = 2


def extract_opinions(texts: Sequence[str], *, exclude_entities: Sequence[str] = (),
                     limit: int = 30, min_count: int = 1) -> List[Dict[str, Any]]:
    """从口碑文本抽取评价短语 → `[{"word","weight","kind":"opinion","polarity"}]`。

    - `weight` = **文档频次**（该短语出现在多少篇文本里），同一文本内重复不叠加。
      用出现次数会让单篇长文灌水，也与「多少人有这个感受」的语义不符。
    - `min_count` 默认 1：评价天然低频，门槛设 2 就是专门把它们筛掉的。
    - `exclude_entities` 双向子串剔除（短语含实体 或 实体含短语）⇒ 结构性解决
      `攀枝花`（被标 `i`）、`大理古城` 这类「词性像评价、其实是地名」。
    - 排序确定性：文档频次降序 → 同频按码位序（与 wordfreq 同纪律，可复现）。
    """
    if not texts:
        return []

    df: Dict[str, int] = {}
    polarity: Dict[str, set] = {}
    ents = [e.strip() for e in exclude_entities if e and len(e.strip()) >= 2]

    for t in texts:
        per_doc: Dict[str, set] = {}
        for phrase, pol in _match_spans(_cut_tagged(t)):
            if _is_entity(phrase, ents):
                continue
            per_doc.setdefault(phrase, set()).add(pol)
        for phrase, pols in per_doc.items():
            df[phrase] = df.get(phrase, 0) + 1  # 同篇内出现多次只记一次（文档频次）
            polarity.setdefault(phrase, set()).update(pols)

    items = [(w, c) for w, c in df.items() if c >= min_count]
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    return [{"word": w, "weight": c, "kind": "opinion",
             "polarity": _resolve_polarity(polarity[w])}
            for w, c in items[:limit]]


def extract_topics(texts: Sequence[str], *, prefer_entities: Sequence[str] = (),
                   limit: int = 14) -> List[Dict[str, Any]]:
    """话题层 → `[{"word","weight","kind":"topic","polarity":"neu"}]`。

    语义是「大家在聊哪个实体」，故**只统计 `prefer_entities` 命中项，不做任何补位**：
    回落去取「高频实词」等于把 `位于`/`图片`/`机型`/`查询` 这些页面 chrome 词从后门
    请回来（`wordfreq._STOPWORDS` 只有 93 个虚词，挡不住它们）。
    `prefer_entities` 为空 ⇒ 返回空表，前端只出大字层，不留空灰区。
    """
    if not texts or not prefer_entities:
        return []
    ents = [e.strip() for e in prefer_entities if e and len(e.strip()) >= 2]
    df: Dict[str, int] = {}
    for t in texts:
        hit_here = {e for e in ents if e in t}
        for e in hit_here:
            df[e] = df.get(e, 0) + 1
    items = sorted(df.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"word": w, "weight": c, "kind": "topic", "polarity": "neu"}
            for w, c in items[:limit]]


# ── 词元模式匹配 ─────────────────────────────────────────

def _match_spans(toks: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """在词元序列上找评价短语，返回 `[(短语, 极性)]`。

    先扫多词元模式（长跨度优先并占用词元），再补未占用单词元 —— 避免
    「很舒服」与「舒服」同时产出、把同一篇的同一感受算两遍。
    """
    n = len(toks)
    used = [False] * n
    spans: List[Tuple[str, str]] = []

    def take(rng: range, phrase: str, pol: str) -> None:
        for i in rng:
            used[i] = True
        if len(phrase) >= _MIN_PHRASE_CHARS and _WORD_RE.match(phrase):
            spans.append((phrase, pol))

    for i in range(n):
        if used[i]:
            continue
        w, f = toks[i]

        # [不/没] + [程度词?] + [形容词/评价动词] → 不舒服 / 不太推荐（判 neg）
        # 头词限形容词或评价动词：否则「不需要理由」「不结婚」「不知道」这类
        # 普通否定会被当成口碑（实测漏出过）。
        if w in _NEGATION and i + 1 < n and not used[i + 1]:
            j = i + 1
            k = j + 1 if (j + 1 < n and toks[j][0] in _DEGREE) else j
            head = toks[k][0] if k < n else ""
            if k < n and (toks[k][1].startswith("a") or head in _VALVE):
                rng = range(i, k + 1)
                take(rng, "".join(toks[x][0] for x in rng), "neg")
                continue

        # [程度副词] + [形容词] → 很舒服 / 太贵
        if w in _DEGREE and i + 1 < n and toks[i + 1][1].startswith("a"):
            rng = range(i, i + 2)
            take(rng, "".join(toks[x][0] for x in rng), _polarity_of(toks[i + 1][0]))
            continue

        # [值得/适合/推荐/喜欢] + [轻动词] → 值得去 / 适合住
        if w in _VALVE and i + 1 < n and toks[i + 1][0] in _LIGHT_VERBS:
            rng = range(i, i + 2)
            take(rng, "".join(toks[x][0] for x in rng), _polarity_of(w))
            continue

        # [形容词] + [得/到/极了] + [形容词] → 美得很 / 干净得发亮
        if (toks[i][1].startswith("a") and i + 2 < n and toks[i + 1][0] in _DEICTIC
                and toks[i + 2][1].startswith("a")):
            rng = range(i, i + 3)
            take(rng, "".join(toks[x][0] for x in rng), _polarity_of(w))
            continue

        # [单字名词] + [程度词] + [形容/数量] → 人太多 / 街太吵
        # 限单字名词：多字名词会拼出「地方很偏僻」「大城市很难」这种读不通的长串，
        # 其中的评价词（偏僻/难）本就该由单词元路径单独出词。
        if (f.startswith("n") and len(w) == 1 and i + 2 < n and toks[i + 1][0] in _DEGREE
                and toks[i + 2][1][:1] in ("a", "m")):
            rng = range(i, i + 3)
            pol = "neg" if toks[i + 2][0] in ("多", "挤", "吵") else _polarity_of(toks[i + 2][0])
            take(rng, "".join(toks[x][0] for x in rng), pol)
            continue

    for i, (w, f) in enumerate(toks):
        if used[i]:
            continue
        if len(w) < _MIN_PHRASE_CHARS or not _WORD_RE.match(w):
            continue
        if w in DESCRIPTIVE_BLACKLIST:
            continue
        if f.startswith(_ADJ_FLAGS) or f.startswith(_IDIOM_FLAGS) or w in OPINION_LEXICON:
            spans.append((w, _polarity_of(w)))
    return spans


def _polarity_of(word: str) -> str:
    """极性只认词表，不猜：词表外一律 neu（词云照出，只是不着色）。"""
    if word in NEG_TOKENS:
        return "neg"
    if word in POS_TOKENS:
        return "pos"
    for t in NEG_TOKENS:
        if len(t) >= 2 and t in word:
            return "neg"
    for t in POS_TOKENS:
        if len(t) >= 2 and t in word:
            return "pos"
    return "neu"


def _resolve_polarity(seen: set) -> str:
    """由「该短语在各文档被判到的极性集合」裁决，**与文档顺序无关**。

    用集合而非折叠累加：折叠对 `merge(pos,neg)→neu` 这类规则不服从结合律，
    `[pos,neg,pos]` 与 `[pos,pos,neg]` 会折出不同结果 —— 那正是 I1 确定性要防的。
    pos 与 neg 同时出现 ⇒ 判不准，如实退回 neu。
    """
    decisive = seen & {"pos", "neg"}
    if len(decisive) == 1:
        return decisive.pop()
    return "neu"


def _is_entity(phrase: str, ents: Sequence[str]) -> bool:
    """双向子串：短语含实体（攀枝花→花…）或实体含短语（古城 ⊆ 大理古城）都算实体词。"""
    for e in ents:
        if e in phrase or phrase in e:
            return True
    return False


def validate_lexicon(expected: Dict[str, frozenset]) -> List[str]:
    """词表体检，返回**问题清单**（空表 = 通过）。仿 `caliber_index.validate_vocabulary`。

    为什么不做「死词」检查：曾计划加一条「词条在真 jieba posseg 下不落任何允许词性 ⇒ 死词」，
    实测不成立 —— 准入取决于**句内词性**而非词条本身，且词表条目还有第二种职责：
    `_polarity_of` 靠子串命中给别的短语着色（`热情好客` 由 `i` 词性准入、由 `热情` 判成 pos）。
    按「单独切词能否准入」来判，会把 39 个真正承重的词条误判成死词（实测），
    于是这条守卫要么恒红、要么把 39 项冻进测试 —— 两者都不是守卫，是噪音。故改为下面
    四条**可判定**的检查，其中第 ④ 条把「加词必须显式改测试」做实。

    ① 词形合法：**准入类**表（`OPINION_LEXICON`/`DESCRIPTIVE_BLACKLIST`）词条必须过
       `_WORD_RE` 且长度 ≥ `_MIN_PHRASE_CHARS` —— 单词元准入有 `len(w) >= 2` 硬门槛，
       往这两张表里塞单字词或塞带空格的词组等于白塞。
       `POS_TOKENS`/`NEG_TOKENS` 只查「非空且是纯字」：它们还兼作模式头与
       `_polarity_of` 的子串锚点，`好`/`贵`/`卡` 这类单字条目是真承重的，
       而 `_WORD_RE` 是为**输出短语**定的形，不该拿来管极性词表。
    ② 极性表互斥：`POS_TOKENS ∩ NEG_TOKENS` 必须为空（否则 `_polarity_of` 先查 neg，
       同词永远判负，静默偏置好评率）
    ③ 极性解析自洽：每个 POS 词条必须被 `_polarity_of` 读出 pos、NEG 读出 neg
    ④ 漂移：四张表必须逐项等于调用方冻结的期望集（新增/删除词都要显式改测试）
    """
    problems: List[str] = []
    admission_tables = {"OPINION_LEXICON": OPINION_LEXICON,
                        "DESCRIPTIVE_BLACKLIST": DESCRIPTIVE_BLACKLIST}
    polarity_tables = {"POS_TOKENS": POS_TOKENS, "NEG_TOKENS": NEG_TOKENS}
    tables = {**polarity_tables, **admission_tables}

    for name, table in admission_tables.items():
        for w in sorted(table):
            if len(w) < _MIN_PHRASE_CHARS or not _WORD_RE.match(w):
                problems.append(f"{name}: 词条 {w!r} 不可能被准入（形状或长度不合 _WORD_RE）")
    for name, table in polarity_tables.items():
        for w in sorted(table):
            if not w.strip() or any(c.isspace() for c in w):
                problems.append(f"{name}: 词条 {w!r} 含空白，不可能是词元")

    both = sorted(POS_TOKENS & NEG_TOKENS)
    if both:
        problems.append(f"POS/NEG 同词冲突（_polarity_of 会恒判 neg）：{both}")

    blacklist_hits = sorted((POS_TOKENS | NEG_TOKENS) & DESCRIPTIVE_BLACKLIST)
    if blacklist_hits:
        problems.append(f"既在极性表又在描述性黑名单，等于白加：{blacklist_hits}")

    for w in sorted(POS_TOKENS - NEG_TOKENS):
        if _polarity_of(w) != "pos":
            problems.append(f"POS 词条 {w!r} 读不出 pos（实为 {_polarity_of(w)}）")
    for w in sorted(NEG_TOKENS):
        if _polarity_of(w) != "neg":
            problems.append(f"NEG 词条 {w!r} 读不出 neg（实为 {_polarity_of(w)}）")

    for name, table in tables.items():
        want = expected.get(name)
        if want is None:
            problems.append(f"期望集缺表 {name}（新增词表必须同时在测试里冻结）")
            continue
        added, removed = sorted(table - want), sorted(want - table)
        if added:
            problems.append(f"{name} 出现未冻结的新词：{added}")
        if removed:
            problems.append(f"{name} 缺了期望中的词：{removed}")
    return problems


__all__ = ["extract_opinions", "extract_topics", "_cut_tagged", "validate_lexicon",
           "POS_TOKENS", "NEG_TOKENS", "OPINION_LEXICON", "DESCRIPTIVE_BLACKLIST"]

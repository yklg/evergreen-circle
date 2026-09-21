"""POI 类别判定规则唯一事实源（rev3 §四A / S1/S2/S8 判据）。

职责边界（架构分治）：
  - **只回答「这个 POI 属于哪一类 / 置信度多高」**（纯判表 + 判定函数），不碰预算、不发起网络。
  - `poi.py` 的 `CATEGORY_DEFS` 收敛到这里，杜绝两套判表双写。
  - 判据来源：百度 `tag`（服务属性）优先，名称作弱先验；`accept_tags/reject_tags` 做标签裁决。

5 条口径判定原则（rev3 §2.2）：按服务属性裁、名称仅作弱先验、标签冲突按 reject 优先、
高危歧义归 other、无信号保持 other（绝不伪造类别）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 置信度档位（rev3 §四A：evaluate_category 返回可解释置信度）
CONFIDENCE = {"high": 0.9, "mid": 0.6, "low": 0.3}

# 便利店口径开关（rev3 §六）：默认按「就近购」算购物；切「菜篮子优先」则 False 归降噪杂讯。
SHOPPING_INCLUDE_CONVENIENCE = True

# 8 类民生判表。键集合 = `poi.CATEGORY_DEFS` 严格一致（不再双写两套表）。
# keywords：百度 place 检索锚点（S1 语义词）；accept/reject_tags：S2/S8 标签裁决来源。
# ideal_circle：圈内理想阈值（评分基准）。
CATEGORY_RULES: Dict[str, Dict[str, Any]] = {
    "market": {
        "label": "菜市场",
        "keywords": ["菜市场", "农贸市场", "生鲜市场"],
        "accept_tags": ["菜市场", "农贸", "生鲜市场", "集贸", "便民市场", "菜篮"],
        "reject_tags": ["海鲜餐厅", "水产批发", "五金", "建材", "花卉", "夜市", "大排档"],
        "ideal_circle": 3,
    },
    "medical": {
        "label": "医疗",
        "keywords": ["社区医院", "诊所", "社区卫生服务中心"],
        "accept_tags": ["诊所", "社区卫生服务中心", "社区医院", "综合医院", "门诊"],
        "reject_tags": ["宠物医院", "牙科诊所", "医美"],
        "ideal_circle": 3,
    },
    "education": {
        "label": "教育",
        "keywords": ["小学", "中学", "幼儿园"],
        "accept_tags": ["小学", "中学", "高中", "幼儿园", "九年一贯制", "初中"],
        "reject_tags": ["驾校", "培训", "早教", "补习"],
        "ideal_circle": 3,
    },
    "shopping": {
        "label": "购物",
        "keywords": ["超市", "综合商场", "便利店", "购物中心", "市场"] if SHOPPING_INCLUDE_CONVENIENCE
        else ["超市", "综合商场", "购物中心"],
        "accept_tags": ["超市", "便利店", "商场", "购物中心", "生鲜超市", "社区超市", "百货"] + (
            ["便利店"] if SHOPPING_INCLUDE_CONVENIENCE else []
        ),
        "reject_tags": ["五金", "建材", "服装批发", "家具", "药店", "菜市场"],
        "ideal_circle": 3,
    },
    "elderly": {
        "label": "养老",
        "keywords": ["养老院", "日间照料中心"],
        "accept_tags": ["养老院", "老年公寓", "日间照料", "敬老院", "康复中心"],
        "reject_tags": ["老年大学", "广场舞", "棋牌室"],
        "ideal_circle": 1,
    },
    "finance": {
        "label": "金融",
        "keywords": ["银行"],
        "accept_tags": ["银行", "储蓄所", "信用社", "ATM"],
        "reject_tags": ["证券", "保险", "贷款", "典当"],
        "ideal_circle": 1,
    },
    "recreation": {
        "label": "文体",
        "keywords": ["公园", "健身中心", "图书馆", "书店"],
        "accept_tags": ["公园", "健身", "体育场馆", "游泳", "图书馆", "影剧院", "博物馆", "文化馆", "书店"],
        "reject_tags": ["健身餐", "儿童游艺", "桌游", "烧烤"],
        "ideal_circle": 1,
    },
    "service": {
        "label": "政务",
        "keywords": ["政务服务中心", "邮政所", "街道办事处", "派出所"],
        "accept_tags": ["政务", "街道办", "派出所", "邮政", "社区服务站", "市民中心"],
        "reject_tags": ["快递网点", "快递代收", "物业"],
        "ideal_circle": 1,
    },
}

# 盲区三要素：market 复用类目；pharmacy/primary 为三要素专用键（不在 8 类中，单独检索）。
TRIAD_RULES: Dict[str, Any] = {
    "market": "market",  # 直接引用类目 market 结果（省 1 次调用）
    "pharmacy": {"label": "药店", "keywords": ["药店"], "accept_tags": ["药店", "药房", "大药房"], "reject_tags": []},
    "primary": {"label": "小学", "keywords": ["小学"], "accept_tags": ["小学", "小学部"], "reject_tags": ["中学", "高中", "大学"]},
    # 兼容既有 TRIAD_KEYWORDS 结构（pharmacy/primary 为字符串关键词查询）
    "_triad_keywords": {"market": "菜市场", "pharmacy": "药店", "primary": "小学"},
}

# 降噪杂讯：命中即判 other，不进入任何类别统计（rev3 §四E）。
_NOISE_TAGS = ("烧烤", "夜市", "五金", "建材", "物流", "快递网点", "宠物医院")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _tag_hit(tag: str, accept: List[str], reject: List[str]) -> Tuple[bool, bool]:
    """返回 (accept_hit, reject_hit)。reject 优先于 accept（口径原则：高危歧义按拒绝裁）。"""
    t = _norm(tag)
    a_hit = any(acc and _norm(acc) in t for acc in accept) if accept else False
    r_hit = any(rej and _norm(rej) in t for rej in reject) if reject else False
    if r_hit:
        return False, True
    return a_hit, False


def evaluate_category(poi: Dict[str, Any]) -> Tuple[str, float]:
    """按 5 条口径原则判定类别与置信度。

    输入：百度归一化 POI dict（可含 name/lng/lat/tag/type；缺字段不抛）。
    返回：(category, confidence)。category 为 `CATEGORY_RULES` 键或 `'other'`。
    置信度：标签命中=high(0.9)；名称关键词仅中(0.6)；无信号=low(0.3)。
    """
    if not isinstance(poi, dict) or not poi.get("name"):
        return "other", CONFIDENCE["low"]

    tag = _norm(poi.get("tag", "") or "")
    typ = _norm(poi.get("type", "") or "")
    name = _norm(poi.get("name", ""))

    # 降噪优先：命中杂讯 → 直接 other（低置信），不入类别。
    if any(no == tag for no in _NOISE_TAGS) or tag in _NOISE_TAGS:
        return "other", CONFIDENCE["low"]

    # 第一遍：标签裁决（服务属性优先）。reject 命中直接排除该类别。
    best: Tuple[str, float] = ("other", CONFIDENCE["low"])
    best_name_hit: str = ""
    for key, defn in CATEGORY_RULES.items():
        a_hit, r_hit = _tag_hit(tag or typ, defn["accept_tags"], defn["reject_tags"])
        if r_hit:
            continue
        if a_hit:
            return key, CONFIDENCE["high"]
        # 名称弱先验：仅作 mid，不覆盖标签命中。
        if any(_norm(kw) in name for kw in defn["keywords"]):
            best = (key, CONFIDENCE["mid"])
            best_name_hit = key
    # 名称命中落在多类（模糊）→ 归 other，避免以名称拍脑袋（口径原则：名称仅弱先验）。
    if best_name_hit:
        return best
    return "other", CONFIDENCE["low"]
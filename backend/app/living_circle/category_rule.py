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

from app.living_circle.facility_rule import norm_name

# 置信度档位（rev3 §四A：evaluate_category 返回可解释置信度）
CONFIDENCE = {"high": 0.9, "mid": 0.6, "low": 0.3}

# 便利店口径开关（rev3 §六）：默认按「就近购」算购物；切「菜篮子优先」则 False 归降噪杂讯。
SHOPPING_INCLUDE_CONVENIENCE = True

# 8 类民生判表。键集合 = `poi.CATEGORY_DEFS` 严格一致（不再双写两套表）。
# keywords：百度 place 检索锚点（S1 语义词）；accept/reject_tags：S2/S8 标签裁决来源。
# ideal_circle：覆盖度的**满分线**（拿到 100% 需要几处），**不是及格线**。
# ⚠️ 这同一个数兼任三件事，改它会**同时**改掉另外两件（10-01 差点在这里翻车）：
#   ① 评分分母（`poi.coverage_from_points`：分子 ÷ 它，封顶 1.0）；
#   ② 采集扩词的**收手条件**（`poi_collector.under_target`：圈内够了就不再扩词 ⇒ 外呼次数、图上点位数、
#      以及盲区判定的输入都会跟着变）；
#   ③ 报告正文那句「相当于圈内基层医疗 ≥3 家」里的 3（`diagnosis_templates.py` 直接读它）。
#      ⚠️ 满分线**不在报告 payload 里**（`poi.py:74` 那句是喂内部 `CATEGORY_DEFS` 的，不是交出去
#      的字段；类别统计只有 `total/in_circle/required_in_circle/coverage`）⇒ 前端组件印不出「÷ 3」，
#      要印就得先加字段（10-01 片 1c-β 已核过，别照着这条注释去 payload 里找）。
# ⚠️ "圈里有 1 所小学就算及格"这类诉求属**及格线**，不许就地改这个数：系统里"缺口/盲区"是**网格级**的
#   （`blindspot.py` 按 1km 内有无设施硬判），**没有任何地方按数量宣判某类缺失** ⇒ 改成 1 不会让谁
#   "不再是缺口"，只会让教育**查到 1 颗就停止扩词**（少采）并把旧载荷的教育覆盖度重读成"1 颗即满分"。
#   要加及格线就新加一根只给文案与达标判据用的线，见计划 §十九。
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
        # 10-03 甲（#87）补进两颗**社区级命名**词 —— 出处逐颗注明，不塞没实测过的词：
        #   「养老服务驿站」：北京真跑 1km 圆盘内 5 颗（332/745/850/869/980 m），返回名清一色
        #       「××社区养老服务驿站」（计划 87 §1；这是北京基层养老的官方命名，现役两词一颗都打不到）；
        #   「养老服务中心」：同批 2 颗（869/986 m）。
        # ⚠️ 这份 `keywords` **同时**是 ① 百度检索锚点 ② `evaluate_category` 的名称弱先验判词
        #   （`category_rule.py:24` 那行原话），加一颗词=两件事一起发生：多一次外呼 **且** 多一个判词。
        #   采集路径按**召回词**归类、不按判表复核（`poi_collector.py:682-691`），所以检索回来的名字
        #   不经判定直接进该类的分子 ⇒ 往这里塞一个没实测过的词，等于让百度返回什么就信什么。
        # ⚠️ 名称通道只在**标签通道谁都没命中**时才走到：若百度的 `tag` 含「社区服务站」，
        #   `service` 先赢（0.9），这两颗词救不了它（#87 的乙档，未做）。
        "keywords": ["养老院", "日间照料中心", "养老服务驿站", "养老服务中心"],
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

# 子类表（计划 §二 W1；10-01 拍板档）。**键 = 8 类里建了表的类别**，未列出的类别本批不建表
# ⇒ 覆盖度分子对它们退回点数（`poi.coverage_from_points` 那一支，判据 T17 半边乙）。
# 形状与 `CATEGORY_RULES` 同构，因此子类判定**复用同一个 `evaluate_category(table=…)` 注入口**，
# 零新实现（`test_judge_single_implementation.py:85` 守这条）。
#
# `required` = 门槛项（进覆盖度分子）。出处逐行注明（§二 两层档位 + §11.4 新核到的国标原文）：
#   · 教育 `primary`：本项目自定口径（"缺失即构成配置缺口"），国标 TD/T 1062 表 A.1 小学
#     服务半径 500m、应独立占地 —— **注意同一张表把幼儿园也列进"基础保障型"**，故 `required`
#     不能写成"依国标基础保障型推定"，只能自定（§11.4 结论 2）。
#   · 医疗 `community_health_center` / `health_service_station`：TD/T 1062 表 A.1「卫生服务中心
#     （社区医院）… 各街道（镇）设一处」+ 表 A.3「卫生服务站 500m 设置一处，不小于 120 ㎡」
#     ⇒ 10-01 据此把"站"从存疑改算门槛（推翻 09-30 甲档的一半）。
#   · 医疗 `pharmacy`：商务部〔2021〕247 号「基本保障类业态」清单里**确有"药店"** ⇒ 可引。
#   · `clinic` **不算**：TD/T 1062 全篇"诊所"出现 **0 次**，国标从未把它列为配置要素。
#   · 存疑形状（口腔/中医馆/医美/视光/名医工作室…）**不建行** ⇒ 落 `evaluate_category` 的
#     `other`（第三档＝待定），照 §二「禁止把存疑项并进已定档行冒充」。
#
# 纪律：每个类别内各行的 `accept_tags` **必须两两不相交**（标签通道取第一个命中 ⇒ 相交就让
# 字典顺序参与裁决）；判据 = `test_subkind_caliber.py` 的 J14a（故意相交表当场翻判）+ J14b。
SUB_KIND_TABLE: Dict[str, Dict[str, Dict[str, Any]]] = {
    "education": {
        "primary": {
            "label": "小学", "required": True, "weight": 500.0,
            "keywords": ["小学"], "accept_tags": ["小学", "小学部"],
            "reject_tags": ["家长学校", "中学", "高中", "大学", "职业"],
        },
        "kindergarten": {
            "label": "幼儿园", "required": False, "weight": 300.0,
            "keywords": ["幼儿园", "托儿所", "学前"], "accept_tags": ["幼儿园", "托儿所"],
            "reject_tags": ["集团", "总园", "分校", "家长学校"],
        },
        "secondary": {
            "label": "中学", "required": False, "weight": 1000.0,
            "keywords": ["中学", "初中", "高中", "九年一贯制"],
            "accept_tags": ["中学", "初中", "高中", "九年一贯制"],
            "reject_tags": ["职业", "技校", "家长学校"],
        },
    },
    "medical": {
        "community_health_center": {
            "label": "社区卫生服务中心", "required": True, "weight": 1000.0,
            "keywords": ["社区卫生服务中心"], "accept_tags": ["社区卫生服务中心"],
            "reject_tags": ["服务站"],
        },
        "health_service_station": {
            "label": "社区卫生服务站", "required": True, "weight": 300.0,
            "keywords": ["社区卫生服务站", "卫生服务站"],
            "accept_tags": ["社区卫生服务站", "卫生服务站"], "reject_tags": [],
        },
        "pharmacy": {
            "label": "药店", "required": True, "weight": 300.0,
            "keywords": ["药店", "药房", "大药房"], "accept_tags": ["药店", "药房"],
            "reject_tags": ["医院"],
        },
        "clinic": {
            "label": "诊所", "required": False, "weight": 300.0,
            "keywords": ["诊所"], "accept_tags": ["诊所"],
            "reject_tags": ["宠物医院", "牙科诊所", "医美"],
        },
        "hospital": {
            "label": "医院", "required": False, "weight": 1000.0,
            "keywords": ["医院", "卫生院"], "accept_tags": ["综合医院", "专科医院", "卫生院"],
            "reject_tags": ["宠物医院", "社区卫生服务中心"],
        },
    },
}


def sub_kind_rule_labels(category: str) -> Optional[Tuple[List[str], List[str]]]:
    """门槛项**名单**（计分组 / 不计分组）—— 只读 `SUB_KIND_TABLE`，**一个点位都不看**。

    给展示侧那一句用：「医疗 · 覆盖度只数「社区卫生服务中心 / 服务站 / 药店」…（诊所、医院不计入分子）」。
    它与 `required_count_from_points` 读同一张表，但**不是第二份判类实现** —— 判类（这颗点算哪个子类）
    全仓只有 `evaluate_category` 一处，本函数连点位都不接。

    返回 ``None`` = 这一类没建子类表 ⇒ 没有门槛项名单可言（展示侧**不得**印成空名单，
    与 `required_in_circle` 的 `None` 同一套三档语义）。

    ⚠️ 名单是**规则名单**，不是"这批圈内采到了哪些"：凯里圈内 25 处医疗点的实测分账是
    诊所 16 / 中心 2 / 站 3 / 存疑 4 ⇒ `pharmacy` 圈内 **0 颗**。若改成 present-only，
    "药店"会从披露里消失（而药店正是盲区三要素之一）—— 那是为了措辞好看而说假话。
    """
    table = SUB_KIND_TABLE.get(category)
    if table is None:
        return None
    hit = [str(d["label"]) for d in table.values() if d.get("required")]
    miss = [str(d["label"]) for d in table.values() if not d.get("required")]
    return hit, miss

# 覆盖度口径版本键（§六 四步先例的第一步：常量 → 缓存键 → 载荷 → 口径索引）。
# **独立命名、不顺着 `ev-*` 排** —— 证据域那把键没变，变的是分子定义。
COVERAGE_CALIBER_VERSION = "cov-1"


# 降噪杂讯：命中即判 other，不进入任何类别统计（rev3 §四E）。
_NOISE_TAGS = ("烧烤", "夜市", "五金", "建材", "物流", "快递网点", "宠物医院")


def sub_kind_of(poi: Dict[str, Any], category: str) -> Optional[str]:
    """该点位的子类键；类别没建表 ⇒ None（覆盖度那一支据此退回点数口径）。

    ⚠️ 这不是第二份判类实现 —— 内部只有 `evaluate_category(poi, table=SUB_KIND_TABLE[cat])`
    一行，判据仍走唯一那一份（`test_judge_single_implementation.py:85`）。
    ⚠️ 传进来的 `poi["name"]` **必须是 `annotate_name` 加工之前的原始名**（§二 规范句）：
    被吸收子点拼进父名的「· 含大药房」一类后缀一旦参与，父点子类会被子点决定。
    """
    table = SUB_KIND_TABLE.get(category)
    if not table:
        return None
    return evaluate_category(poi, table=table)[0]




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


def evaluate_category(
    poi: Dict[str, Any], table: Dict[str, Dict[str, Any]] = None
) -> Tuple[str, float]:
    """按 5 条口径原则判定类别与置信度。

    输入：百度归一化 POI dict（可含 name/lng/lat/tag/type；缺字段不抛）。
    `table` 判表**可注入**（默认 = `CATEGORY_RULES`）：这是"换一张表判类"的唯一入口，
    探针与测试都走它 —— 判据只允许一份实现，复刻一份同序版就是双写（会漂移）。
    返回：(category, confidence)。category 为判表键或 `'other'`。
    置信度：标签命中=high(0.9)；名称关键词仅中(0.6)；无信号=low(0.3)。
    """
    rules = CATEGORY_RULES if table is None else table
    if not isinstance(poi, dict) or not poi.get("name"):
        return "other", CONFIDENCE["low"]

    tag = _norm(poi.get("tag", "") or "")
    typ = _norm(poi.get("type", "") or "")
    # 名称弱先验吃 `norm_name`（剥括号）而非只并空白的 `_norm`：括号里是**分店名/限定语**，
    # 吃原始名等于让「博南口腔(拉薇公园店)」靠括号里的「公园」判成休闲 —— 跨类关键词注入。
    # 归一必须是管线共用的那一份，判类自己再造一套就会与显示/实体归并漂移。
    name = norm_name(poi.get("name", ""))

    # 降噪优先：命中杂讯 → 直接 other（低置信），不入类别。
    if any(no == tag for no in _NOISE_TAGS) or tag in _NOISE_TAGS:
        return "other", CONFIDENCE["low"]

    # 第一遍：标签裁决（服务属性优先）。reject 命中直接排除该类别。
    name_hits: List[str] = []
    for key, defn in rules.items():
        a_hit, r_hit = _tag_hit(tag or typ, defn["accept_tags"], defn["reject_tags"])
        if r_hit:
            continue
        if a_hit:
            return key, CONFIDENCE["high"]
        # 名称弱先验：仅作 mid，不覆盖标签命中。
        # 第十八轮 P0-4 / 第十九轮拍板 ①：**名称通道同样吃 `reject_tags`**（table 驱动 ⇒ 子类表
        # 注入后自动获得同一能力，零新实现）。代价已写在计划 §二：这条同时改变 8 个大类的名称判定
        # 行为，不是"只影响子类层"；10-01 只读探针实测改判面 = 502 颗真点位里 1 颗
        # （`凯峰建材大市场` `shopping→other`），另在合成样本上确实存在（`菜市场` `other→market`）。
        # 不写这条会怎样：`sub_kinds` 里 `primary.reject_tags=["家长学校"]` 拦不住
        # 「凯里市第十三小学家长学校」——它照样靠"小学"被判成小学 ⇒ 门槛项白加一 ⇒ 覆盖度假了。
        if any(_norm(kw) in name for kw in defn["keywords"]) and not any(
                _norm(r) in name for r in defn["reject_tags"]):
            name_hits.append(key)
    # 名称命中落在多类（模糊）→ 归 other，避免以名称拍脑袋（口径原则：名称仅弱先验）。
    # 这里必须**计数**而不是「留最后一个」：单变量覆盖会让判定随判表的书写次序漂移，
    # 而次序是文件里的排版细节，不是口径。
    if len(name_hits) == 1:
        return name_hits[0], CONFIDENCE["mid"]
    if len(name_hits) > 1:
        return "other", CONFIDENCE["low"]
    return "other", CONFIDENCE["low"]
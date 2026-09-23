"""调研类型契约（单一真相源）：章节 / 搜索角度 / 分析 Schema / 澄清问卷 / 视角。

设计约束（务必保持）：
- **叶子模块**：仅依赖标准库，禁止 import app.core.*。orchestrator / audit / schemas /
  main 全部单向导入本模块，从根上杜绝「放 orchestrator 则 audit 反向 import」的循环依赖。
- **数据驱动**：各阶段遍历本注册表（spec["charts"] / spec["structured_keys"] ...）而不是
  写 `if rtype == "guide"` 分支；新增第 3 个调研类型 = 在 RESEARCH_TYPES 加一条记录，
  9 个阶段自动生效。漏键由 test_research_types.py 的泛型断言在 CI 拦下。
- 规模类配置（搜索量/篇幅/返工轮次/景点 TopN）仍留在 orchestrator.MODE_CONFIG；本模块只管**语义**。
- 攻略章节的信息密度硬约束由 orchestrator 按 rtype 注入，不写进共享 SECTION_PROMPTS，
  避免波及 assessment 类型。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── 类型注册表 ────────────────────────────────────────────────
DEFAULT_RESEARCH_TYPE = "guide"
DEFAULT_MODE = "deep"
MODES: Tuple[str, ...] = ("quick", "deep", "expert")

# 报告章节基础标题（id → 无序号标题）；只含新章节，不留 legacy。
# 序号由 numbered_titles() 按类型白名单动态生成。
SECTION_PLAN: Dict[str, str] = {
    # 两类型共用
    "summary": "执行摘要 · 核心判断",
    "conclusion": "结论与行动建议",
    "risk": "风险提示与不确定性",
    "contrarian": "反共识洞察 · 敢下判断",
    "trend": "发展轨迹与趋势研判",
    # 游玩攻略（deep 9 章骨架 + expert 收尾；route 章 D2 起 deep 也出）
    "spots": "景点分布调研 · Top榜与位置分布",
    "food": "美食清单 · Top榜",
    "sentiment_report": "全网舆情 · 逐景点口碑与词云",
    "transport": "交通与抵达 · 逐景点实际路线",
    "shops": "美食商铺调研 · 价格与路线",
    "budget": "预算拆解",
    "stay": "住宿区域与选型",
    "season": "最佳季节与气候",
    "route": "一页视图 · 逐日行程组装",
    "tips": "避坑指南",
    # 调研评估
    "accessibility": "可达性评估",
    "amenities": "配套完善度",
    "safety": "安全与风险",
    "value": "性价比与成本",
    "livelihood": "生活成本与落地体验",
    "verdict": "综合研判",
    # 视角专属板块（按类型各一套，按问卷答案择一插入）
    "persp_family": "亲子视角 · 带娃出行专版",
    "persp_couple": "情侣视角 · 双人出行专版",
    "persp_solo": "独行视角 · 单人出行专版",
    "persp_photo": "摄影视角 · 出片机位专版",
    "persp_senior": "长辈视角 · 舒适慢游专版",
    "persp_live": "自住长居视角 · 落地生活专版",
    "persp_invest": "置业投资视角 · 价值研判专版",
    "persp_study": "求学陪读视角 · 教育配套专版",
    "persp_retire": "养老避寒视角 · 长期宜居专版",
    "persp_remote": "数字游民视角 · 远程办公专版",
}

SECTION_PROMPTS: Dict[str, str] = {
    "summary": "全局执行摘要，给出最核心的 3-4 条判断，要求结论先行、观点锐利，让读者 30 秒抓住全貌。",
    "conclusion": "给决策者的明确行动建议，分优先级排序（高/中/低），要敢拍板、有具体动作，不要空泛的套话。",
    "risk": "本报告结论的风险提示与不确定性，说明结论可能在哪些条件下失效、有哪些未知因素。",
    "contrarian": "反共识洞察：提出 2-3 个与主流宣传相反、但有证据支撑的大胆判断，敢于下结论，解释为什么大多数人看错了。",
    "trend": "发展轨迹与趋势研判：基于历史数据与当前信号，预判目的地未来 1-3 年的走向与关键变量。",
    # 游玩攻略：数据实体（榜单/路线/舆情统计）由系统结构化产出并随章节注入，
    # 正文只做榜单解释不了的评注，禁止复述表格内容、禁止自造实体名与数字。
    "spots": "景点分布调研：Top 景点榜单表与位置分布由系统结构化产出（勿重复罗列榜单行），"
             "只写榜单解释不了的内容：这批景点为什么在抖音/小红书热度最高、区域分布对行程安排的意义、"
             "谁被高估谁被低估。提及景点必须使用注入榜单中的原文名，不得新增或改写景点名。",
    "food": "美食清单：Top 美食榜单由系统结构化产出（勿重复罗列），逐条写清正确吃法、"
            "排队与踩坑点、本地人习惯；不得虚构榜单之外的菜品。",
    "sentiment_report": "全网舆情：逐景点声量、好评率、词云高频词等统计由系统结构化产出（勿复述数字），"
                        "只写跨景点对比判断：谁口碑最稳、谁声量虚高、哪些高频词暴露真实风险。"
                        "只引用统计产物与改写式口碑，禁止引用评论原句、禁止自造占比数字。",
    "transport": "交通与抵达：先给抵达方案结论（航班/高铁/自驾的费用与耗时对比，一行一条）；"
                 "逐景点地铁/公交/打车路线由系统结构化产出（勿复述换乘明细），"
                 "只点评衔接风险、耗时陷阱与更优走法。",
    "shops": "美食商铺调研：商铺名称、地址、参考价由系统结构化产出（勿重复罗列），"
             "点评人均价与排队情况的可信度、最值得去的是哪家；参考价缺失写「待核验」，不得编造价格。",
    "stay": "住宿区域与选型：各住宿区域的位置优劣、价格区间、适合人群、周边配套与真实踩坑点，给出「住哪个区域 + 住什么类型」的明确建议。",
    "route": "一页视图 · 逐日行程组装：基于系统注入的景点/商铺实体与路线数据，按天数给出可执行的逐日安排"
             "（景点、交通方式、停留时长、衔接要点），避免赶场与走回头路；不得引入榜单之外的新景点。",
    "budget": "预算拆解：按交通/住宿/餐饮/门票/购物分类给出人均花费区间与占比，说明不同档位的取舍，并提示可变成本与省钱空间。",
    "season": "最佳季节与气候：逐月气候与客流特征、旺季淡季差异、需要避开的时段，给出最佳出行窗口与备选方案。",
    "tips": "避坑指南：整理高频踩坑场景（宰客、低价团、黄牛、假特产、天气突变等）与可直接执行的应对方法，一行一条。",
    # 调研评估
    "accessibility": "可达性评估：从主要出发地到目的地的交通方式、耗时、费用与班次频次，以及市内通勤便利度，量化打分并给出结论。",
    "amenities": "配套完善度：医疗、教育、商业、政务、网络等生活配套的覆盖情况与缺口，逐项给出覆盖程度判断。",
    "safety": "安全与风险：治安、自然灾害（台风/地震/洪涝）、医疗应急等风险维度，逐项评估风险等级并给出防范建议。",
    "value": "性价比与成本：把居住/生活成本与可获得的配套、环境、机会做对照，判断「值不值」，给出成本结构与省钱空间。",
    "livelihood": "生活成本与落地体验：房租/物价/通勤/日常消费的真实水平，结合真实居住者反馈，描述落地后的日常体验与适应难点。",
    "verdict": "综合研判：给出明确结论与排序，说明「更适合谁、不适合谁」，敢于下判断并交代依据。",
    # 视角专属板块
    "persp_family": "以亲子视角输出：带娃出行的节奏安排、亲子友好景点与住宿、母婴设施与应急医疗、饮食与安全注意事项，给出可执行的亲子专属建议。",
    "persp_couple": "以情侣/夫妻视角输出：双人出行的浪漫体验点、私密性与舒适度、拍照出片场景、预算分配与行程节奏建议。",
    "persp_solo": "以独行视角输出：单人出行的安全注意、性价比住宿与拼车/公共交通方案、社交与结伴机会、独行友好的体验清单。",
    "persp_photo": "以摄影视角输出：最佳机位与光线时段、季节与天气窗口、器材与取景建议、避开人流的拍摄策略。",
    "persp_senior": "以长辈视角输出：慢节奏行程、体力与休息安排、无障碍与适老设施、医疗可达性与饮食适配建议。",
    "persp_live": "以自住长居视角输出：租房/购房的真实难度、社区氛围、日常采买与通勤、社交与融入成本，给出「落地长住」的可执行建议。",
    "persp_invest": "以置业投资视角输出：区域价格与租售比、政策与限购、供需与流动性、持有成本与退出难度，给出价值研判与风险提示。",
    "persp_study": "以求学陪读视角输出：学校分布与入学门槛、课业与升学路径、陪读生活成本与安全，给出陪读家庭的可执行建议。",
    "persp_retire": "以养老避寒视角输出：气候与医疗资源、慢病就医便利度、生活成本与适老配套、居住安全，给出长期宜居建议。",
    "persp_remote": "以数字游民视角输出：网络与共享办公、签证/居留与税务、生活成本与社群、时区与通勤，给出远程办公落地的可执行建议。",
}

# 章节 → (claim 字段, 图表类型)。合并原 _write_single_section.field_map、
# _assemble_report.sec_meta 与 audit 的字段关键词表，消除三表漂移隐患。
# 攻略数据型章节只引用既有 claim 词表；榜单/路线等结构化实体经 SECTION_STRUCTURED
# 单独挂载，不新增 claim 字段，避免波及 audit 覆盖度判定。
SECTION_FIELDS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    # 共用
    "summary": (("overview", "verdict"), ("radar", "donut", "trend")),
    "conclusion": (("overview", "verdict", "budget", "risk"), ()),
    "risk": (("risk",), ()),
    "contrarian": (("overview", "verdict", "trend"), ()),
    "trend": (("trend",), ("trend",)),
    # 游玩攻略
    "spots": (("overview", "verdict"), ()),
    "food": (("food",), ()),
    "sentiment_report": (("sentiment",), ("sentiment_donut", "platform_bar", "wordcloud")),
    "transport": (("transport",), ()),
    "shops": (("food", "budget"), ()),
    "budget": (("budget", "cost_breakdown"), ("cost_bar", "cost_compose")),
    "stay": (("stay", "stay_options"), ()),
    "season": (("season",), ("season_heat",)),
    "route": (("route", "route_plan"), ()),
    "tips": (("tips", "risk"), ()),
    # 调研评估
    "accessibility": (("accessibility", "access_matrix"), ()),
    "amenities": (("amenities", "amenity_checklist"), ()),
    "safety": (("safety", "risk_profile"), ()),
    "value": (("value", "budget"), ("cost_bar",)),
    "livelihood": (("livelihood",), ()),
    "verdict": (("verdict",), ("radar",)),
    # 视角
    "persp_family": (("overview", "stay", "tips"), ()),
    "persp_couple": (("overview", "stay", "route"), ()),
    "persp_solo": (("overview", "stay", "transport"), ()),
    "persp_photo": (("overview", "route", "season"), ()),
    "persp_senior": (("overview", "transport", "stay"), ()),
    "persp_live": (("livelihood", "overview", "verdict"), ()),
    "persp_invest": (("verdict", "trend", "overview"), ()),
    "persp_study": (("amenities", "overview", "safety"), ()),
    "persp_retire": (("livelihood", "safety", "overview"), ()),
    "persp_remote": (("livelihood", "value", "overview"), ()),
}

# claim 字段 → focus 维度关键词（audit 判定「某维度是否被覆盖」用）。
FIELD_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "overview": ("综合", "全貌", "整体", "格局"),
    "trend": ("趋势", "发展", "增长"),
    "risk": ("风险", "不确定", "安全"),
    "sentiment": ("口碑", "舆情", "评价"),
    "transport": ("交通", "抵达", "航班", "高铁", "车程", "通达"),
    "stay": ("住宿", "酒店", "民宿", "住哪"),
    "route": ("路线", "行程", "天数", "日程", "安排"),
    "food": ("美食", "餐饮", "吃"),
    "budget": ("预算", "花费", "费用", "价格", "成本", "性价比"),
    "season": ("季节", "气候", "天气", "淡旺"),
    "tips": ("避坑", "注意", "贴士", "防宰"),
    "accessibility": ("可达", "交通", "距离", "通勤"),
    "amenities": ("配套", "设施", "医疗", "教育", "商业"),
    "safety": ("安全", "治安", "灾害", "应急"),
    "value": ("性价比", "成本", "价格", "花费"),
    "livelihood": ("生活成本", "物价", "房租", "落地", "日常"),
    "verdict": ("综合", "结论", "判断", "研判"),
}

# 结构化键 → claim 字段（_analyze_structured 产出的对象也允许作为 claim.field 挂载）
STRUCTURED_FIELDS: Tuple[str, ...] = (
    "route_plan", "stay_options", "cost_breakdown",
    "access_matrix", "amenity_checklist", "risk_profile",
    "spot_ranking", "spot_routes", "food_ranking", "shop_list",
)

# 章节 id → 该章挂载的结构化键（渲染与审计的单一映射，防散落双定义）。
# 注意：地图不是图表——坐标/区域是 spot_ranking 的行字段，前端地图组件读结构化数据。
SECTION_STRUCTURED: Dict[str, Tuple[str, ...]] = {
    "spots": ("spot_ranking",),
    "food": ("food_ranking",),
    "transport": ("spot_routes",),
    "shops": ("shop_list",),
    "stay": ("stay_options",),
    "budget": ("cost_breakdown",),
    "route": ("route_plan",),
    "accessibility": ("access_matrix",),
    "amenities": ("amenity_checklist",),
    "safety": ("risk_profile",),
}

# 图表类型白名单（charts.py 能力面 ∩ 本模块使用面）
CHART_TYPES: Tuple[str, ...] = (
    "radar", "cost_bar", "cost_compose", "season_heat", "donut",
    "trend", "sentiment_donut", "platform_bar", "wordcloud",
)

# 已废弃的旧契约字段（防回潮：不得出现在任何类型的产出里）
DEPRECATED_CLAIM_FIELDS: Tuple[str, ...] = (
    "feature_tree", "pricing_model", "user_persona", "swot",
)

# 只在「有多个目的地可比」时才成立的产出项。目的地数量 N=1 时由
# analysis_keys_for() / charts_for() 整体剔除——单对象没有份额、没有对比对象。
# 新增此类产出只需往这两个元组里加一项，编排层无需写分支。
MULTI_ONLY_ANALYSIS_KEYS: Tuple[str, ...] = ("share_estimate",)
MULTI_ONLY_CHARTS: Tuple[str, ...] = ("donut",)

# 与上表对称：只在「单一目的地」时才成立的产出项，N≥2 时由 charts_for() 剔除
# （多目的地要看的是城市之间的档位对比，不是同城花费构成）。
SOLO_ONLY_CHARTS: Tuple[str, ...] = ("cost_compose",)

# 以目的地为**行主键**的产出登记：「点分键路径 → 行主键字段」。
# 编排层据此在装配前统一剔除不属于本次调研目的地的行（analysis 行主键 ⊆ destinations），
# 新增一类按目的地分行的产出只需往这里加一行，编排层无需写分支。
# 路径首段是 analysis 的键；`structured.` 前缀指向结构化分组（组级主键即 destination）。
DEST_KEYED_ROWS: Tuple[Tuple[str, str], ...] = (
    ("comparison.scores", "destination"),
    ("livability.scores", "destination"),
    ("budget", "destination"),
    ("cost", "destination"),
    ("safety_index", "destination"),
    ("season.matrix", "destination"),
    ("share_estimate", "name"),
    ("trends.series", "name"),
    ("structured.spot_ranking", "destination"),
    ("structured.food_ranking", "destination"),
    ("structured.spot_routes", "destination"),
    ("structured.shop_list", "destination"),
    ("structured.route_plan", "destination"),
    ("structured.stay_options", "destination"),
    ("structured.cost_breakdown", "destination"),
)

_CN_NUM: Tuple[str, ...] = ("一", "二", "三", "四", "五", "六",
                            "七", "八", "九", "十", "十一", "十二", "十三", "十四")


# ── 题-消费契约单一真相源（问卷优化 v2 · C1）────────────────────
# 每道问卷题（含增强题）的消费方式在这里登记；元测试钉死「有题必有登记、
# 登记值合法、plan_text 题面不得含承诺性文案」。新增一题不登记即红——
# 防止「问了不听」的装饰题再次出现（days/origin/focus 三个历史错位点即根因实例）。
CONSUMER_PLAN_TEXT = "plan_text"          # 答案仅作为提示词参考文本进计划层
CONSUMER_CONFIRM_ONLY = "confirm_only"    # 用户校对位，答案不改变产出


def _structured(point: str) -> str:
    return f"structured:{point}"


STRUCTURED_CONSUMERS = frozenset(
    _structured(p) for p in ("days_angle", "origin_angle", "perspective",
                             "destinations", "focus"))
ALL_CONSUMERS = STRUCTURED_CONSUMERS | {CONSUMER_PLAN_TEXT, CONSUMER_CONFIRM_ONLY}

# qid → {consumer, digest, label}；digest=True 的答案进报告头部答题摘要（C6 唯一白名单）。
CLARIFY_CONSUMERS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "guide": {
        "days": {"consumer": _structured("days_angle"), "digest": True, "label": "天数"},
        "party": {"consumer": _structured("perspective"), "digest": True, "label": "人群"},
        "budget_level": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "travel_season": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "origin": {"consumer": _structured("origin_angle"), "digest": False, "label": ""},
        "focus": {"consumer": _structured("focus"), "digest": True, "label": "侧重"},
        "extra": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "scope": {"consumer": CONSUMER_CONFIRM_ONLY, "digest": False, "label": ""},
        "destinations": {"consumer": _structured("destinations"), "digest": True, "label": "目的地"},
    },
    "assessment": {
        "intent": {"consumer": _structured("perspective"), "digest": True, "label": "用途"},
        "horizon": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "dimensions": {"consumer": _structured("focus"), "digest": True, "label": "侧重"},
        "budget_level": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "origin": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "extra": {"consumer": CONSUMER_PLAN_TEXT, "digest": False, "label": ""},
        "scope": {"consumer": CONSUMER_CONFIRM_ONLY, "digest": False, "label": ""},
        "destinations": {"consumer": _structured("destinations"), "digest": True, "label": "目的地"},
    },
}


def consumer_of(rtype: Optional[str], qid: str) -> Dict[str, Any]:
    """查题的消费登记；未登记返回 {}（元测试据此判红，运行期据此挂 consumer 键）。"""
    return consumer_registry(rtype).get(str(qid), {})


def clarify_digest_fields(rtype: Optional[str]) -> List[Tuple[str, str]]:
    """答题摘要的唯一白名单（C6 消费）：(qid, label)，只来自本注册表，禁止散点硬编码。"""
    return [(qid, cfg["label"]) for qid, cfg in consumer_registry(rtype).items()
            if cfg.get("digest")]


def consumer_registry(rtype: Optional[str]) -> Dict[str, Dict[str, Any]]:
    return CLARIFY_CONSUMERS.get(_type_key(rtype), CLARIFY_CONSUMERS[DEFAULT_RESEARCH_TYPE])


def _type_key(rtype: Optional[str]) -> str:
    s = str(rtype or "").strip().lower()
    return s if s in CLARIFY_CONSUMERS else DEFAULT_RESEARCH_TYPE


def _attach_consumers(rtype: str, qs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按注册表给每题挂 consumer 键（随问卷下发前端，前端忽略未知键）。"""
    reg = CLARIFY_CONSUMERS[rtype]
    for q in qs:
        q["consumer"] = reg[q["id"]]["consumer"]
    return qs


def _clarify_guide() -> List[Dict[str, Any]]:
    return _attach_consumers("guide", [
        {"id": "days", "question": "这次计划玩几天？", "type": "single",
         "options": ["1-2 天", "3-5 天", "6-10 天", "10 天以上", "还没定"]},
        {"id": "party", "question": "同行人群是？（决定行程节奏与视角章节）", "type": "single",
         "options": ["亲子家庭", "情侣/夫妻", "独自旅行", "朋友结伴", "带长辈", "摄影采风"]},
        {"id": "budget_level", "question": "预算档位大概在哪一档？", "type": "single",
         "options": ["经济实惠（人均 <1000）", "舒适均衡（1000-3000）",
                     "品质享受（3000-6000）", "高端不限（>6000）", "还没定"]},
        {"id": "travel_season", "question": "计划什么时候出行？", "type": "single",
         "options": ["寒暑假", "法定节假日", "春秋淡季",
                     "特定季节（赏花/滑雪/避暑等）", "还没定"]},
        {"id": "origin", "question": "从哪个城市出发 / 目前常驻哪里？（用于城际交通与抵达方案检索）",
         "type": "text", "options": [],
         "hint": "填写具体城市名（如 北京），报告将按此检索城际交通；不确定可留空。"},
        {"id": "focus", "question": "最看重哪些维度？（可多选，影响内容详略，不取舍章节）",
         "type": "multi",
         "options": ["景点榜与位置分布", "美食与商铺", "舆情口碑", "交通路线",
                     "预算控制", "住宿选型", "避坑防宰"]},
        {"id": "extra", "question": "还有哪些特定偏好、同行限制或需要纠正的信息？（选填）",
         "type": "text", "options": []},
    ])


def _clarify_assessment() -> List[Dict[str, Any]]:
    return _attach_consumers("assessment", [
        {"id": "intent", "question": "这次评估的用途是？（决定结论取向与视角章节）", "type": "single",
         "options": ["自住长居", "置业投资", "求学陪读", "养老避寒", "数字游民", "仅作横向对比"]},
        {"id": "horizon", "question": "看多长的时间跨度？", "type": "single",
         "options": ["1 年内", "1-3 年", "3-5 年", "5 年以上"]},
        {"id": "dimensions", "question": "最关心哪些维度？（可多选，影响内容详略，不取舍章节）",
         "type": "multi",
         "options": ["交通可达性", "生活配套", "治安安全", "居住成本",
                     "气候环境", "就业机会", "教育医疗", "发展前景"]},
        {"id": "budget_level", "question": "预算量级大概是多少？", "type": "single",
         "options": ["月支出 <5000", "5000-10000", "10000-20000", ">20000", "暂无概念"]},
        {"id": "origin", "question": "从哪个城市出发/作为对照基准？", "type": "single",
         "options": ["一线城市", "新一线/省会", "二三线城市", "海外", "不限"]},
        {"id": "extra", "question": "还有哪些特定顾虑、硬性条件或需要纠正的信息？（选填）",
         "type": "text", "options": []},
    ])


RESEARCH_TYPES: Dict[str, Dict[str, Any]] = {
    "guide": {
        "label": "游玩攻略",
        "subtitle": "景点榜 · 美食 · 舆情 · 路线 · 商铺 · 预算 · 住宿",
        "sections": {
            "quick": ("summary", "spots", "food", "transport", "budget"),
            "deep": ("summary", "spots", "food", "sentiment_report", "transport",
                     "shops", "budget", "stay", "route"),
            "expert": ("summary", "spots", "food", "sentiment_report", "transport",
                       "shops", "budget", "stay", "season", "route", "tips",
                       "contrarian", "conclusion", "risk"),
        },
        "numbered": ("spots", "food", "sentiment_report", "transport", "shops",
                     "budget", "stay", "season", "route", "tips"),
        "angles": ("抖音热门景点榜", "小红书必去景点", "小红书必吃美食", "抖音美食打卡",
                   "门票与预约", "商铺人均价格", "交通攻略", "住宿推荐",
                   "最新攻略2026", "游记实拍"),
        "rework_angles": ("最新攻略2026", "官方公告", "近期实拍"),
        "sentiment_platforms": ("douyin", "xiaohongshu", "bilibili", "mafengwo", "ctrip"),
        "sentiment_angles": ("{d} 值得去吗", "{d} 怎么样", "{d} 踩坑", "{d} 真实体验"),
        "structured_keys": ("spot_ranking", "food_ranking", "spot_routes", "shop_list",
                            "route_plan", "stay_options", "cost_breakdown"),
        "analysis_keys": ("comparison", "budget", "season", "share_estimate",
                          "trends", "contradictions"),
        "radar_key": "comparison",
        "radar_title": "目的地适配雷达对比",
        "radar_title_solo": "目的地适配雷达",
        "radar_dims": ("交通便利", "住宿性价比", "景点密度", "美食丰富度", "人均花费", "季节适配"),
        "cost_bar": {"key": "budget", "value_field": "per_capita_3d", "unit": "元/人·3天",
                     "title": "人均花费对比（3 天）", "title_solo": "人均花费拆解（3 天）"},
        "share_title": "热度/客流份额估算（分析师推断）",
        # 天数角度模板：只在用户原文确证给出天数时启用（{days} = 原文天数短语）。
        # 刻意不含目的地占位符——采集层按 f"{destination} {angle}" 拼检索词，带地名会重复。
        "days_angle_tpl": "{days}行程",
        # 城际交通角度模板（问卷 origin 题答案接通，C3）：{origin} = 用户填写的出发城市。
        # 与 days_angle_tpl 同型——恰 1 条、占一格预算；目的地由采集层前缀拼入。
        "origin_angle_tpl": "{origin}出发 城际交通方式 耗时 票价",
        # focus 题答案 → 角度关键词映射（C4）：勾选维度的匹配角度前置排序。
        "focus_qid": "focus",
        "focus_angle_keywords": {
            "景点榜与位置分布": ("景点", "榜", "景区", "位置", "地图"),
            "美食与商铺": ("美食", "吃", "餐", "商铺", "价格"),
            "舆情口碑": ("口碑", "测评", "体验", "实拍", "游记"),
            "交通路线": ("交通", "路线", "抵达", "高铁", "机场"),
            "预算控制": ("预算", "人均", "门票", "费用", "花费"),
            "住宿选型": ("住宿", "酒店", "民宿"),
            "避坑防宰": ("避坑", "坑", "宰", "注意", "防"),
        },
        "charts": ("radar", "cost_bar", "cost_compose", "season_heat", "donut",
                   "trend", "sentiment_donut", "platform_bar", "wordcloud"),
        "data_grid_sections": ("spots", "food", "budget", "shops", "route"),
        # 信息密度硬约束（评分/篇幅等规模参数仍归 MODE_CONFIG；这里是编辑规则），
        # 由 orchestrator 在写稿提示中注入，仅 guide 类型声明。
        "density": (
            "信息密度铁律：榜单/表格/清单等结构化数据先行，正文各段直接给事实、数据与机理"
            "（不写导语、总起句、评价性收束句——核心判断已单独成块，正文不得把它复述一遍）；"
            "景点/美食/商铺一律引用给定实体表中的名称与 spot_id，禁止另起别名或重新匹配；"
            "每段至少含 1 个具体数字（价格/耗时/占比/时长）或具体实体名，否则删掉该段；"
            "禁止「众所周知/随着社会发展/总而言之」等套话开头结尾，禁止空洞升华段。"
        ),
        "clarify": _clarify_guide(),
        "perspective_source": ("party", "perspective"),
        "perspectives": {
            "family": {"section": "persp_family",
                       "keywords": ("亲子", "带娃", "孩子", "儿童", "家庭", "婴儿")},
            "couple": {"section": "persp_couple",
                       "keywords": ("情侣", "夫妻", "双人", "二人", "蜜月")},
            "solo": {"section": "persp_solo",
                     "keywords": ("独自", "一个人", "单人", "独行", "solo")},
            "senior": {"section": "persp_senior",
                       "keywords": ("长辈", "父母", "老人", "老年", "爸妈", "银发")},
            "photo": {"section": "persp_photo",
                      "keywords": ("摄影", "拍照", "出片", "机位", "旅拍")},
        },
        "title_suffix": "旅游攻略报告",
        "cover_byline": "旅游调研 · 攻略",
        "glossary": (
            {"term": "景点综合评分", "definition": "由声量、口碑、性价比三类可数信号归一化后按 0.4/0.4/0.2 加权算出的榜单分，附计算明细，LLM 不参与打分。", "source": "本报告评分公式（scoring.py）"},
            {"term": "景点位置与路线", "definition": "景点坐标与公交/地铁/打车路线来自地图数据服务，匹配失败的景点仅进表格并标占位。", "source": "本报告数据管线"},
            {"term": "词云", "definition": "对采集到的真实评论做分词与词频统计后的高频词可视化，只呈现统计产物，不引用评论原句。", "source": "本报告分析框架"},
            {"term": "季节适配矩阵", "definition": "逐月出行适宜度评分（0-100），用于判断最佳出行窗口与需避开的时段。", "source": "本报告分析框架"},
            {"term": "人均花费拆解", "definition": "按交通/住宿/餐饮/门票等分类给出的人均花费与占比，用于判断预算分布。", "source": "本报告分析框架"},
        ),
    },
    "assessment": {
        "label": "调研评估",
        "subtitle": "可达性 · 配套 · 安全 · 性价比",
        "sections": {
            "quick": ("summary", "accessibility", "amenities", "safety", "verdict"),
            "deep": ("summary", "accessibility", "amenities", "safety", "value",
                     "trend", "verdict", "conclusion", "risk"),
            "expert": ("summary", "accessibility", "amenities", "safety", "value",
                       "trend", "livelihood", "verdict", "contrarian", "conclusion", "risk"),
        },
        "numbered": ("accessibility", "amenities", "safety", "value",
                     "livelihood", "trend", "verdict"),
        "angles": ("交通可达性", "生活配套", "居住成本", "治安与环境", "气候宜居",
                   "就业与发展", "教育医疗", "真实居住体验", "长期居住攻略"),
        "rework_angles": ("最新规划与政策", "官方统计数据", "近期居住体验"),
        "sentiment_platforms": ("xiaohongshu", "zhihu", "douyin", "bilibili", "dianping"),
        "sentiment_angles": ("{d} 宜居吗", "{d} 生活成本", "{d} 真实居住体验", "{d} 优缺点"),
        "structured_keys": ("access_matrix", "amenity_checklist", "risk_profile"),
        "analysis_keys": ("livability", "cost", "safety_index", "share_estimate",
                          "trends", "contradictions"),
        "radar_key": "livability",
        "radar_title": "目的地宜居度雷达对比",
        "radar_title_solo": "目的地宜居度雷达",
        "radar_dims": ("可达性", "配套完善", "安全", "成本", "气候", "发展潜力"),
        "cost_bar": {"key": "cost", "value_field": "monthly_living", "unit": "元/月",
                     "title": "月均生活成本对比", "title_solo": "月均生活成本拆解"},
        "share_title": "热度/关注份额估算（分析师推断）",
        "focus_qid": "dimensions",
        "focus_angle_keywords": {
            "交通可达性": ("交通", "可达", "高铁", "机场", "通勤"),
            "生活配套": ("配套", "商业", "生活"),
            "治安安全": ("治安", "安全", "风险"),
            "居住成本": ("成本", "房价", "租金", "费用", "生活成本"),
            "气候环境": ("气候", "环境", "天气"),
            "就业机会": ("就业", "工作", "招聘"),
            "教育医疗": ("教育", "医疗", "学校", "医院"),
            "发展前景": ("发展", "前景", "规划"),
        },
        "charts": ("radar", "cost_bar", "donut", "trend",
                   "sentiment_donut", "platform_bar"),
        "data_grid_sections": ("value", "accessibility", "trend"),
        "clarify": _clarify_assessment(),
        "perspective_source": ("intent", "perspective"),
        "perspectives": {
            "live": {"section": "persp_live",
                     "keywords": ("自住", "长居", "定居", "搬过去", "生活")},
            "invest": {"section": "persp_invest",
                       "keywords": ("投资", "置业", "买房", "购房", "房产")},
            "study": {"section": "persp_study",
                      "keywords": ("求学", "留学", "陪读", "上学", "教育")},
            "retire": {"section": "persp_retire",
                       "keywords": ("养老", "避寒", "退休", "康养")},
            "remote": {"section": "persp_remote",
                       "keywords": ("数字游民", "远程", "自由职业", "remote", "办公")},
        },
        "title_suffix": "宜居评估报告",
        "cover_byline": "旅游调研 · 评估",
        "glossary": (
            {"term": "可达性打分", "definition": "从主要出发地到目的地的交通方式、耗时、费用与班次频次综合量化。", "source": "本报告分析框架"},
            {"term": "配套完善度", "definition": "医疗/教育/商业/政务/网络等生活配套的覆盖程度评级（full/partial/none）。", "source": "本报告分析框架"},
            {"term": "风险画像", "definition": "按治安/自然灾害/医疗应急等维度给出的风险等级（low/medium/high）与依据。", "source": "本报告分析框架"},
        ),
    },
}


# ── 查表函数（各阶段统一入口）─────────────────────────────────
def type_spec(rtype: Optional[str]) -> Dict[str, Any]:
    """未知/空类型一律回落默认类型（不报错，防透传断链炸掉整条流水线）。"""
    return RESEARCH_TYPES.get(str(rtype or "").strip().lower()) or RESEARCH_TYPES[DEFAULT_RESEARCH_TYPE]


def type_key(rtype: Optional[str]) -> str:
    """归一化后的类型 key（用于落库/回传契约）。"""
    key = str(rtype or "").strip().lower()
    return key if key in RESEARCH_TYPES else DEFAULT_RESEARCH_TYPE


def research_type_options() -> List[Dict[str, str]]:
    """GET /api/research-types 的载荷（前端卡片唯一数据源）。"""
    return [{"key": k, "label": v["label"], "subtitle": v["subtitle"]}
            for k, v in RESEARCH_TYPES.items()]


def sections_for(rtype: Optional[str], mode: Optional[str], perspective: str = "") -> List[str]:
    """章节集：按类型 + 模式查表，再按视角插入专属板块（插在 conclusion 之前）。"""
    spec = type_spec(rtype)
    ids = list(spec["sections"].get(mode or "", spec["sections"][DEFAULT_MODE]))
    sid = perspective_section(rtype, perspective)
    if sid and sid not in ids:
        at = len(ids)
        for i, s in enumerate(ids):
            if s in ("conclusion", "risk"):
                at = i
                break
        ids.insert(at, sid)
    return ids


def section_fields(sid: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """章节 → (claim 字段, 图表类型)；未知章节回落 ("overview",)。"""
    return SECTION_FIELDS.get(sid, (("overview",), ()))


def section_structured_keys(sid: str) -> Tuple[str, ...]:
    """章节 → 应挂载的结构化键（渲染/审计的单一映射，防双定义）。"""
    return SECTION_STRUCTURED.get(sid, ())


def field_keywords(name: str) -> Tuple[str, ...]:
    return FIELD_KEYWORDS.get(name, ())


def claim_fields_for(rtype: Optional[str]) -> Tuple[str, ...]:
    """该类型下允许的 claim 字段全集（含共用字段与结构化字段，覆盖全部模式）。"""
    spec = type_spec(rtype)
    ids = {sid for mode_ids in spec["sections"].values() for sid in mode_ids}
    owned = {f for sid in ids for f in SECTION_FIELDS.get(sid, ((), ()))[0]}
    return tuple(sorted(set(spec["structured_keys"]) | owned | {"overview", "trend", "risk", "sentiment"}))


def perspective_key(rtype: Optional[str], raw: str) -> str:
    """把问卷答案（如「亲子家庭」「置业投资」）归一化为视角 key；无匹配返回 ""。"""
    text = str(raw or "")
    low = text.lower()
    for key, p in type_spec(rtype)["perspectives"].items():
        if any(kw in text or kw in low for kw in p["keywords"]):
            return key
    return ""


def perspective_section(rtype: Optional[str], raw: str) -> str:
    """问卷答案 → 视角专属章节 id；通用/综合答案返回 ""（不加板块）。"""
    key = perspective_key(rtype, raw)
    if not key:
        return ""
    return type_spec(rtype)["perspectives"][key]["section"]


def numbered_titles(present_ids: Sequence[str], rtype: Optional[str]) -> Dict[str, str]:
    """给类型 `numbered` 白名单内、且实际出现在报告里的章节加中文序号。

    按白名单顺序编号（而非章节在报告中的物理位置），未入选章节不加序号。
    """
    spec = type_spec(rtype)
    present = set(present_ids)
    out: Dict[str, str] = {}
    i = 0
    for sid in spec["numbered"]:
        if sid not in present:
            continue
        base = SECTION_PLAN.get(sid, sid)
        out[sid] = f"{_CN_NUM[i]}、{base}" if i < len(_CN_NUM) else base
        i += 1
    return out


def analysis_keys_for(rtype: Optional[str], n_destinations: int) -> Tuple[str, ...]:
    """按目的地数量取分析键：N<2 时剔除只靠「多对象可比」才成立的产出（如份额估算）。"""
    spec = type_spec(rtype)
    keys = tuple(spec["analysis_keys"])
    if n_destinations >= 2:
        return keys
    return tuple(k for k in keys if k not in MULTI_ONLY_ANALYSIS_KEYS)


def charts_for(rtype: Optional[str], n_destinations: int) -> Tuple[str, ...]:
    """按目的地数量取图集：N<2 剔除多对象专属图（份额环形图），N≥2 剔除单对象专属图
    （同城花费构成柱——多目的地要看的是城市之间的对比）；雷达保留（单对象评分仍可读）。"""
    spec = type_spec(rtype)
    charts = tuple(spec["charts"])
    if n_destinations >= 2:
        return tuple(c for c in charts if c not in SOLO_ONLY_CHARTS)
    return tuple(c for c in charts if c not in MULTI_ONLY_CHARTS)


def radar_title(rtype: Optional[str], n_destinations: int) -> str:
    """雷达图标题：单目的地不写「对比」（没有比较对象）。"""
    spec = type_spec(rtype)
    return spec["radar_title_solo"] if n_destinations < 2 else spec["radar_title"]


def cost_bar_title(rtype: Optional[str], n_destinations: int) -> str:
    """成本图标题：同上按 N 分支；类型未配成本图时返回空串（调用方本就跳过该图）。"""
    cb = type_spec(rtype).get("cost_bar") or {}
    return (cb.get("title_solo") or cb.get("title") or "") if n_destinations < 2 \
        else (cb.get("title") or "")


def report_title(destinations: Sequence[str], rtype: Optional[str]) -> str:
    names = "、".join(destinations) or "目的地"
    return f"{names} {type_spec(rtype)['title_suffix']}"

"""调研类型契约（单一真相源）：章节 / 搜索角度 / 分析 Schema / 澄清问卷 / 视角。

设计约束（务必保持）：
- **叶子模块**：仅依赖标准库，禁止 import app.core.*。orchestrator / audit / schemas /
  main 全部单向导入本模块，从根上杜绝「放 orchestrator 则 audit 反向 import」的循环依赖。
- **数据驱动**：各阶段遍历本注册表（spec["charts"] / spec["structured_keys"] ...）而不是
  写 `if rtype == "guide"` 分支；新增第 3 个调研类型 = 在 RESEARCH_TYPES 加一条记录，
  9 个阶段自动生效。漏键由 test_research_types.py 的泛型断言在 CI 拦下。
- 规模类配置（搜索量/篇幅/返工轮次）仍留在 orchestrator.MODE_CONFIG；本模块只管**语义**。
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
    # 游玩攻略
    "transport": "交通与抵达",
    "stay": "住宿区域与选型",
    "route": "逐日路线安排",
    "food": "美食清单",
    "budget": "预算拆解",
    "season": "最佳季节与气候",
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
    # 游玩攻略
    "transport": "交通与抵达：怎么去最划算、最快、最省心——航班/高铁/自驾/长途客运的班次频次、耗时、费用区间与换乘要点，给出明确的抵达方案建议。",
    "stay": "住宿区域与选型：各住宿区域的位置优劣、价格区间、适合人群、周边配套与真实踩坑点，给出「住哪个区域 + 住什么类型」的明确建议。",
    "route": "逐日路线安排：按天数给出可执行的行程节奏（景点、交通方式、停留时长、衔接要点），避免赶场与走回头路。",
    "food": "美食清单：必吃菜品/店铺/街区，含人均消费、排队情况、踩坑提示与本地人的正确吃法。",
    "budget": "预算拆解：按交通/住宿/餐饮/门票/购物分类给出人均花费区间与占比，说明不同档位的取舍，并提示可变成本与省钱空间。",
    "season": "最佳季节与气候：逐月气候与客流特征、旺季淡季差异、需要避开的时段，给出最佳出行窗口与备选方案。",
    "tips": "避坑指南：整理高频踩坑场景（宰客、低价团、黄牛、假特产、天气突变等）与可直接执行的应对方法。",
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
SECTION_FIELDS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    # 共用
    "summary": (("overview", "verdict"), ("radar", "donut", "trend")),
    "conclusion": (("overview", "verdict", "budget", "risk"), ()),
    "risk": (("risk",), ()),
    "contrarian": (("overview", "verdict", "trend"), ()),
    "trend": (("trend",), ("trend",)),
    # 游玩攻略
    "transport": (("transport",), ()),
    "stay": (("stay", "stay_options"), ()),
    "route": (("route", "route_plan"), ()),
    "food": (("food",), ()),
    "budget": (("budget", "cost_breakdown"), ("cost_bar",)),
    "season": (("season",), ("season_heat",)),
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
)

# 图表类型白名单（charts.py 能力面 ∩ 本模块使用面）
CHART_TYPES: Tuple[str, ...] = (
    "radar", "cost_bar", "season_heat", "donut",
    "trend", "sentiment_donut", "platform_bar",
)

# 已废弃的旧契约字段（防回潮：不得出现在任何类型的产出里）
DEPRECATED_CLAIM_FIELDS: Tuple[str, ...] = (
    "feature_tree", "pricing_model", "user_persona", "swot",
)

_CN_NUM: Tuple[str, ...] = ("一", "二", "三", "四", "五", "六",
                            "七", "八", "九", "十", "十一", "十二")


def _clarify_guide() -> List[Dict[str, Any]]:
    return [
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
        {"id": "focus", "question": "最看重哪些维度？（可多选）", "type": "multi",
         "options": ["交通与抵达", "住宿选型", "路线安排", "美食体验",
                     "预算控制", "季节气候", "避坑防宰"]},
        {"id": "extra", "question": "还有哪些特定偏好、同行限制或需要纠正的信息？（选填）",
         "type": "text", "options": []},
    ]


def _clarify_assessment() -> List[Dict[str, Any]]:
    return [
        {"id": "intent", "question": "这次评估的用途是？（决定结论取向与视角章节）", "type": "single",
         "options": ["自住长居", "置业投资", "求学陪读", "养老避寒", "数字游民", "仅作横向对比"]},
        {"id": "horizon", "question": "看多长的时间跨度？", "type": "single",
         "options": ["1 年内", "1-3 年", "3-5 年", "5 年以上"]},
        {"id": "dimensions", "question": "最关心哪些维度？（可多选）", "type": "multi",
         "options": ["交通可达性", "生活配套", "治安安全", "居住成本",
                     "气候环境", "就业机会", "教育医疗", "发展前景"]},
        {"id": "budget_level", "question": "预算量级大概是多少？", "type": "single",
         "options": ["月支出 <5000", "5000-10000", "10000-20000", ">20000", "暂无概念"]},
        {"id": "origin", "question": "从哪个城市出发/作为对照基准？", "type": "single",
         "options": ["一线城市", "新一线/省会", "二三线城市", "海外", "不限"]},
        {"id": "extra", "question": "还有哪些特定顾虑、硬性条件或需要纠正的信息？（选填）",
         "type": "text", "options": []},
    ]


RESEARCH_TYPES: Dict[str, Dict[str, Any]] = {
    "guide": {
        "label": "游玩攻略",
        "subtitle": "交通 · 住宿 · 路线 · 美食 · 预算",
        "sections": {
            "quick": ("summary", "transport", "stay", "route", "budget"),
            "deep": ("summary", "transport", "stay", "route", "food",
                     "budget", "season", "conclusion", "risk"),
            "expert": ("summary", "transport", "stay", "route", "food", "budget",
                       "season", "tips", "contrarian", "conclusion", "risk"),
        },
        "numbered": ("transport", "stay", "route", "food", "budget", "season", "tips"),
        "angles": ("交通攻略", "住宿推荐", "行程路线", "必吃美食", "门票与价格",
                   "避坑指南", "最佳季节", "最新攻略2026", "游记实拍"),
        "rework_angles": ("最新攻略2026", "官方公告", "近期实拍"),
        "sentiment_platforms": ("douyin", "xiaohongshu", "bilibili", "mafengwo", "ctrip"),
        "sentiment_angles": ("{d} 值得去吗", "{d} 怎么样", "{d} 踩坑", "{d} 真实体验"),
        "structured_keys": ("route_plan", "stay_options", "cost_breakdown"),
        "analysis_keys": ("comparison", "budget", "season", "share_estimate",
                          "trends", "contradictions"),
        "radar_key": "comparison",
        "radar_title": "目的地适配雷达对比",
        "radar_dims": ("交通便利", "住宿性价比", "景点密度", "美食丰富度", "人均花费", "季节适配"),
        "cost_bar": {"key": "budget", "value_field": "per_capita_3d", "unit": "元/人·3天",
                     "title": "人均花费对比（3 天）"},
        "share_title": "热度/客流份额估算（分析师推断）",
        "charts": ("radar", "cost_bar", "season_heat", "donut",
                   "trend", "sentiment_donut", "platform_bar"),
        "data_grid_sections": ("budget", "route"),
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
            {"term": "季节适配矩阵", "definition": "逐月出行适宜度评分（0-100），用于判断最佳出行窗口与需避开的时段。", "source": "本报告分析框架"},
            {"term": "逐日路线表", "definition": "按天拆解的景点—交通—停留时长安排，用于判断行程节奏是否可行。", "source": "本报告分析框架"},
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
        "radar_dims": ("可达性", "配套完善", "安全", "成本", "气候", "发展潜力"),
        "cost_bar": {"key": "cost", "value_field": "monthly_living", "unit": "元/月",
                     "title": "月均生活成本对比"},
        "share_title": "热度/关注份额估算（分析师推断）",
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


def report_title(destinations: Sequence[str], rtype: Optional[str]) -> str:
    names = "、".join(destinations) or "目的地"
    return f"{names} {type_spec(rtype)['title_suffix']}"

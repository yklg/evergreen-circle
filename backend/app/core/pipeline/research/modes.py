"""调研三档规模配置（M3 自 engine.py 原文迁出 · 行为零变化）。

只管**规模旋钮**（搜索量/篇幅/返工轮次/模型分档/实体规模/视角采集配额）；
章节集等**语义**归属 research_types 注册表，互不越界。
依赖：无内部分依赖（纯叶子），engine/assemble 共享同一真相源。
"""
from __future__ import annotations


# ── 调研模式三档（对应需求 3）─────────────────────────────
# 只管**规模**（搜索量/篇幅/返工轮次/模型档）；章节集属语义，查 research_types.sections_for()。
#
# section_max_tokens 是「正文 + 结构字段」共享的**单章**上限，且推理模型的思考 token 也算在里面
# （实测 deepseek 未关思考时，被截断章的推理约占 3.7–4.2k）。故三档都按「正文需求 + 推理余量」
# 给足，deep 6000→8000 正是为此。8192 是服务商（api.deepseek.com）单次输出上限，再高会被拒；
# 仍被截断的章由写稿后的 _repair_missing_structure 兜住（见该函数）。
MODE_CONFIG = {
    "quick": {
        "label": "快速模式",
        "max_angles": 4, "fetch_per_destination": 6, "platform_per": 6,
        "freshness": "oneYear", "rework_rounds": 0,
        # 写作深度：段落数下限 / 每段字数 / 单章 token 预算
        "min_paragraphs": 3, "para_words": "120-200", "section_max_tokens": 4500,
        "analyze_max_tokens": 6000, "structured_max_tokens": 6000,
        # 舆情覆盖：取口碑的目的地数 / 每平台每查询取条数
        "sentiment_destinations": 2, "platform_take": 5,
        # 逐景点舆情补充采集：每景点每平台取条数（0=不采集；quick 无舆情章故为 0）
        "spot_sent_take": 0,
        # 景点榜单实体规模（属规模配置，不进 research_types）
        "spot_topn": 4,
        # 商铺路线配额：每种榜上美食给前 N 家 matched 商铺配公交路线（0=不出；quick 无商铺章）
        "shop_route_topn": 0,
        # 视角专属采集配额（rough-cliff-vole）：槽位角度条数 / 逐景点二查前 N 名。
        # quick 全 0：核查表仍出（全行待核验），但不吃搜索预算——配额优先给主链路。
        "persp_slots": 0, "persp_probe_topn": 0,
    },
    "deep": {
        "label": "深度模式",
        "max_angles": 8, "fetch_per_destination": 12, "platform_per": 8,
        "freshness": "oneYear", "rework_rounds": 1,
        "min_paragraphs": 5, "para_words": "180-280", "section_max_tokens": 8000,
        "analyze_max_tokens": 8000, "structured_max_tokens": 8000,
        "sentiment_destinations": 3, "platform_take": 8,
        "spot_sent_take": 4,
        "spot_topn": 7,
        "shop_route_topn": 2,
        # 行程路线章（D2，deep 起出）：用户未写天数时按每天 N 景点推算行程跨度
        "spot_day_pace": 4,
        # 视角槽位 2 条 + 冻结榜前 7 名逐景点二查（≤16 次/deep 拍板口径）；
        # max_angles 6→8 保证 reserve（days/origin/视角 2）不再挤占模型角度（原 4 条保住）。
        "persp_slots": 2, "persp_probe_topn": 7,
    },
    "expert": {
        "label": "专家级模式",
        "max_angles": 11, "fetch_per_destination": 16, "platform_per": 10,
        "freshness": "oneYear", "rework_rounds": 2,
        # 专家级：篇幅最长、最详尽（券商行研/MBB 深度报告级别）
        "min_paragraphs": 7, "para_words": "260-420", "section_max_tokens": 8192,
        "analyze_max_tokens": 9000, "structured_max_tokens": 9000,
        "sentiment_destinations": 4, "platform_take": 10,
        "spot_sent_take": 6,
        "spot_topn": 10,
        "shop_route_topn": 2,
        # 一页视图节奏旋钮：用户未写天数时按每天 N 景点推算行程跨度（M3a）
        "spot_day_pace": 4,
        # 同 deep 的视角配额（二查按榜前 7，不为 expert 的 10 名榜放大搜索预算）
        "persp_slots": 2, "persp_probe_topn": 7,
    },
}

# 核心章用质量最高的模型档，其余用辅助档（属「模型分配」旋钮，与 MODE_CONFIG 同类，
# 故留在编排层而非语义注册表）。覆盖两类型各自最吃分析的章节。
CORE_SECTIONS = frozenset({
    "summary", "conclusion", "contrarian",
    "spots", "route", "budget",      # 游玩攻略
    "safety", "value", "verdict",    # 调研评估
})

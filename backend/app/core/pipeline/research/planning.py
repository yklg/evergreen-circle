"""目的地发现与调研计划（M3 自 engine.py 原文迁出 · 行为零变化）。

问卷候选目的地发现（LLM+正则兜底）、单/多目的地闸门、正交角度、plan 追踪。
依赖方向：planning → _util/runtime/errors + core 叶子（db/llm/research_types/trace），
不反向依赖 engine；符号由 engine re-export 保持既有接缝。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.core import db
from app.core import research_types as RT
from app.core import trace
from app.core import llm
from app.core.llm import LLMModelUnavailable, LLMNotConfigured, is_temporary_unavailable
from app.core.research_types import DEFAULT_RESEARCH_TYPE

from ._util import _DAY_PATTERNS, _core_name
from .errors import GuideSingleDestinationError
from . import runtime


# trace 里的固定 step 名（前端「决策日志」按它检索降级事实）
_DEST_PLAN_STEP = "目的地集合判定"


# 需求句里常见的动词/疑问短语：命中即说明这串是「一句话」而不是地名（历史缺陷：整句需求被当目的地）。
_DEST_REJECT_PHRASES = ("我想", "想去", "帮我", "推荐", "规划", "怎么玩", "多久", "多少钱", "最好")


# 只拒绝「一眼不是地名」的需求短语；不加字符白名单，否则「乌镇」「Lake Como」类真实地名会被误杀。
_DEST_REJECT_WORDS = ("对比", "比较", "评估", "调研", "攻略", "路线", "与", "和", "、", "/", "vs")


_DEST_RETRY_PURPOSE = "识别目的地（兜底重试）"


# ── 目的地发现（LLM 路径 + 正则兜底）──────────────────────
# 正则兜底用的静态候选目的地映射（按常见关键词命中，毫秒级、无需 LLM）。
_FALLBACK_DESTINATION_MAP: Dict[str, List[str]] = {
    "三亚": ["海口", "陵水", "万宁", "厦门"],
    "大理": ["丽江", "香格里拉", "腾冲", "西双版纳"],
    "丽江": ["大理", "香格里拉", "泸沽湖", "腾冲"],
    "成都": ["重庆", "西安", "昆明", "长沙"],
    "重庆": ["成都", "贵阳", "西安", "武汉"],
    "杭州": ["苏州", "南京", "绍兴", "上海"],
    "上海": ["杭州", "苏州", "南京", "厦门"],
    "北京": ["西安", "南京", "洛阳", "天津"],
    "西安": ["洛阳", "南京", "北京", "成都"],
    "厦门": ["泉州", "福州", "平潭", "青岛"],
    "青岛": ["大连", "威海", "烟台", "厦门"],
    "广州": ["深圳", "佛山", "珠海", "厦门"],
    "深圳": ["广州", "珠海", "香港", "厦门"],
    "长沙": ["武汉", "南昌", "重庆", "广州"],
    "昆明": ["大理", "贵阳", "南宁", "成都"],
    "桂林": ["阳朔", "贵阳", "张家界", "黔东南"],
    "贵阳": ["昆明", "重庆", "桂林", "黔东南"],
    "哈尔滨": ["长春", "沈阳", "漠河", "雪乡"],
    "乌鲁木齐": ["喀纳斯", "伊犁", "敦煌", "兰州"],
    "拉萨": ["林芝", "日喀则", "西宁", "香格里拉"],
    "西宁": ["兰州", "张掖", "敦煌", "拉萨"],
    "东京": ["大阪", "京都", "札幌", "首尔"],
    "大阪": ["东京", "京都", "福冈", "首尔"],
    "首尔": ["釜山", "济州", "东京", "大阪"],
    "曼谷": ["清迈", "普吉岛", "吉隆坡", "新加坡"],
    "新加坡": ["吉隆坡", "曼谷", "巴厘岛", "香港"],
    "巴厘岛": ["普吉岛", "长滩岛", "苏梅岛", "龙目岛"],
    "香港": ["澳门", "深圳", "台北", "新加坡"],
    "巴黎": ["罗马", "巴塞罗那", "伦敦", "柏林"],
    "伦敦": ["巴黎", "阿姆斯特丹", "柏林", "爱丁堡"],
    "纽约": ["洛杉矶", "芝加哥", "多伦多", "波士顿"],
    "悉尼": ["墨尔本", "奥克兰", "布里斯班", "黄金海岸"],
}


_FALLBACK_DOMAIN_MAP: Dict[str, str] = {
    "海岛": "海岛度假", "海滩": "海岛度假", "冲浪": "海岛度假",
    "古镇": "古镇水乡", "水乡": "古镇水乡", "古城": "古镇水乡",
    "自驾": "自驾公路", "公路": "自驾公路",
    "宜居": "移居/宜居", "移居": "移居/宜居", "长居": "移居/宜居", "养老": "移居/宜居",
    "徒步": "山岳徒步", "登山": "山岳徒步", "雪山": "山岳徒步",
    "亲子": "亲子研学", "带娃": "亲子研学", "研学": "亲子研学",
    "美食": "美食之旅", "小吃": "美食之旅",
    "滑雪": "冰雪运动", "冰雪": "冰雪运动",
    "摄影": "摄影采风", "出片": "摄影采风", "机位": "摄影采风",
    "温泉": "康养温泉", "康养": "康养温泉",
    "避暑": "避暑度假", "避寒": "避寒度假",
    "古建": "古建人文", "人文": "古建人文", "博物馆": "古建人文",
    "出境": "出境游", "签证": "出境游", "海外": "出境游",
    "预算": "预算与成本", "性价比": "预算与成本",
    "交通": "交通可达性", "高铁": "交通可达性", "航班": "交通可达性",
}


_MAX_DESTINATIONS = 6


# ── 目的地集合政策：唯一判据 + 唯一来源 + 三跳兜底 ──────────────
# 历史缺陷：模型被提示词命令「必须凑够 3-6 个对比目的地」，用户只说「我想去上海玩三天」
# 也会产出五城报告。根治办法是把「谁是目的地」的判定权收回给用户原文与勾选，
# 模型只当候选提供者；判据与取数路径各只有一处实现。
_MAX_DEST_NAME_LEN = 16


# 三跳都拿不到目的地时的占位名：宁可带着降级横幅空跑并在报告里如实标注，也不编造城市。
_NO_DESTINATION = "目的地"


# 出发地题允许留空或写模糊语；这些短语穿透 `_usable_destination`（「本地」是合法 2 字串），
# 必须在消费点整串精确匹配跳过，否则会生成「还没定出发 城际交通方式…」这类脏检索角度。
_ORIGIN_SKIP_WORDS = ("还没定", "待定", "不确定", "不知道", "还没想好", "再说",
                      "本地", "本地出发", "无所谓", "随便")


def _discover_scope(query: str) -> Dict[str, Any]:
    """领域识别 + 目的地自动发现（前置侦察，LLM 路径）。

    返回 {"subject", "domain", "candidates", "fallback"}。
    用 aux 模型（已关思考、JSON 稳定）；失败重试一次，
    仍失败则交由 _discover_scope_fallback 返回正则兜底（fallback=True），绝不抛错。
    """
    msgs = [
        {"role": "system", "content": (
            "你是旅游调研总监，负责开题前的『主题识别 + 候选目的地发现』。"
            "根据用户一句话需求，判断：①真正要调研的目的地/主题是什么（城市/景区/区域全称）；"
            "②它属于什么旅游细分领域（如 海岛度假、古镇水乡、自驾公路、移居宜居、亲子研学）；"
            "③围绕该主题，尽可能多地列出值得一并调研的真实候选目的地（8-12 个，"
            "必须是真实存在、可搜索的城市/景区，按可对比性与知名度从高到低排列，不要编造）。"
            '只输出 JSON：{"subject":"目的地/主题全称","domain":"细分领域","candidates":["候选目的地1","候选目的地2"]}。'
            "candidates 不要包含调研对象自身。只输出 JSON，不要任何解释或思考过程。"
        )},
        {"role": "user", "content": query},
    ]
    for _ in range(2):
        try:
            data = llm.chat_json(
                msgs, max_tokens=1500, temperature=0.3,
                model=runtime._model("aux"), purpose="主题识别+目的地自动发现",
            )
            if isinstance(data, dict) and (data.get("subject") or data.get("candidates")):
                subject = str(data.get("subject") or "").strip()
                domain = str(data.get("domain") or "").strip()
                comps = [
                    str(c).strip() for c in (data.get("candidates") or [])
                    if str(c).strip() and str(c).strip() != subject
                ]
                seen = set()
                comps = [c for c in comps if not (c in seen or seen.add(c))]
                return {
                    "subject": subject, "domain": domain,
                    "candidates": comps[:12], "fallback": False,
                }
        except Exception:
            pass
    # LLM 全失败 → 正则兜底（不抛，保证流程继续）
    return _discover_scope_fallback(query)


def _discover_scope_fallback(query: str) -> Dict[str, Any]:
    """纯正则 / 静态映射兜底：无 LLM 调用，毫秒级返回。

    命中已知目的地 → 给出其常见候选对比目的地与推测主体；否则尝试从引号抽取候选。
    始终返回 fallback=True（提示前端这是自动识别候选，需用户核对）。
    """
    q = (query or "").strip()
    low = q.lower()
    candidates: List[str] = []
    subject = ""
    for key, vals in _FALLBACK_DESTINATION_MAP.items():
        if key in low:
            candidates = [v for v in vals if v.lower() != key]
            subject = key
            break
    if not candidates:
        cand = re.findall(r"[‘’'\"\“\”]([^‘’'\"\“\”]{2,20})[‘’'\"\“\”]", q)
        candidates = [c.strip() for c in cand if c.strip()]
    domain = ""
    for kw, dom in _FALLBACK_DOMAIN_MAP.items():
        if kw in low:
            domain = dom
            break
    return {
        "subject": subject, "domain": domain,
        "candidates": candidates[:12], "fallback": True,
    }


def _usable_destination(name: Any) -> bool:
    """「这串字符能不能当一个目的地名」的唯一判据（四条取数路径共用）。"""
    s = str(name or "").strip()
    if not (2 <= len(s) <= _MAX_DEST_NAME_LEN) or s.isdigit():
        return False
    low = s.lower()
    return not any(w in low for w in _DEST_REJECT_WORDS + _DEST_REJECT_PHRASES)


def _mentioned_in_text(name: Any, text: str) -> bool:
    """目的地名是否出现在需求原文里（「上海」↔「上海市」等价，ASCII 大小写不敏感）。
    只做「候选名 ⊆ 原文」的单向判定；反向包含会让「海」这类短串误命中「上海」。"""
    core = _core_name(name)
    if len(core) < 2:
        return False
    return core.lower() in str(text or "").lower()


def _days_from_text(text: str) -> str:
    """抽取用户原文里的行程时长短语；命中即返回**原文片段本身**，保证天数角度必有出处。"""
    s = str(text or "")
    for pat in _DAY_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(0).strip()
    return ""


def _checked_destinations(clar: Dict[str, Any]) -> List[str]:
    """问卷里勾选/填写的目的地（兼容单字符串答案），仅过判据、不看原文。"""
    raw = (clar or {}).get("destinations") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in raw if _usable_destination(x)]


def _dedupe_names(names: List[str]) -> List[str]:
    """按核心名去重保序（「上海」与「上海市」算同一个）。"""
    out: List[str] = []
    seen = set()
    for n in names:
        key = _core_name(n).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n.strip())
    return out


def locked_destination(query: str, candidates: Any) -> str:
    """需求原文是否**唯一点名**了候选池里的一个目的地——问卷层与计划层共用的锁定判据。

    问卷据此跳过目的地题（用户已说清的事不再追问），计划层据此保证「不出题 ⇔ 集合
    就是锁定名」；两处必须同一函数，否则会出现问卷锁定了大理、计划却反问/扩城的分叉。
    候选池只认目的地发现给出的 candidates：subject 可能只是主题短语（「亲子游哪里好」
    的兜底 subject 是「亲子游」），并入会把提问句误判成锁定。
    """
    pool = [str(c).strip() for c in (candidates or [])]
    mentioned = [c for c in _dedupe_names(pool)
                 if _usable_destination(c) and _mentioned_in_text(c, query)]
    return mentioned[0] if len(mentioned) == 1 else ""


def origin_answer(clar: Dict[str, Any]) -> str:
    """出发地答案 → 城际交通检索凭据；仅当整串是一个可用地名时生效，否则视为未填。"""
    s = str((clar or {}).get("origin") or "").strip()
    if not s or s in _ORIGIN_SKIP_WORDS or not _usable_destination(s):
        return ""
    return s


def _destination_set(query: str, clar: Dict[str, Any],
                     plan_candidates: List[str]) -> Tuple[List[str], str]:
    """目的地集合的**唯一**来源：问卷勾选 ∪ 需求原文点过名的候选（并集只增不减，上限 6）。

    计划 LLM 给的候选只作为「待验证的池子」——用户没提的一律不纳入，这是防自扩的关键闸门。
    返回 (destinations, source)；source ∈ clarify/query/…，空列表表示需要走兜底链。
    """
    checked = [d for d in _checked_destinations(clar) if _usable_destination(d)]
    mentioned = [c for c in plan_candidates
                 if _usable_destination(c) and _mentioned_in_text(c, query)]
    merged = _dedupe_names(checked + mentioned)
    if not merged:
        return [], ""
    source = "clarify" if checked else "query"
    return merged[:_MAX_DESTINATIONS], source


def _orthogonal_angles(raw_angles: Any, destinations: List[str], days_phrase: str,
                       spec: Dict[str, Any], max_angles: int,
                       origin_phrase: str = "",
                       focus_keywords: Tuple[str, ...] = (),
                       persp_angles: Tuple[str, ...] = ()) -> List[str]:
    """把计划给出的角度整形成与目的地**正交**、且体现用户显式答题的角度集。

    规则（顺序即优先级）：
    1. 剔掉含任一目的地名的角度——采集层按 `f"{destination} {angle}"` 拼检索词，
       角度里再带地名会重复、带别的城市名会污染证据归属（历史缺陷的直接根因）；
    2. 剔掉含具体天数的角度——天数只许来自用户原文；注册表维度词「行程路线」不含天数，不受影响；
    3. 用户勾选了侧重维度（`focus_keywords`）→ 命中的角度**稳定排序前置**，
       截断时优先保住它们；未命中的原有相对次序不变；
    4. 原文/答案确证了天数且该类型配了 `days_angle_tpl` → 追加**恰好 1 条**天数角度；
       出发地答案可用且配了 `origin_angle_tpl` → 同样**恰好 1 条**城际交通角度；
    5. 全被剔空 → 回落注册表角度（用已知可靠的角度，不送空集）；
    6. 夹到 max_angles，并为天数/出发地两条确定性角度预留格子，保证不被挤掉。
    始终返回新列表，绝不改动注册表里的共享元组。
    """
    names = [_core_name(d) for d in destinations]

    def _conflicting(angle: str) -> bool:
        low = angle.lower()
        if any(n and n.lower() in low for n in names):
            return True
        return any(p.search(angle) for p in _DAY_PATTERNS)

    kept: List[str] = []
    for a in (raw_angles if isinstance(raw_angles, (list, tuple)) else []):
        if not isinstance(a, str):
            continue
        s = a.strip()
        if s and not _conflicting(s) and s not in kept:
            kept.append(s)

    if focus_keywords:
        lows = [k.lower() for k in focus_keywords if k]
        # sorted 稳定：命中侧重关键词的前置，其余保持模型给出的相对次序
        kept = sorted(kept, key=lambda a: 0 if any(k in a.lower() for k in lows) else 1)

    tpl = str(spec.get("days_angle_tpl") or "")
    days_angle = tpl.format(days=days_phrase).strip() if (days_phrase and tpl) else ""
    optpl = str(spec.get("origin_angle_tpl") or "")
    origin_angle = optpl.format(origin=origin_phrase).strip() if (origin_phrase and optpl) else ""
    reserve = (1 if days_angle else 0) + (1 if origin_angle else 0) + len(persp_angles)
    kept = kept[:max(0, max_angles - reserve)]
    if origin_angle and origin_angle not in kept:
        kept.append(origin_angle)
    if days_angle and days_angle not in kept:
        kept.append(days_angle)
    # 视角槽位（rough-cliff-vole）：与 days/origin 同型确定性追加，不被模型角度挤掉
    for a in persp_angles:
        if a and a not in kept:
            kept.append(a)
    if not kept:
        kept = [str(a) for a in spec["angles"]][:max_angles]
    return kept


def _plan_trace(task_id: str, decision: str, detail: str = "") -> None:
    """把「目的地是谁、从哪条路径来」写进决策日志（trace 本身持久化到 DB）。"""
    trace.record_manual_span(task_id, "L3-001", "intake", _DEST_PLAN_STEP,
                             detail=detail, decision=decision)


def _fallback_destination(query: str, research_type: str, task_id: str) -> Tuple[str, str]:
    """计划没拿到任何「用户点过名」的目的地时的三跳兜底，按序取第一个过判据的结果。

    三跳全部复用既有能力，不新写第四套地名识别：
    hop1 发现阶段缓存的 subject（零 LLM）→ hop2 静态地名表（`_discover_scope_fallback`）
    → hop3 一次 fast 档小模型专问。全 miss 则返回 ("", "fallback")。
    **模型不可用/限速类异常一律原样上抛**：把 404 伪装成「目的地自动识别」就是遮盖症状。
    """
    try:
        cached = db.get_discovery_cache(db._query_hash(query)) or {}
        subject = str(cached.get("subject") or "").strip()
    except Exception as e:  # noqa: BLE001 —— 缓存读失败必须留痕后继续下跳，不静默
        _plan_trace(task_id, "hop1 读发现缓存失败，改用静态地名表。",
                    f"{type(e).__name__}: {e}")
        subject = ""
    if _usable_destination(subject):
        return subject, "cache"

    subject = str((_discover_scope_fallback(query) or {}).get("subject") or "").strip()
    if _usable_destination(subject):
        return subject, "static"

    subject = _retry_destination(query, research_type, task_id)
    return (subject, "retry") if _usable_destination(subject) else ("", "fallback")


def _retry_destination(query: str, research_type: str, task_id: str) -> str:
    """最后一跳：单独问一次小模型「这句需求里的目的地是谁」（不做其它拆解，尽量便宜）。"""
    spec = RT.type_spec(research_type)
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研开题助手，本次任务类型是「{spec['label']}」。"
                    "只做一件事：从用户这句需求里**抽取**它提到的目的地名称。"
                    "不要推荐、不要补充用户没提到的城市/景区。"
                    '只输出 JSON：{"destination":"目的地名（城市/景区/区域，不要写成短语或整句）"}。'
                )},
                {"role": "user", "content": query},
            ],
            max_tokens=200, temperature=0.0, model=runtime._model("fast"),
            purpose=_DEST_RETRY_PURPOSE,
        )
    except Exception as e:  # noqa: BLE001
        # 模型本身不可用/没配 → 按既有契约上抛（runner 有对应报错分支），不降级
        if isinstance(e, (LLMNotConfigured, LLMModelUnavailable)) or is_temporary_unavailable(e):
            raise
        _plan_trace(task_id, "hop3 小模型重试失败，目的地降级为占位。", f"{type(e).__name__}: {e}")
        return ""
    if isinstance(data, dict):
        return str(data.get("destination") or data.get("subject") or "").strip()
    return str(data or "").strip()


def _plan_research(query: str, clar: Dict[str, Any], max_angles: int = 7,
                   research_type: str = DEFAULT_RESEARCH_TYPE,
                   task_id: str = "",
                   persp_slots: int = 0) -> Dict[str, Any]:
    """拆解调研计划：目的地只认用户点过名的，角度与目的地正交，天数只取原文。

    政策（详见改造计划 §4/§6）：
    - 模型只负责抽取与补全，**不得自扩调研范围**；它给出的候选只有出现在需求原文里
      （或被问卷勾选）才被采纳，其余丢弃。
    - 检索角度里不许夹带地名或具体天数；行程天数只来自用户原文（`_DAY_PATTERNS` 准绳）。
    - 拿不到目的地时走三跳兜底，并把降级事实写进 trace 与运行中横幅。
    - 返回 dict 的 `degraded` / `dest_source` 属**内部字段**：只供编排层推 SSE 与写 trace，不进报告 payload。
    """
    clar = clar or {}
    spec = RT.type_spec(research_type)
    clar_text = "；".join(f"{k}: {v}" for k, v in clar.items()
                         if v and not str(k).startswith("_"))
    checked = _checked_destinations(clar)
    region = str(clar.get("_region") or "").strip()
    candidates: List[str] = []
    focus: List[str] = []
    raw_angles: List[str] = []
    plan_error = ""
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研总监，本次任务类型是「{spec['label']}」（{spec['subtitle']}）。"
                    "从用户的调研需求里**抽取**信息，不要扩大范围、不要替换用户提到的对象、"
                    "不要补充用户没提的目的地。输出 JSON："
                    '{"subject":"用户要调研的目的地全称（单个城市/景区名，不要写成短语）",'
                    '"region":"目的地所属省份/国家（用于消歧，如 云南省、海南省、日本）",'
                    '"destinations":["你判断用户可能一并关心的候选目的地"],'
                    '"focus":["本次重点维度，如 交通/住宿/预算/口碑"],'
                    '"search_angles":["针对每个目的地的搜索角度短语"]}。'
                    "destinations 只是**候选**：只有用户在需求里点过名或勾选过的才会被采纳，"
                    "其余会被系统丢弃——绝不要为了凑齐对比对象而塞进用户没提的城市。"
                    "search_angles 每条只写维度短语（如 交通攻略、住宿推荐、门票与价格、避坑指南）："
                    "①不得含任何城市/景区名（检索词会自动带上目的地，重复地名会污染结果）；"
                    "②不得含具体天数（行程时长只依用户原文，不接受你推断的天数）。"
                    f"region 要给一个能精准消歧的行政区/国家短语（避免同名地歧义，如「凤凰」应识别为「湖南省湘西州」）。"
                    f"search_angles 给 {max_angles} 个，务必包含「最新攻略2026」「官方公告」等时效性角度以抓取最新信息。"
                    "只输出 JSON。"
                )},
                {"role": "user", "content": (
                    f"调研需求：{query}\n用户补充：{clar_text or '无'}\n"
                    f"用户已勾选的目的地（这些一定会被纳入，你只需补全维度与角度）："
                    f"{('、'.join(checked)) or '无'}"
                )},
            ],
            max_tokens=2000,
            temperature=0.3,
            model=runtime._model("fast"),
            purpose="拆解调研计划（目的地/维度/搜索角度）",
        )
        if isinstance(data, dict):
            candidates = [str(x).strip() for x in (data.get("destinations") or [])
                          if isinstance(x, str) and x.strip()]
            subject = str(data.get("subject") or "").strip()
            if subject:
                candidates.insert(0, subject)   # subject 也只当候选，同样过判据与原文校验
            focus = [f for f in data.get("focus", []) if isinstance(f, str)]
            region = str(data.get("region") or "").strip() or region
            raw_angles = [a for a in (data.get("search_angles") or []) if isinstance(a, str)]
    except Exception as e:  # noqa: BLE001
        if isinstance(e, (LLMNotConfigured, LLMModelUnavailable)) or is_temporary_unavailable(e):
            raise                          # 模型不可用不是「识别不到目的地」，必须如实报错
        plan_error = f"{type(e).__name__}: {e}"

    destinations, source = _destination_set(query, clar, candidates)
    degraded = False
    if not destinations:
        name, source = _fallback_destination(query, research_type, task_id)
        degraded = True
        destinations = [name] if name else [_NO_DESTINATION]

    # 终点闸门：问卷题已改单选、submit_clarify 也已拒，这里兜住「原文点名多目的地」
    # 与旧缓存问卷两条漏网路径——在采集/算分之前拒，不浪费后续预算。
    if research_type == "guide" and len([d for d in destinations if d != _NO_DESTINATION]) > 1:
        _plan_trace(task_id, f"guide 多目的地被拒（{'、'.join(destinations)}）。",
                    f"来源={source}\n需求原文：{query}\n勾选：{('、'.join(checked)) or '无'}")
        raise GuideSingleDestinationError(
            f"游玩攻略报告目前仅支持单个目的地，识别到 {len(destinations)} 个"
            f"（{'、'.join(destinations)}）。请改为单个城市/景区，或改用「调研评估」类型做对比。")

    # 天数判据双源：用户原文优先（显式说过就以它为准），原文没有才认问卷答案。
    days_phrase = _days_from_text(query) or _days_from_text(str(clar.get("days") or ""))
    origin_phrase = origin_answer(clar)
    focus_qid = str(spec.get("focus_qid") or "")
    sel_raw = clar.get(focus_qid) if focus_qid else None
    selected = [str(x).strip() for x in
                (sel_raw if isinstance(sel_raw, (list, tuple)) else ([sel_raw] if sel_raw else []))
                if str(x).strip()]
    kw_map = spec.get("focus_angle_keywords") or {}
    focus_keywords: List[str] = []
    for opt in selected:
        for k in kw_map.get(opt, ()):
            if k not in focus_keywords:
                focus_keywords.append(k)

    # 视角槽位（rough-cliff-vole）：视角命中且模式配了格子才占——
    # 判据源在 PERSPECTIVE_SPECS（编排层不写 persp_family 分支）。
    persp_qid, persp_key = (spec.get("perspective_source") or ("", ""))[:2]
    _persp_raw = str(clar.get(persp_key) or clar.get(persp_qid) or "")
    persp_sid = RT.perspective_section(research_type, _persp_raw)
    persp_angles = tuple(
        (RT.perspective_spec(persp_sid).get("angle_tpls") or ())[:max(0, persp_slots)])

    angles = _orthogonal_angles(raw_angles, destinations, days_phrase, spec, max_angles,
                                origin_phrase, tuple(focus_keywords),
                                persp_angles=persp_angles)
    if degraded or plan_error:
        detail = (f"计划候选：{('、'.join(candidates)) or '无'}\n"
                  f"需求原文：{query}\n勾选：{('、'.join(checked)) or '无'}")
        if plan_error:
            detail += f"\n计划 LLM 异常：{plan_error}"
        _plan_trace(task_id, f"目的地降级为「{'、'.join(destinations)}」（来源={source}）；"
                             "已在运行中提示用户核对。", detail)
    merged_focus = selected + [f for f in focus if f not in selected]
    return {
        "destinations": destinations,
        "focus": merged_focus or ["交通", "住宿", "预算", "口碑"],
        "angles": angles,
        "region": region,
        "degraded": degraded,
        "dest_source": source,
    }

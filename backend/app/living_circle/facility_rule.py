"""设施实体判表唯一事实源（生活圈 POI 归并）。

职责边界（照抄 `category_rule.py` 的分治纪律）：
  - **只回答「这两条 POI 是不是同一个实体设施」**（纯判表 + 判定函数），不碰预算、不发网络。
  - 几何判重在 `poi.is_duplicate`，实体归并判据在本模块，两者由 `poi.dedupe_pois` 的
    `policy` 决定用哪个 —— 判据**不得**塞进 `is_duplicate`，否则 `policy="geometric"`
    从那一层就漏了，盲区三要素通道的隔离当场失效。

要修的缺陷：百度把同一实体的功能子点（24小时自助银行、个贷中心、门诊、停车场、大门）
作为独立 POI 返回，于是「中国建设银行(昆明兴关支行)」与「中国建设银行24小时自助银行
(兴关支行)」（实测相距 10.89m）被算成两处金融设施 —— 图上重影、圈内计数虚高、
每类展示名额被同址记录白占。

三条判据原则：
  1. **机构主体必须相同**：只按「都含'银行'」+ 近距会把交通银行与建设银行合成一家
     （官渡实测 22.98m 就有这么一对）。
  2. **限定语相容而非相等**：真实数据里该合的案例**全部**是城市名前缀不对称
     （`昆明关上支行` ↔ `关上支行`、`潘家园支行` ↔ `北京潘家园支行`），
     按字面相等判会把 7 组该合样本全部拒掉且不报错。
  3. **距离是安全阀不是判据**：<50m 只防「同品牌不同网点」被拉合，本身绝不能单独用
     （放宽到 20~30m 就会命中原则 1 那对反例）。

> 本模块**不设**「至少一侧是功能子点」这道闸：双方都非子点时 `institution` 恒等于
> `norm_name(name)`，机构相同即蕴含归一化同名，<50m 的同名合并早已被 `is_duplicate`
> 的 U7 规则覆盖，加闸不拦任何新案例（真实数据 0 例）。评审第 1 轮曾把它记为
> 「防两家美宜佳被合成一家」的护栏，该理由不成立 —— 那对点位今天就被 U7 合并着。
> 见 `same_facility` 内的同款注释，别再把它当安全网。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.living_circle.geo_utils import haversine_m

# 判据版本号：并进 `caliber.caliber_payload_key` 与报告举证，改动必须升版本。
FACILITY_RULE_VERSION = "v1"


def norm_name(name: str) -> str:
    """名称归一：去空白/全角 → 剥括号 → 小写。

    **定义在此而非 `poi.py`**：本模块与 `category_rule` 一样是纯判表层，不得反向依赖
    管线层（否则 `poi → facility_rule → poi` 成环）。`poi.py` 单向 import 本函数，
    `poi.norm_name` 仍可寻址 —— 口径索引 `poi::norm_name` 与专家团绑定不受影响。
    """
    if not name:
        return ""
    s = re.sub(r"[\s\u3000]+", "", name)
    s = re.sub(r"（.*?）|\(.*?\)", "", s)
    return s.lower()


# 同一设施的归并半径（米）。与 `poi.dedupe_pois` 的同名聚簇半径同量级但**语义不同**：
# 那里是「同一家店被多关键词重复返回」，这里是「同一实体的功能子点贴在建在它旁边」。
FACILITY_MERGE_M = 50.0

# 功能子点后缀词表：命中即「它是某个设施的附属职能/出入口，而不是一个独立设施」。
# **长词在前**由 `_longest_suffix` 按最长匹配保证，不依赖本表顺序。
# 刻意不收「营业部 / 分理处 / 储蓄所」—— 它们更像独立网点，收进来有把两个真网点
# 合掉的风险（见计划「待确认事项 5」）。
SUB_POINT_SUFFIXES: Tuple[str, ...] = (
    "24小时自助银行", "自助银行", "自动柜员机", "存取款一体机", "atm",
    "个贷中心", "信用卡中心", "小微服务中心", "理财中心", "贷款中心",
    "发热门诊", "急诊", "门诊", "住院部", "体检中心", "预防保健科",
    "立体停车场", "地面停车场", "地下停车场", "停车场",
    "出入口", "西门", "东门", "南门", "北门", "侧门", "大门",
    "号楼", "分院",
)
# 「X门」这类带编号的门（西2门 / 1号门）用正则兜，不逐个枚举。
_SUB_POINT_PATTERN = re.compile(r"(?:[东南西北]\d*门|\d+号门)$")

# 剥完子点后缀会留下的悬挂分隔符。
_DANGLING_SEP = re.compile(r"[-—–·\s]+$")

# 序数分支号：「中国建设银行**第五**个贷中心」剥掉「个贷中心」后剩「中国建设银行第五」，
# 不归一就与主点「中国建设银行」不同名、合不掉（黄金样本 guandong-ccb-xingguang-loancenter）。
_ORDINAL_TAIL = re.compile(r"第[\d一二三四五六七八九十百零]+$")

# 显式父子字段（当前百度 place/v2 不提供，留作多源接入的优先通道）。
_PARENT_KEYS = ("parent_uid", "parent_id", "parent_poiid")
_UID_KEYS = ("uid", "poi_id", "poiid")


class FacilityCore(NamedTuple):
    """一条 POI 名称拆出的设施身份三元组。"""

    institution: str        # 机构主体名（剥括号 + 剥子点后缀）；空串表示无从判定
    branch_qualifier: str   # 括号内支行/网点限定语，已归一；无则空串
    is_sub_point: bool      # 是否功能子点
    matched_suffix: str     # 命中的子点词（供披露与升格用），未命中为空串


def _explicit_parent_link(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """两侧是否由**显式父子字段**直接连上（有字段就优先信字段，不信名称）。"""
    for key_a in _PARENT_KEYS:
        pa = a.get(key_a)
        if not pa:
            continue
        for key_b in _UID_KEYS:
            if b.get(key_b) and pa == b[key_b]:
                return True
    return False


def _longest_suffix(core: str) -> str:
    """返回 core 末尾命中的**最长**子点词（未命中返回空串）。"""
    best = ""
    for suffix in SUB_POINT_SUFFIXES:
        if core.endswith(suffix) and len(suffix) > len(best):
            best = suffix
    if best:
        return best
    m = _SUB_POINT_PATTERN.search(core)
    return m.group(0) if m else ""


def facility_core(name: str) -> FacilityCore:
    """名称 → 设施身份三元组。

    归一化**复用 `poi.norm_name`**（去空白/全角、剥括号、小写），避免出现两套并行的
    名称归一器而互相漂移。限定语要在剥括号**之前**取，故先单独提取一次。
    """
    if not name:
        return FacilityCore("", "", False, "")
    m = re.search(r"[（(]([^）)]*)[）)]", name)
    qualifier = norm_name(m.group(1)) if m else ""
    core = norm_name(name)
    suffix = _longest_suffix(core)
    if suffix:
        institution = _ORDINAL_TAIL.sub("", _DANGLING_SEP.sub("", core[: -len(suffix)]))
    else:
        institution = core
    return FacilityCore(institution, qualifier, bool(suffix), suffix)


def _qualifiers_compatible(qa: str, qb: str) -> bool:
    """限定语相容性：**一侧为空、或互为包含**即相容；都非空且互不包含才拒。

    相容而非相等，是因为真实数据里同一网点的限定语普遍带不带城市名前缀不对称
    （`昆明关上支行` vs `关上支行`）。字面相等判据会让归并整体静默打空。
    """
    if not qa or not qb:
        return True
    return qa in qb or qb in qa


def same_facility(
    a: Dict[str, Any],
    b: Dict[str, Any],
    distance_m: float,
    radius_m: float = FACILITY_MERGE_M,
    category: Optional[str] = None,
) -> bool:
    """两条 POI 是否属于**同一个实体设施**（`policy="facility"` 时追加的判据）。

    `category` 形参当前不参与判定，是留给「按类别差异化归并强度」的扩展位
    （仿 `category_rule.SHOPPING_INCLUDE_CONVENIENCE` 的口径开关形态）。
    """
    if distance_m >= radius_m:
        return False
    if _explicit_parent_link(a, b) or _explicit_parent_link(b, a):
        return True

    fa, fb = facility_core(a.get("name", "")), facility_core(b.get("name", ""))
    if not fa.institution or fa.institution != fb.institution:
        return False                       # 原则 1：机构主体必须相同
    if not (fa.is_sub_point or fb.is_sub_point):
        # 双方都不是功能子点 —— 此时 `institution` 恒等于 `norm_name(name)`（没剥任何后缀），
        # 「机构相同」就蕴含「归一化同名」，<50m 的同名合并**已由 `is_duplicate` 覆盖**
        # （U7）。本分支不新增任何拦截，只是把这条推理写明，免得后人以为这里有闸。
        return False
    return _qualifiers_compatible(fa.branch_qualifier, fb.branch_qualifier)


def promote_display_name(name: str) -> str:
    """子点名 → 其所属机构名：`中国建设银行24小时自助银行(昆明官渡支行)` →
    `中国建设银行(昆明官渡支行)`。

    在**原始大小写**上做（`facility_core` 的 institution 已小写化，直接用会把英文店名打烂），
    剥的是同一个 `matched_suffix` + 序数尾巴，保证与判据用的是同一份词表。
    """
    core = facility_core(name)
    if not core.is_sub_point or not core.matched_suffix:
        return name
    lowered = name.lower()
    idx = lowered.rfind(core.matched_suffix)
    if idx < 0:
        return name
    head = _ORDINAL_TAIL.sub("", name[:idx]).rstrip("-—–· ")
    tail = name[idx + len(core.matched_suffix):]
    return f"{head}{tail}"


def pick_representative(
    group: Sequence[Dict[str, Any]], center: Tuple[float, float]
) -> Dict[str, Any]:
    """代表点 = 组内**距查询中心最近**者（它天然也是耗时最小的那个）。

    并列时取名称更短者（主点名字通常比子点短）。`center` 必须是查询中心，
    不可用可达区环的顶点 —— 理由同 `poi.to_points` 的 `center` 注释。
    """
    return min(
        group,
        key=lambda it: (haversine_m((it["lng"], it["lat"]), center), len(it.get("name") or "")),
    )


def pick_display_name(
    group: Sequence[Dict[str, Any]],
    representative: Dict[str, Any],
    taken_names: Sequence[str] = (),
) -> str:
    """展示名：优先用组内**主点**的名称；全是子点时才升格为机构主体名。

    升格带一道护栏：升格后的名字若与同类别里已存在的其它点位撞名，就放弃升格、
    保留代表点原名 —— 否则一张图上会出现两个同名点位。北京劲松正是这个形状：
    「潘家园旧货市场」主点距其停车场/西2门 171m、不在同组，若把子点组升格成同一个
    名字，购物类里就会并列两个「潘家园旧货市场」。
    """
    parents = [it for it in group if not facility_core(it.get("name", "")).is_sub_point]
    if parents:
        return min(parents, key=lambda it: len(it.get("name") or ""))["name"]

    promoted = promote_display_name(representative.get("name", ""))
    if promoted == representative.get("name") or promoted in taken_names:
        return representative["name"]
    return promoted


def sub_point_labels(group: Sequence[Dict[str, Any]]) -> List[str]:
    """组内被吸收的**子点**职能标签（去重、保持首次出现顺序），供「含24小时自助」标注。"""
    labels: List[str] = []
    for it in group:
        core = facility_core(it.get("name", ""))
        if core.is_sub_point and core.matched_suffix and core.matched_suffix not in labels:
            labels.append(core.matched_suffix)
    return labels


def annotate_name(name: str, labels: Sequence[str]) -> str:
    """把子点职能并进展示名（写进 `name` 字符串本身，不动 `PoiPoint` 跨端契约）。"""
    if not labels:
        return name
    return f"{name} · 含{'/'.join(labels[:2])}"

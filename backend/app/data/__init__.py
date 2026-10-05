"""48 专家数据加载（双域名册：旅游调研 experts.json / 生活圈 experts_living_circle.json）。

融合后两域共用同一套 48 个 id/头像/层级，但知识人设与 group 按域不同：
  - travel（默认）：decision/strategy/industry/function，旅游调研引擎使用；
  - living_circle：decision/strategy/facility/method，lc_team 组队使用。

加载器保持宽松（skip 既有铁律，test_expert_loader_availability 守护）：
缺字段回落默认值并记 warning，缺文件回落 travel 默认，绝不因名册数据问题阻断启动；
结构性强校验由 app.data.schema.validate_roster() 在 CI/自检端点负责，不进 loader。
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent
_FILES = {
    "travel": _DIR / "experts.json",
    "living_circle": _DIR / "experts_living_circle.json",
}
_DEFAULT_DOMAIN = "travel"

#: 合法域名清单（端点层校验与测试共用，避免第二份字面量）
DOMAINS = tuple(_FILES)


def _normalize(data: list[dict]) -> list[dict]:
    """宽松校验：只记录 warning/回落默认值，绝不因数据问题抛异常。"""
    for idx, e in enumerate(data):
        eid = e.get("id", f"<index:{idx}>")
        if not e.get("name"):
            logger.warning("[%s] name 缺失，回退为 id", eid)
        if not isinstance(e.get("skills"), list):
            logger.warning("[%s] skills 非列表，回退为空列表", eid)
            e["skills"] = []
        if not isinstance(e.get("knowledge_tags"), list):
            logger.warning("[%s] knowledge_tags 非列表，回退为空列表", eid)
            e["knowledge_tags"] = []
        if "caliber_refs" not in e:
            e["caliber_refs"] = []
    return data


@lru_cache
def load_experts(domain: str) -> list[dict]:
    """按域取名册。`domain` **必填**：两本名册共用同一套 48 个 id、人设却不同，
    留一个"默认域"等于让忘记传域的调用点静默拿到另一本人设（生活圈报告署名曾整批
    取成旅游人设，实测 7/7 章全错），而这类错误不会抛异常、只会显示成另一个人名。

    未知域名 ⇒ 直接抛错，绝不回落 travel（回落等于把同一个静默错值留给端点层）。
    唯一保留的回落是**文件级**的：living_circle 文件缺失/损坏时借 travel 并记 warning，
    让"名册数据缺陷"永不阻断启动（由 test_expert_loader_availability 守）。
    """
    if domain not in _FILES:
        raise ValueError(f"未知专家域 {domain!r}，可选：{', '.join(DOMAINS)}")
    path = _FILES[domain]
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        if domain != _DEFAULT_DOMAIN:
            logger.warning("名册 %s 不可用（%s），回落 travel 默认名册", path.name, exc)
            with open(_FILES[_DEFAULT_DOMAIN], "r", encoding="utf-8") as f:
                return _normalize(json.load(f))
        raise


def expert_by_id(eid: str, domain: str) -> Optional[dict]:
    for e in load_experts(domain):
        if e.get("id") == eid:
            return e
    return None


def experts_by_level(level: str, domain: str) -> list[dict]:
    return [e for e in load_experts(domain) if e.get("level") == level]

"""48 专家数据加载（前后端共用同一份 experts.json）。

加载器保持宽松：缺字段回落默认值，记录 warning 但不阻断。
结构性校验由 app.data.schema.validate_roster() 负责，
在生成脚本、CI 测试与 /api/experts/integrity 自检端点中调用。
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA = Path(__file__).parent / "experts.json"


@lru_cache
def load_experts() -> list[dict]:
    with open(_DATA, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 宽松校验：只记录 warning，绝不因数据问题抛异常
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


def expert_by_id(eid: str) -> Optional[dict]:
    for e in load_experts():
        if e.get("id") == eid:
            return e
    return None


def experts_by_level(level: str) -> list[dict]:
    return [e for e in load_experts() if e.get("level") == level]

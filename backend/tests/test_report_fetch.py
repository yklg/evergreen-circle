"""报告读取端点的状态码契约（live 档白屏缺陷的后端半边，独立于第五维）。

实测成因：`GET /api/reports/{id}` 曾对**不存在**的报告返回 **HTTP 200 + `{ok:false,
message:'report not ready'}`**。前端 `lib/api.ts` 的 `safeJson` 只看 HTTP 状态 ⇒ 那枚信封
被当成一份报告塞进 store ⇒ `ReportPage.tsx` 在 `r.evidence.map` 上抛 TypeError、整页白屏。
同族端点（`/brief`、`/refine`、`/feedback`）本来就返 404 —— 这个 GET 是异类。

两条判据各钉一半：**不存在 ⇒ 404**（而不是 200 信封）、**存在 ⇒ 200 且原样是那一份**
（后者防"把路由改成永远 404"也算通过）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import db
from app.main import app


def test_missing_report_is_404_not_a_200_envelope():
    r = TestClient(app).get("/api/reports/r-definitely-missing-zz")
    assert r.status_code == 404, f"实得 {r.status_code} + {r.text[:120]}"
    body = r.json()
    assert body.get("detail"), "404 也要带可读 detail（前端那一支会显式抛错，不做静默兜底）"
    # 关键区别：响应体是 FastAPI 的 `{detail}`，**不是**旧那枚 `{ok:false,message:...}` 信封 ——
    # 后者会被只看 HTTP 状态的前端当成一份报告。
    assert set(body) == {"detail"}, f"404 响应体形状变了（不许再混进 ok/message）：{body}"
    assert body["detail"] == "report not ready"


def test_present_report_still_serves_200(monkeypatch):
    """正对照：404 那半边不许顺手把路由改成"永远找不到"。"""
    fake = {
        "id": "r-present-zz", "title": "在的", "subtitle": "", "created_at": "2026-10-13T00:00:00Z",
        "report_type": "research", "experts": [], "toc": [], "sections": [], "charts": [],
        "evidence": [], "claims": [], "metrics": {},
    }
    monkeypatch.setattr(db, "get_report", lambda rid: dict(fake))
    r = TestClient(app).get("/api/reports/r-present-zz")
    assert r.status_code == 200, f"实得 {r.status_code} + {r.text[:120]}"
    assert r.json()["id"] == "r-present-zz"

"""A6 精神 · 后端/前端 fixture 镜像守卫：backend/app/living_circle/fixtures 与
frontend VITE_USE_MOCK fixture 必须逐字节一致（M5 由 make_fixtures 双写覆写）。"""
import hashlib
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT = BACKEND_DIR.parent  # skip/
FRONTEND_FIXTURES = PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_living_circle_fixtures_mirror_frontend():
    pairs = [
        (BACKEND_DIR / "app" / "living_circle" / "fixtures" / "kaili.json",
         FRONTEND_FIXTURES / "kaili.json"),
        (BACKEND_DIR / "app" / "living_circle" / "fixtures" / "beijing-jinsong.json",
         FRONTEND_FIXTURES / "beijing-jinsong.json"),
    ]
    for backend_f, front_f in pairs:
        assert front_f.exists(), f"前端 fixture 缺失: {front_f}"
        assert backend_f.exists(), f"后端 fixture 缺失: {backend_f}"
        assert _md5(backend_f) == _md5(front_f), (
            f"镜像漂移: {backend_f.name} 与前端不一致——请用 scripts/make_fixtures.py 双写后重跑"
        )
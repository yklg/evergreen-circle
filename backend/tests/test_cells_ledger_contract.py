"""逐格台账契约夹具的**后端侧**钉子（两侧同钉，范式同 `compareDiffContract.json`）。

夹具住在前端（`frontend/src/__tests__/fixtures/cellsLedgerContract.json`），因为读侧要 import 它；
但它描述的字母表、键名、格型与格阵换算**归后端定**。没有这一支，前端那份就是手抄本 ——
手抄本的历史结局本仓写过很多次了：写侧改一个字符，读侧继续按旧的解释画给用户。

这里只问一件事：**夹具说的，是不是生产码此刻真的在发的那些东西**。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.living_circle.blindspot import (
    LEDGER_GRID,
    LEDGER_NO,
    LEDGER_SCHEMA_VERSION,
    LEDGER_UNKNOWN,
    LEDGER_YES,
    TRIAD_KEYS,
)
from app.living_circle.geo_utils import to_local_xy

BACKEND = Path(__file__).resolve().parents[1]
FIXTURE = BACKEND.parent / "frontend" / "src" / "__tests__" / "fixtures" / "cellsLedgerContract.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_alphabet_and_schema_match_the_producing_constants():
    assert CONTRACT["letters"] == {
        "yes": LEDGER_YES, "no": LEDGER_NO, "unknown": LEDGER_UNKNOWN, "no_distance": "-",
    }, "台账字母表漂了：读侧会把「没查过」画成别的字"
    assert CONTRACT["grid"] == LEDGER_GRID
    assert CONTRACT["schema_version"] == LEDGER_SCHEMA_VERSION


def test_key_names_are_the_ones_render_cells_ledger_actually_emits():
    """夹具的键名集必须**等于**渲染器发出的那份（多一个少一个都算漂）。"""
    assert sorted(CONTRACT["keys"]) == sorted(
        ["grid", "schema_version", "n", "step_m", "scan_m", "radius_m", "center",
         "inside", "capped", "blind", "verdict"]
        + [f"{p}.{k}" for p in ("judge", "present", "nearest") for k in TRIAD_KEYS])
    assert sorted(CONTRACT["matrix_keys"]) == sorted(
        ["inside", "capped", "blind", "verdict"]
        + [f"{p}.{k}" for p in ("judge", "present") for k in TRIAD_KEYS])
    assert sorted(CONTRACT["distance_keys"]) == sorted(f"nearest.{k}" for k in TRIAD_KEYS)


def test_sample_uses_only_the_declared_alphabet_and_shape():
    led = CONTRACT["sample"]
    n = led["n"]
    assert n % 2 == 1 and n > 0
    for key in CONTRACT["matrix_keys"]:
        rows = led[key]
        assert len(rows) == n and all(len(r) == n for r in rows), key
        assert set("".join(rows)) <= {LEDGER_YES, LEDGER_NO, LEDGER_UNKNOWN}, key
    for key in CONTRACT["distance_keys"]:
        rows = led[key]
        assert len(rows) == n
        for row in rows:
            toks = row.split(" ")
            assert len(toks) == n, key
            assert all(t == "-" or t.isdigit() for t in toks), key


def test_sample_is_self_consistent_with_the_asymmetry_rule():
    """夹具那五档结论必须真由"判盲只需一类有据、说不盲要三类有据"推出来。

    否则前端测的是一堆**编出来的**期望值 —— 读侧全绿而语义是假的，比红更难查。
    """
    led = CONTRACT["sample"]
    n = led["n"]
    for i in range(n):
        for j in range(n):
            inside = led["inside"][i][j] == LEDGER_YES
            asked = [k for k in TRIAD_KEYS if led[f"judge.{k}"][i][j] == LEDGER_YES]
            present = {k: led[f"present.{k}"][i][j] for k in TRIAD_KEYS}
            if not inside:
                assert led["blind"][i][j] == led["verdict"][i][j] == LEDGER_NO, (i, j)
                assert all(present[k] == LEDGER_UNKNOWN for k in TRIAD_KEYS), (i, j)
                continue
            blind = any(present[k] == LEDGER_NO for k in asked)
            clear = (not blind and len(asked) == len(TRIAD_KEYS)
                     and all(present[k] == LEDGER_YES for k in TRIAD_KEYS))
            assert (led["blind"][i][j] == LEDGER_YES) is blind, (i, j)
            assert (led["verdict"][i][j] == LEDGER_YES) is (blind or clear), (i, j)
            # 有据 ⇔ 该格的判定圆被盘完整盖住；没盖住就不许有结论位（第三态的读侧版本）
            for k in TRIAD_KEYS:
                if led[f"judge.{k}"][i][j] == LEDGER_NO:
                    assert present[k] == LEDGER_UNKNOWN, (i, j, k)
                if led[f"nearest.{k}"][i].split(" ")[j] != "-":
                    assert present[k] != LEDGER_UNKNOWN, (i, j, k)


def test_cell_at_cases_agree_with_the_backend_grid_arithmetic():
    """`cellAt` 的格阵映射必须与后端 `to_local_xy` + `linspace(-scan, scan, n)` 同式。

    这一条是"点中的格"与"卡片说的那格"是同一格的唯一凭据：两端各写一遍换算，
    纬度余弦取整方式一不同就会错一格。
    """
    led = CONTRACT["sample"]
    center = tuple(led["center"])
    n, scan, step = led["n"], led["scan_m"], led["step_m"]
    for case in CONTRACT["cell_at"]["cases"]:
        lng, lat = case["lnglat"]
        x, y = to_local_xy(center, lng, lat)
        i = int(round((y + scan) / step))
        j = int(round((x + scan) / step))
        want = None if (i < 0 or j < 0 or i >= n or j >= n) else [i, j]
        assert case["cell"] == want, f"{case['lnglat']} 夹具说 {case['cell']}，后端算得 {want}"

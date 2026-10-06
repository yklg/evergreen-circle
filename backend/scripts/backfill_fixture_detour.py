"""笔 3b（前半）：把 `rc-1` 与 `sampling.detour` 离线补进两份镜像夹具。

**零外呼、零分数变更**：标定块由生产函数 `isochrone.detour_residual` 从每份夹具自己的
1049 个采样点现算（与 live 链同一个实现，不在这里另写一份判据 —— 否则就是本仓正在消灭的
「同一语义多份实现」）。只加两个键，别的字段一律不动，并且**由程序证明**这一点。

用法：
    .venv/bin/python scripts/backfill_fixture_detour.py --check   # 只核对与试算，不写盘
    .venv/bin/python scripts/backfill_fixture_detour.py --apply   # 通过核对后写出

三条硬前置（任一不成立就拒绝写）：
 ① 排版保真：`json.dumps(doc, indent=2, ensure_ascii=False)` 必须与原字节相同（只差行尾空白可容忍）。
    不保真就说明夹具的写入口用的是别的格式，我这里一写就会把整份文件重排成看不出改动的巨大 diff。
 ② 诚实闸：只对 `interpolation == 'idw'` 的实测场补。`circular_approx`（离线估算）那份是
    距离模型恒等式，标定必然得 k≡声明值、残差处处 0 —— 给它补一块等于替一次没发生的测量举证
    （见 `data_source.OfflineDataSource` 与 `tests/test_reach_calibration.py`）。
 ③ 逐字段证明：改动路径集合必须**恰好等于** `{caliber.reach_caliber_version, sampling.detour}`，
    其余任何一处不同就整份拒绝。分数、盲区、POI、等时圈、采样点、generated_at 都不许动。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent

FIXTURES: List[Path] = []
for sub, name in (("kaili.json", "kaili.json"),
                  ("kaili-ev2.json", "kaili-ev2.json"),
                  ("beijing-jinsong.json", "beijing-jinsong.json")):
    FIXTURES.append(BACKEND / "app" / "living_circle" / "fixtures" / name)
    FIXTURES.append(PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle" / sub)

sys.path.insert(0, str(BACKEND))
from app.living_circle.isochrone import detour_residual  # noqa: E402

ALLOWED_PATHS = {"caliber.reach_caliber_version", "sampling.detour"}


def _payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    """夹具既可能是裸 `living_circle` 载荷，也可能裹在报告外壳里 —— 两种都吃。"""
    return doc.get("living_circle", doc)


def _diff_paths(before: Any, after: Any, prefix: str = "") -> List[str]:
    """列出所有不同的路径（只到"键"这一层，数组按下标进不去的写法保持简单）。"""
    out: List[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            if k not in before or k not in after:
                out.append(f"{prefix}{k}")
            else:
                out.extend(_diff_paths(before[k], after[k], f"{prefix}{k}."))
    elif before != after:
        out.append(prefix.rstrip(".") or "<root>")
    return out


def build(f: Path) -> Tuple[str, str, Dict[str, Any], List[str]]:
    """返回 (原文, 尾随换行状态, 新文档, 改动路径集合)。

    尾随换行要**原样保留**：夹具是脚本写出来的，末尾有没有 `\\n` 是那个写口的习惯，
    我这里统一加一个就会让每份文件都多一处无意义 diff。
    """
    src = f.read_text(encoding="utf-8")
    doc = json.loads(src)
    lc = _payload(doc)
    trailing = "\n" if src.endswith("\n") else ""

    # ① 排版保真
    re_dumped = json.dumps(doc, indent=2, ensure_ascii=False)
    if re_dumped != src.rstrip("\n"):
        raise AssertionError(
            f"{f.name}: 重新序列化与原文件不一致（长度 {len(re_dumped)} vs {len(src.rstrip())}）"
            "⇒ 夹具写口用的格式与此处不同，硬写会把整份文件重排、diff 看不出改了啥。拒绝。")

    sampling, caliber = lc["sampling"], lc.get("caliber") or {}
    # ② 诚实闸
    if sampling.get("interpolation") != "idw":
        raise AssertionError(
            f"{f.name}: interpolation={sampling.get('interpolation')!r} 不是实测场 ⇒ 不该补标定块")

    center = tuple(lc["scene"]["center"])
    pts = [(p["lng"], p["lat"]) for p in sampling["points"]]
    mins = [p.get("minutes") for p in sampling["points"]]
    detour = detour_residual(
        center, pts, mins,
        speed_m_per_min=float(caliber["speed_m_per_min"]),
        declared_k=float(caliber["detour_k"]),
    )

    # 追加在两段末尾 ⇒ 只多两格，不重排既有键序
    sampling["detour"] = detour
    lc["caliber"]["reach_caliber_version"] = "rc-1"

    # ③ 逐字段证明：改动面必须恰好是那两个键
    changed = set(_diff_paths(json.loads(src), doc))
    if changed != ALLOWED_PATHS:
        raise AssertionError(
            f"{f.name}: 改动面超出允许集合 ⇒ 多了 {sorted(changed - ALLOWED_PATHS)}、"
            f"少了 {sorted(ALLOWED_PATHS - changed)}")
    return src, trailing, doc, changed


def main() -> int:
    apply = "--apply" in sys.argv
    print("（--check 模式：只核对与试算，不写盘）" if not apply else "（--apply：先全部核对，全过才写）")

    # 两趟：先把所有文件核对完并算出目标字节，**有任何一份不过就一份都不写**。
    # 写成"边验边写"会让第 5 份失败时前 4 份已经落盘，夹具的两本镜像就分叉了
    # —— 而镜像分叉正是 `test_fixture_mirror` 专门要抓的那种事故。
    pending: List[Tuple[Path, str]] = []
    errors: List[str] = []
    for f in FIXTURES:
        if not f.exists():
            errors.append(f"✗ {f.relative_to(PROJECT)}: 文件不存在")
            continue
        try:
            src, trailing, doc, _changed = build(f)
        except AssertionError as e:
            errors.append(f"✗ {e}")
            continue
        body = json.dumps(doc, indent=2, ensure_ascii=False) + trailing
        if body == src:
            errors.append(f"✗ {f.name}: 算出的内容与原文逐字相同 ⇒ 本次不会有任何生效")
            continue
        pending.append((f, body))
        lc = _payload(doc)
        d = lc["sampling"]["detour"]
        r = d["residual_min"] or {}
        print(
            f"✓ {f.relative_to(PROJECT)}｜k 标定 {d['detour_factor_measured']}"
            f"（声明 {d['declared_detour_k']}）｜入样 {d['points_used']}"
            f"｜剔除 {d['excluded']}｜残差 p50 {r.get('p50')} p90 {r.get('p90')} max {r.get('max')}"
            f"｜+{len(body) - len(src)} 字节")

    for line in errors:
        print(line)
    if errors:
        print(f"\n{len(errors)} 份未通过核对 ⇒ **一份都没写**（原子性）。")
        return 1
    if not apply:
        print(f"\n{len(pending)} 份全部通过核对。加 --apply 才写盘。")
        return 0
    for f, body in pending:
        f.write_text(body, encoding="utf-8")
    print(f"\n已写出 {len(pending)} 份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

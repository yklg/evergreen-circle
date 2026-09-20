"""lc_healthcheck.py 的负对照 —— 证明它的判据**真的会红**。

一条永远绿的检查没有判别力：它既不能证明数据没问题，也不能在数据出问题时拦住你。
所以这里对数据库**副本**注入两类"已知必须被抓住"的缺陷，断言体检脚本
退出码 = 1 且报出对应原因：

  1. `numeric` —— 可见报告内部数字不自洽（poi.in_circle 与类别求和对不上）
     期望命中：``数字不自洽``
  2. `era`     —— 现役区间内某份被 done 任务签发的报告违反几何契约
     （把盲区整体平移出可达区）
     期望命中：``写路径守卫失效``

**全程不触碰真库**：只读真库字节做 sha256 指纹，脚本结束前后比对自证未改动。
用法：``python skip/scripts/lc_healthcheck_selftest.py``（退出码 0 = 两类缺陷都被抓住）
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "app" / "data" / "verda.db"
HEALTHCHECK = Path(__file__).resolve().parent / "lc_healthcheck.py"

sys.path.insert(0, str(ROOT / "backend"))
from app.living_circle.report_contract import assess_geometry  # noqa: E402


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rows(db: Path):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = con.execute(
        "select report_id, data_origin, created_at, data from living_circle_reports"
    ).fetchall()
    tasks = con.execute(
        "select task_id, status, report_id from tasks where kind='living_circle'"
    ).fetchall()
    con.close()
    return out, tasks


def logical_fingerprint(db: Path) -> tuple[str, int, int]:
    """逻辑指纹（报告内容 + 任务状态）。

    为什么不用文件字节 sha256 作判据：真库正被后端以写连接持有，SQLite 会在 WAL 超阈值时
    **自动 checkpoint**，于是 verda.db 的字节会合法地变化——拿它当"未改动"判据会随机误报。
    逻辑指纹与物理布局无关，才是"数据没被改"的正确判据；字节 sha256 另行输出供人工比对。
    """
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    h = hashlib.sha256()
    rws = con.execute(
        "select report_id, data from living_circle_reports order by report_id"
    ).fetchall()
    tks = con.execute(
        "select task_id, status, coalesce(report_id,'') from tasks order by task_id"
    ).fetchall()
    con.close()
    for r in rws:
        h.update(repr(r).encode())
    for t in tks:
        h.update(repr(t).encode())
    return h.hexdigest(), len(rws), len(tks)


def run_healthcheck(db: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HEALTHCHECK), "--db", str(db)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return p.returncode, p.stdout + p.stderr


def pick_era_target(db: Path):
    """挑一份"现役区间内、合规、且被 done 任务签发"的报告作为破坏目标。

    优先选**有盲区**的（破坏盲区几何最贴近真实事故形态）；全都没盲区时退回任何一份，
    由 ``tamper`` 改用"把圈内点标成圈外"这一等效的几何违约手段。
    """
    rws, tasks = rows(db)
    done_reports = {t["report_id"] for t in tasks if t["status"] == "done" and t["report_id"]}
    live_ok = []
    for r in rws:
        lc = (json.loads(r["data"]) or {}).get("living_circle") or {}
        if r["data_origin"] == "live" and assess_geometry(lc).ok and r["report_id"] in done_reports:
            live_ok.append((bool(lc.get("blindspots")), r["created_at"], r["report_id"]))
    if not live_ok:
        return None
    with_bs = sorted((x for x in live_ok if x[0]), key=lambda x: x[1])
    if with_bs:
        return with_bs[0][2]           # 最早一份"有盲区"的合规 live
    return sorted(live_ok, key=lambda x: x[1])[0][2]


def snapshot(src: Path, dst: Path) -> None:
    """对数据库做**一致性快照** —— 必须用 ``VACUUM INTO``。

    踩过的坑：直接 ``shutil.copy2(verda.db)`` 会**静默丢掉 WAL 里尚未 checkpoint 的提交**。
    实测真库 verda.db = 2.1MB、verda.db-wal = 4.2MB，只拷 ``.db`` 拿到的副本里
    最近 3 份 live 报告集体消失（副本 12 行 vs 真实 15 行），而文件大小一模一样——
    这种"看起来成功的备份"比失败更危险。
    ``VACUUM INTO`` 只读源库、产出**自包含**副本（WAL 内容已并入），是 SQLite 官方推荐做法。
    """
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        if dst.exists():
            dst.unlink()
        con.execute("vacuum into ?", (str(dst),))
    finally:
        con.close()


def tamper(src: Path, dst: Path, *, mode: str, target: str) -> None:
    snapshot(src, dst)
    con = sqlite3.connect(str(dst))
    payload = json.loads(
        con.execute("select data from living_circle_reports where report_id=?", (target,)).fetchone()[0]
    )
    lc = payload["living_circle"]
    if mode == "numeric":
        lc["poi"]["in_circle"] = int(lc["poi"]["in_circle"]) + 1        # 与类别求和对不上
    elif mode == "era":
        bs = lc["blindspots"]
        if bs:
            for b in bs:                                                # 整体平移 ~3km，越出可达区
                for axis, delta in ((0, 0.030), (1, 0.020)):
                    c = b.get("center")
                    if isinstance(c, list) and len(c) >= 2:
                        c[axis] = float(c[axis]) + delta
                    poly = (b.get("polygon") or {}).get("coordinates") or []
                    for ring in poly:
                        for pt in ring:
                            pt[axis] = float(pt[axis]) + delta
        else:
            # 等效违约：把圈内点标成圈外（Q2 本体 —— 圈外点不该被展示/计分）
            pts = lc.get("poi", {}).get("points") or []
            if not pts:
                raise SystemExit(f"{target} 既无盲区也无点位，无法做 era 负对照")
            pts[0]["in_circle"] = False
    else:
        raise SystemExit(f"未知模式 {mode}")
    con.execute(
        "update living_circle_reports set data=? where report_id=?",
        (json.dumps(payload, ensure_ascii=False), target),
    )
    con.commit()
    con.close()


def main() -> int:
    if not DB.exists():
        print(f"❌ 真库不存在：{DB}")
        return 1
    real_before = sha256(DB)
    log_before, n_rep, n_tsk = logical_fingerprint(DB)

    era_target = pick_era_target(DB)
    if not era_target:
        print("❌ 找不到'现役区间内、合规、且被 done 任务签发'的报告，无法构造 era 负对照")
        return 1

    rws, _ = rows(DB)
    visible = []
    for r in rws:
        lc = (json.loads(r["data"]) or {}).get("living_circle") or {}
        if assess_geometry(lc).ok:
            visible.append(r["report_id"])
    if not visible:
        print("❌ 真库没有可见报告，无法构造 numeric 负对照")
        return 1

    cases = [
        ("numeric", visible[0], "数字不自洽"),
        ("era", era_target, "写路径守卫失效"),
    ]

    failures = 0
    with tempfile.TemporaryDirectory() as td:
        for mode, target, expect in cases:
            tmp = Path(td) / f"negctl-{mode}.db"
            tamper(DB, tmp, mode=mode, target=target)
            code, out = run_healthcheck(tmp)
            hit = expect in out
            ok = code == 1 and hit
            print(f"\n── 负对照 [{mode}] 目标 {target} ──")
            print(f"   期望：退出码=1 且报出「{expect}」")
            print(f"   实得：退出码={code}  命中={hit}")
            if ok:
                print("   ✅ 判据有效（正确判红）")
            else:
                failures += 1
                print("   ❌ 判据失效（漏判）—— 健康检查对这类缺陷无判别力")
                for line in out.splitlines():
                    if "异常" in line or "❌" in line:
                        print(f"      | {line.strip()}")

    real_after = sha256(DB)
    log_after, n_rep2, n_tsk2 = logical_fingerprint(DB)
    unchanged = (log_before == log_after) and (n_rep, n_tsk) == (n_rep2, n_tsk2)
    byte_same = real_before == real_after
    print(f"\n真库数据未被改动：{'✅ 逻辑指纹一致' if unchanged else '❌ 逻辑指纹变化！'}"
          f"（报告 {n_rep}→{n_rep2} 条，任务 {n_tsk}→{n_tsk2} 条）")
    print(f"  逻辑 before = {log_before[:16]}…  after = {log_after[:16]}…")
    # 字节 sha256 仅供人工比对：后端持写连接时会自动 checkpoint WAL，verda.db 字节合法变化。
    print(f"  [信息] verda.db 字节 sha256 {real_before[:16]}… → {real_after[:16]}…"
          f"（{'未变' if byte_same else '已变，通常是 WAL 自动 checkpoint，非本脚本所致'}）")

    if failures or not unchanged:
        print(f"\n❌ 负对照未全部通过（{failures} 项漏判）")
        return 1
    print("\n✅ 两类缺陷均被抓住 —— 体检脚本的判据具备判别力")
    return 0


if __name__ == "__main__":
    sys.exit(main())

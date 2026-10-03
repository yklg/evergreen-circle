"""「精报替换粗报」这条链的休眠声明 + 留痕欠账台账（计划 `tmp/plan-report-id-dormancy.md`）。

先更正前提（这条链今天**跑不到**，所以本文件不加字段）：

- 全仓唯一会删存量报告的那句 `db.delete_living_circle_reports_for_scene(scene_key)` 住在
  `pipeline/living_circle.py:531`，它在 `_finalize_living_report(..., replace_scene=True)` 里面；
- `replace_scene=True` 的**唯一**设置者是 `_schedule_refine`（同文件 :536），而它在 `app/**` 里
  **零生产调用点**（`:249` 与 `repository.py:247` 的注释也各自自陈这件事）⇒ 今天没有任何路径
  能删掉任何一份报告，用户 09-29 拍的「每次体检各留一份」比当时描述的现状更强。

三条判据各守一件事，别互相顶替：

- **A 结构面**（今天即绿）：`app/**` 里对 `_finalize_living_report` 的每个调用点，`replace_scene`
  只能是字面 `False`（关键字或第三位实参都算）。这条拦的是"将来谁把它顺手改成 True"。
- **B 行为面**（今天即绿）：走用户入口连跑两次同参体检 ⇒ 第一份 `report_id` **必须仍可取**、
  同场景行数只增不减。这是 D-4 在**真能跑到的路径**上的最小表达，与 U31
  （`test_pipeline_living_circle.py:395`，走"缓存命中但落库缺失"的兜底口）分工互补。
- **C 留痕欠账**（`xfail(strict=True)`）：那条链真接上时，替换必须留下被替换那份的 id。
  今天没有这个字段 ⇒ 必红 ⇒ 挂 strict；谁实现了它，strict 会转 XPASS 当场报错逼摘标。

⚠️ 效力上限（写在这里是因为它容易被读成"已经安全"）：A/B 只证**今天删不掉**，
不证**将来接上时安全** —— 后半截是 C 那笔账，而 C 只能由台架驱动（生产没有入口走到它）。
三条都跑在临时库上，绝不碰 `app/data/verda.db`。
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from app.core import db
from app.core.pipeline.living_circle import (
    _finalize_living_report,
    _schedule_refine,
    _scene_key,
    create_living_circle_task,
)
from app.living_circle.data_source import CheckParams, Repository

# 复用同目录既有的 live 分支驱动件（与 U18/U31/M2 同一套，不留第二份驱动件）
from test_pipeline_living_circle import (
    KAILI_CENTER,
    PipelineStubBaidu,
    _done_id,
    _live_params,
    _live_source,
    _row_count_for_scene,
    _run_pipeline,
)

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
TARGET = "_finalize_living_report"


def _non_false_replace_scene_calls(tree: ast.AST) -> list[int]:
    """找出把 `replace_scene` 传成"非字面 False"的调用行号。

    两种写法都拦：① 关键字 `replace_scene=True` / `replace_scene=某变量`；
    ② **位置实参第三位**（`_finalize_living_report(a, b, True)` —— 那个形参不是 keyword-only，
    只盯关键字就会漏掉这种，而它改起来同样静默）。
    判据落在**调用形状**上而不是字符串上：写成一行的 grep 会被 `flag = True` 再传 `flag` 绕开。
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if fname != TARGET:
            continue
        for kw in node.keywords:
            if kw.arg == "replace_scene" and not (isinstance(kw.value, ast.Constant)
                                                  and kw.value.value is False):
                hits.append(node.lineno)
        if len(node.args) >= 3 and not (isinstance(node.args[2], ast.Constant)
                                        and node.args[2].value is False):
            hits.append(node.lineno)
    return sorted(set(hits))


def _enclosing_map(tree: ast.AST) -> dict[int, str]:
    """行号 → 所在的**最外层**具名函数（嵌套函数不覆盖外层）。

    为什么需要它，也要为什么取外层：判据说的是"这唯一一处替换面住在哪个函数里"，行号本身不说明
    归属，写成常量（`:557`）则上面挪一行就红。取最外层是因为第一版取了最内层，结果解析出来是
    `_run`（`_schedule_refine` 里那个 `async def _run`）—— 说的是同一个地方，但断言的名字变了，
    而"住在 refine 里"这件事本来就该由最外层那个名字来表述。
    """
    owner: dict[int, str] = {}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if hasattr(node, "lineno"):
                owner.setdefault(node.lineno, fn.name)
    return owner


# ── A · 结构面：先证扫描器不是恒 0，再跑真树 ──────────────────────────

def test_replace_scene_scanner_proves_itself_before_being_trusted():
    """正半（**必须先跑**）：同一段样本源码里两种"改成 True"的写法都要被点出来。

    没有这一条，下面那句"真树 0 命中"就什么都不是 —— 一个永远返回空列表的扫描器同样"全绿"，
    而那正是本仓反复踩过的恒绿闸。
    """
    sample = """
flag = True
_finalize_living_report(data, key)                      # 缺省 False ⇒ 不该点
_finalize_living_report(data, key, replace_scene=False)  # 字面 False ⇒ 不该点
_finalize_living_report(data, key, replace_scene=True)   # 关键字写法 ⇒ 该点
_finalize_living_report(data, key, replace_scene=flag)   # 先算变量再传 ⇒ 该点
_finalize_living_report(data, key, True)                 # 位置实参第三位 ⇒ 该点
_other_report_fn(data, key, True)                        # 不是目标函数 ⇒ 不该点
"""
    hits = _non_false_replace_scene_calls(ast.parse(sample))
    assert len(hits) == 3, f"扫描器点名数不对（期望 3，实测 {hits}）⇒ 下面那条'真树 0'不可信"
    # 归属也要有敏感性对照：嵌套函数里的调用点必须记到**最外层**那个名字（第一版记成内层，
    # 真树上就解析成了 `_run`，与它声称的 `_schedule_refine` 对不上 —— 那是判据的形状错）。
    nested = ast.parse("""
def outer():
    def inner():
        _finalize_living_report(d, k, True)
    return inner
""")
    nested_hits = _non_false_replace_scene_calls(nested)
    assert len(nested_hits) == 1, nested_hits
    assert _enclosing_map(nested)[nested_hits[0]] == "outer", _enclosing_map(nested)


def test_the_only_scene_replacer_lives_inside_the_dormant_refiner():
    """负半：`app/**` 里开着替换语义的调用点**有且只有一处**，且它必须住在 `_schedule_refine` 体内。

    为什么不是"零处"：`_schedule_refine` 自己就是那个替换者，"零处"这条永远红（第一版就写成了
    零处，跑出来红在 `living_circle.py:557` —— 那是判据写错，不是代码错）。正确的说法是两半合起来
    才成立：**唯一**一处替换面 + 它所在的那个函数**零生产调用点**（下面那条单独钉)⇒ 今天不可达。
    敏感性：谁再补一处（哪怕也在 refine 里），或把 refine 里那处搬出去 ⇒ 当场红。
    """
    offenders: list[tuple[str, int, str]] = []
    scanned = 0
    for py in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        scanned += 1
        owner = _enclosing_map(tree)
        for lineno in _non_false_replace_scene_calls(tree):
            offenders.append((str(py.relative_to(APP_DIR.parent)), lineno, owner.get(lineno, "<top>")))
    assert scanned > 50, f"扫描面塌了（只解析到 {scanned} 个文件）⇒ 这条判据没在覆盖生产码"
    assert len(offenders) == 1, (
        f"替换面应当恰有一处（挪走/加第二处 = 体检链可能真去删同场景存量，与 D-4「每次体检各留一份」相冲）："
        f"{offenders}")
    where, lineno, enclosing = offenders[0]
    assert enclosing == "_schedule_refine", (
        f"那唯一一处替换面搬进了 `{enclosing}`（原住 `_schedule_refine`）⇒ 若那个函数有了调用者，"
        f"删存量就变成可达路径：{where}:{lineno}")


def test_the_only_replacer_has_no_production_caller():
    """休眠声明的正半 + 负半：`_schedule_refine` 里确实写着 `replace_scene=True`，但**没人调它**。

    为什么要两面：只断"没人调"会连"函数被删了"一起判成通过（那是把这条账悄悄勾掉）；
    所以先证那个 True 还在（缺陷面仍在，只是走不到），再证它在 `app/**` 里零调用点。
    """
    refine_src = (APP_DIR / "core" / "pipeline" / "living_circle.py").read_text(encoding="utf-8")
    tree = ast.parse(refine_src, filename="living_circle.py")
    # 正半：True 还写在 _schedule_refine 的函数体里
    bodies = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_schedule_refine"]
    assert len(bodies) == 1, f"预期只有一处 `_schedule_refine` 定义，实测 {len(bodies)}"
    inner = [n for n in ast.walk(bodies[0])
             if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == TARGET
             and any(k.arg == "replace_scene" and getattr(k.value, "value", None) is True
                     for k in n.keywords)]
    assert len(inner) == 1, f"`_schedule_refine` 里的替换面应当恰有一处，实测 {len(inner)}"

    # 负半：它在 app/** 里零调用点（"唯一调用者是测试台架"这句话现在有机器可见的证据）
    callers = []
    for py in sorted(APP_DIR.rglob("*.py")):
        if py.name == "living_circle.py" and py.parent.name == "pipeline":
            continue      # 定义处与它自己的函数体不算调用者
        t = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(t):
            if isinstance(node, ast.Call):
                if getattr(node.func, "id", getattr(node.func, "attr", "")) == "_schedule_refine":
                    callers.append(f"{py.relative_to(APP_DIR.parent)}:{node.lineno}")
    assert not callers, (
        f"这条链被接上了 ⇒ 本文件的休眠声明作废，必须同时把 C 那条 xfail 摘掉并真加留痕字段：{callers}")


# ── B · 行为面：走用户入口，两份都要在 ──────────────────────────

def test_two_checkups_keep_both_rows(monkeypatch):
    """连跑两次同参体检 ⇒ 第一份 `report_id` 仍可取，同场景行数只增不减（D-4 的最小表达）。

    U31 走的是"缓存命中但落库缺失"那个兜底口，这条走正常口：两条合起来才把写侧两个入口都盖住。
    两次都吃桩（`PipelineStubBaidu`），零真实外呼。
    """
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-D4")
    scene_key = _scene_key(params)

    rid1 = _done_id(_run_pipeline(create_living_circle_task(params)))
    before = _row_count_for_scene(scene_key)
    assert db.get_living_circle_report(rid1) is not None, "前置不成立：第一份根本没落库"

    rid2 = _done_id(_run_pipeline(create_living_circle_task(params)))
    after = _row_count_for_scene(scene_key)

    assert after >= before, f"第二次体检把同场景的行删了（{before} → {after}）⇒ 撞 D-4"
    assert db.get_living_circle_report(rid1) is not None, (
        f"第一次那份（{rid1}）在第二次体检后读不到了 ⇒ 存量被静默替换，"
        f"用户手里的链接会指向不存在的行（第二次给的 id={rid2}）")


# ── C · 留痕欠账：接上那天必须补上被替换那份的 id ────────────────────

def _as_check(params: dict) -> CheckParams:
    """把 `_live_params()` 的 dict 落成 `CheckParams`（与 M2 那条同一造法，不留第二份）。"""
    return CheckParams(scene_name=params["scene_name"], city=params["city"],
                       address=params["address"], center=tuple(params["center"]),
                       study_radius_m=params["study_radius_m"],
                       sample_profile=params["sample_profile"],
                       travel_mode=params["travel_mode"])


@pytest.mark.xfail(
    strict=True,
    reason="欠账（#32 同批必做 · 用户 10-03 拍「只做台账判据，不加字段」）：精报真替换粗报时，"
           "新报告里没有任何字段说明它顶掉了哪一份 ⇒ 用户开着的链接指向已被删的行且无从追溯。"
           "实现那轮本用例会自动转 XPASS，届时必须摘标并把字段形状（顶层 or report['replaces']）一起定。",
)
def test_refine_replacement_records_the_superseded_report_id(monkeypatch):
    """留痕判据：`_schedule_refine` 成功替换时，精报必须带着被它替换掉那份的 id。

    ⚠️ 驱动的是**台架路径**（直接调 `_schedule_refine`）—— 生产今天没有入口能走到它，
    这正是本文件要记成的事实。前置三行不是装饰：替换真发生了才谈得上留痕，否则这条会红在
    无关的地方（挂 xfail 前用 `--runxfail` 单独跑过，确认红的种类是"缺这个键"）。
    """
    coarse_stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(coarse_stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-留痕")
    scene_key = _scene_key(params)
    rid1 = _done_id(_run_pipeline(create_living_circle_task(params)))
    assert db.get_living_circle_report(rid1) is not None

    check = _live_params(scene_name="凯里老街-留痕")

    async def _drive():
        # `_schedule_refine` 内部用 `asyncio.create_task` ⇒ 必须在**运行中的事件循环**里调它
        # （M2 同一形状；第一版在外面造 task 再 await，RuntimeError 被 xfail 一起吞成"预期失败"，
        #  warning 里那句 `coroutine ... was never awaited` 就是当时的现形）。
        task = _schedule_refine(PipelineStubBaidu(KAILI_CENTER), _as_check(check), Repository(),
                                scene_key, [], "standard")
        await task

    asyncio.run(_drive())

    rows = _row_count_for_scene(scene_key)
    latest = db.get_latest_report_id_for_scene(scene_key)
    assert latest is not None and latest != rid1, (
        f"前置不成立：这台架没能造出「替换确实发生」的形状（rows={rows}, latest={latest}）")
    assert db.get_living_circle_report(rid1) is None, (
        "前置不成立：粗报行还在 ⇒ 这条测的就不是留痕了")

    refined = db.get_living_circle_report(latest)
    doc = refined.get("living_circle") or {}
    superseded = refined.get("replaces_report_id") or doc.get("replaces_report_id")
    assert superseded == rid1, (
        f"精报替换了粗报却没留下被顶替那份的 id（rid1={rid1}）⇒ 用户开着的链接指向不存在的行")

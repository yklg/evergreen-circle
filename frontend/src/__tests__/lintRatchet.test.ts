/**
 * lint 棘轮守卫（计划台账 2.9 的结案件）
 *
 * ## 它替换的是什么
 *
 * `.github/workflows/ci.yml` 的 `frontend` job 原本第一步就是阻断的 `npm run lint`，
 * 而已入库码有 106 个 eslint error（大头在 `src/dev/*Probe.tsx` 探针）⇒ step 按序终止，
 * 后面的 `vitest`（1027 例）与 `build` 在 CI 里**一行都没跑过**。
 * 现在：`npm run lint` 留作**非阻断诊断**，阻断权交给本条棘轮 —— 存量不追究，**新增必红**。
 * 判据分解在 `helpers/lintRatchet.ts`，逐文件账本在 `fixtures/lintRatchetBaseline.json`。
 *
 * ## 为什么把 spawn eslint 放进测试里（而不是单独一个 npm script）
 *
 * 单独脚本需要有人在 CI 里记得调它，而"记得调"正是这次要修的病；进 vitest 就跟着
 * `npm run test` 一起跑，CI 与本地同一条路径。代价实测 **+5s 墙钟**（`eslint . -f json` ≈ 5s，
 * 全套原本 15s）—— 比一道会被人绕过的闸门便宜。整个套件只跑一次 eslint（`beforeAll` 缓存）。
 *
 * ## 正对照与"不得静默报绿"
 *
 * 第一个 describe 不碰进程，用合成报告证明判据本身有效（分流、超线、欠线、新文件）；
 * 第二个 describe 真跑 eslint，先证明**报告非空、根目录认得、git 可列文件、账本里的路径 git 都认得** ——
 * 任一失效都直接红，不许把"取不到数据"报成绿（同后端 `test_guard_selfvalidation` 的口径）。
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  diffAgainstBaseline,
  tallyByTrackedFile,
  type LintFileReport,
  type TrackedTally,
} from './helpers/lintRatchet'
import baseline from './fixtures/lintRatchetBaseline.json'

const ROOT = fileURLToPath(new URL('../../', import.meta.url))

describe('棘轮判据自证（合成报告，不起进程）', () => {
  const tracked = new Set(['src/a.ts', 'src/b.tsx'])

  it('正对照：已跟踪与未跟踪分流，路径归一只认仓内相对路径', () => {
    const reports: LintFileReport[] = [
      { filePath: `${ROOT}src/a.ts`, errorCount: 3 },
      { filePath: `${ROOT}src/b.tsx`, errorCount: 1 },
      { filePath: `${ROOT}src/wip.ts`, errorCount: 7 }, // 在制品：进台账不进判据
      { filePath: `${ROOT}src/clean.ts`, errorCount: 0 },
    ]
    const tally = tallyByTrackedFile(reports, ROOT, tracked)
    expect(tally.perFile).toEqual({ 'src/a.ts': 3, 'src/b.tsx': 1 })
    expect(tally.untrackedErrors).toBe(7)
    expect(tally.filesScanned).toBe(4)
  })

  it('新增违规必红；基线里没记的新文件按额度 0 处理', () => {
    const d = diffAgainstBaseline({ perFile: { 'src/a.ts': 4, 'src/new.ts': 1 } }, { 'src/a.ts': 3 })
    expect(d.above).toEqual([
      { file: 'src/a.ts', budget: 3, now: 4 },
      { file: 'src/new.ts', budget: 0, now: 1 },
    ])
  })

  it('债变少也红：逼着同笔把基线改小，不留"以后可以涨回去"的空档', () => {
    const d = diffAgainstBaseline({ perFile: { 'src/a.ts': 2 } }, { 'src/a.ts': 3, 'src/gone.ts': 5 })
    expect(d.below).toEqual([
      { file: 'src/a.ts', budget: 3, now: 2 },
      { file: 'src/gone.ts', budget: 5, now: 0 },
    ])
    expect(d.above).toEqual([])
  })

  it('恰好等于基线 ⇒ 两向都无违例（这条不成立时下面真跑那条就是空判）', () => {
    const d = diffAgainstBaseline({ perFile: { 'src/a.ts': 3 } }, { 'src/a.ts': 3 })
    expect(d).toEqual({ above: [], below: [] })
  })
})

describe('棘轮真跑（eslint . -f json × git ls-files × 账本）', () => {
  type Run = { status: number | null; stdout: string; stderr: string }

  const run = (cmd: string, args: string[], maxBuffer = 64 * 1024 * 1024): Run => {
    const r = spawnSync(cmd, args, { cwd: ROOT, encoding: 'utf8', maxBuffer })
    return { status: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' }
  }

  /**
   * eslint 有 error 时退出码非 0 —— 那**不是**这一步的失败，判据在报告里；
   * 所以走 spawnSync 读 stdout，不用会抛异常的 execFileSync。
   */
  const eslintReport = (): LintFileReport[] => {
    const bin = `${ROOT}node_modules/eslint/bin/eslint.js`
    if (!existsSync(bin)) throw new Error(`取不到 eslint：${bin}（npm ci 没装好 ⇒ 本条无权报绿）`)
    const r = run(process.execPath, [bin, '-f', 'json', '.'])
    if (!r.stdout.trim()) throw new Error(`eslint 无输出（status=${r.status}）：${r.stderr.slice(0, 400)}`)
    return JSON.parse(r.stdout) as LintFileReport[]
  }

  const gitTracked = (): Set<string> => {
    const r = run('git', ['ls-files', '-z'])
    if (!r.stdout.trim()) throw new Error('git ls-files 空输出 ⇒ 无法区分已入库与在制品，判据作废')
    return new Set(r.stdout.split('\0').filter(Boolean))
  }

  let tally: TrackedTally | null = null
  beforeAll(() => {
    tally = tallyByTrackedFile(eslintReport(), ROOT, gitTracked())
  }, 180_000)

  it('取数自证：扫到了文件、账本非空、且账本里每条路径 git 都认得', () => {
    expect(tally!.filesScanned).toBeGreaterThan(100)
    expect(Object.keys(baseline.perFile).length).toBeGreaterThan(10)
    const stale = Object.keys(baseline.perFile).filter((f) => !gitTracked().has(f))
    expect(stale, `账本里记了 git 不认的路径：${stale.join(', ')}`).toEqual([])
  })

  it('逐文件 error 数 == 账本（只减不增）', () => {
    const { above, below } = diffAgainstBaseline(tally!, baseline.perFile as Record<string, number>)

    // 口径对账：逐文件合计必须等于账本合计，防"每条都涨但总数看着没变"
    const sum = Object.values(tally!.perFile).reduce((a, b) => a + b, 0)
    expect(sum, `实测已入库 error 合计 ${sum} ≠ 账本 ${baseline.totalErrorsInTrackedFiles}`).toBe(
      baseline.totalErrorsInTrackedFiles,
    )

    if (above.length) {
      throw new Error(
        `lint 棘轮：新增违规 ${above.length} 个文件（已入库共 ${sum} error；另有在制品 ${tally!.untrackedErrors} 条不计入判据）。\n` +
          `必须先消掉，账本数字不许往上调：\n` +
          above.map((v) => `    ${v.file}: 账本 ${v.budget} → 实测 ${v.now}`).join('\n'),
      )
    }
    if (below.length) {
      throw new Error(
        `lint 棘轮：${below.length} 个文件的债比账本少 —— 还了债请**同笔把 fixtures/lintRatchetBaseline.json 改小**（或删除条目并同步 totalErrorsInTrackedFiles）：\n` +
          below.map((v) => `    ${v.file}: 账本 ${v.budget} → 实测 ${v.now}`).join('\n'),
      )
    }
  })
})

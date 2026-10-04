/**
 * lint 棘轮的**纯判据**（不起进程、不读源码），真跑 eslint 的那一半在 `lintRatchet.test.ts`。
 *
 * ## 为什么要有这道棘轮
 *
 * `npm run lint` 在 HEAD 的已入库码里有 **106 个 error**（2026-10-04 实测），其中一半在
 * `src/dev/*Probe.tsx` 这些调试探针上。让它继续当 CI 闸门 = `frontend` job 的第一步永远红，
 * 而 GitHub Actions 的 step **按序终止** ⇒ 后面的 vitest 与 build 一行都不跑，1027 例在 CI
 * 眼里等于没跑。把它整条撤掉 = 新增违规从此无人看守。
 * ⇒ 折中：`npm run lint` 降级为**非阻断诊断**，阻断权交给这里这条**只减不增**的棘轮。
 *
 * ## 判据形状（逐文件，不是只看总数）
 *
 * 用一个总数会漏掉"修了 A 文件的 2 条、同时在 B 文件新加 2 条"这种互相抵消；
 * 逐文件记账还顺便把债落在哪一页写清楚了。规则只有两条，且都红：
 *  - `now > budget` ⇒ 新增违规，必须自己消掉；
 *  - `now < budget` ⇒ 债变少了，**要求把基线数字改小**（同 `tailwindClassIntegrity` 里
 *    `KNOWN_PROBE_DANGLING` 的只减不增手法）。留着旧数字等于允许它哪天悄悄涨回去。
 *
 * ## 为什么排除未跟踪文件
 *
 * 用户工作区里的在制品（`git status` 里的 `??`）不该算进**这条分支的债**，
 * 也不该由我替他改。所以判据只统计 `git ls-files` 认得的已入库文件；
 * 未跟踪文件的 error 数照样进台账打印，只是不参与红绿。CI 里 checkout 全为已跟踪，
 * 两种口径同值。
 */

/** eslint `-f json` 里我们真正用到的两个字段（不引 eslint 类型包，避免版本耦合） */
export interface LintFileReport {
  filePath: string
  errorCount?: number
}

export interface TrackedTally {
  /** 相对 eslint 运行根的 posix 路径 → 该文件的 error 数（只含已跟踪文件） */
  perFile: Record<string, number>
  /** 未跟踪文件（在制品）的 error 合计：进台账、不进判据 */
  untrackedErrors: number
  /** 报告里出现过的文件数（正对照用：为 0 说明 eslint 根本没跑到东西） */
  filesScanned: number
}

export interface Violation {
  file: string
  budget: number
  now: number
}

export interface RatchetDiff {
  /** 超出基线的文件（含"基线里没有 = 额度 0"的新文件） */
  above: Violation[]
  /** 低于基线的文件：必须把基线改小或删除条目 */
  below: Violation[]
}

/**
 * 把 eslint 报告的绝对路径换成仓内相对路径，并按"是否已跟踪"分流。
 * `tracked` 传 `git ls-files` 的结果（同样 posix 相对路径）。
 */
export function tallyByTrackedFile(
  reports: LintFileReport[],
  rootAbs: string,
  tracked: ReadonlySet<string>,
): TrackedTally {
  const perFile: Record<string, number> = {}
  let untrackedErrors = 0
  for (const r of reports) {
    const errors = r.errorCount ?? 0
    if (errors === 0) continue
    const rel = toRel(r.filePath, rootAbs)
    if (tracked.has(rel)) perFile[rel] = (perFile[rel] ?? 0) + errors
    else untrackedErrors += errors
  }
  return { perFile, untrackedErrors, filesScanned: reports.length }
}

function toRel(absolute: string, rootAbs: string): string {
  const sep = absolute.includes('\\') ? '\\' : '/'
  const root = rootAbs.replace(/[\\/]$/, '')
  const rest = absolute.startsWith(root + sep) ? absolute.slice(root.length + 1) : absolute
  return rest.split(sep).join('/')
}

/** 逐文件比对基线；基线缺项按额度 0 处理（新出现的违规文件不会因为"没记账"而溜过去） */
export function diffAgainstBaseline(
  tally: Pick<TrackedTally, 'perFile'>,
  baseline: Readonly<Record<string, number>>,
): RatchetDiff {
  const above: Violation[] = []
  const below: Violation[] = []
  const files = new Set([...Object.keys(tally.perFile), ...Object.keys(baseline)])
  for (const file of [...files].sort()) {
    const now = tally.perFile[file] ?? 0
    const budget = baseline[file] ?? 0
    if (now > budget) above.push({ file, budget, now })
    else if (now < budget) below.push({ file, budget, now })
  }
  return { above, below }
}

export const formatViolations = (list: Violation[]): string =>
  list.map((v) => `    ${v.file}: 基线 ${v.budget} → 实测 ${v.now}`).join('\n')

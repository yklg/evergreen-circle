/**
 * textBrief.ts —— 全仓库唯一的「长句变短」入口（纯函数、零依赖、可单测）。
 *
 * 约束（见 报告章节导图与目录跳转修复计划.md §6.6）：
 *  - L1′：输出必须是原文的连续子串（允许结尾省略号）—— 不改写、不摘要、不抽实体；
 *  - L2：输出不得含内部编号（claim_id `c_xxx` / evidence_ids `e_xxx` / author `L2-001`）；
 *  - 预算：默认 ≤34 字，容差 SLACK=6（实测拐点：省略号 15→2 条，仅 +280px）。
 *
 * 方法：按中文分句边界（，。；：、,;: 与破折号）抽取语义单元，保留原标点；
 *      兜底 safeCut（不切断数字/小数、不落进未闭合括号、回退到最近分句边界）。
 */

/** 引用剥离：覆盖三种真实形态 —— 单个 [e_x]、连写 [e_x][e_y]、逗号并列 [e_a,e_b,e_z]（全/半角括号） */
export const REF_RE =
  /\s*[【[]\s*e_[0-9a-f]{6,12}(?:\s*[,，]\s*e_[0-9a-f]{6,12})*\s*[】\]]/g

export function stripRefs(s: string): string {
  return String(s).replace(REF_RE, '').trim()
}

export const BRIEF_BUDGET = 34
export const BRIEF_SLACK = 6

/** 安全截断：不切断数字/小数点，不落在未闭合括号内，回退到最近的分句边界 */
export function safeCut(s: string, n: number): string {
  if (s.length <= n) return s
  let p = n - 1
  while (p > 0 && /[\d.]/.test(s[p])) p--
  let d = 0
  for (let i = 0; i < p; i++) {
    if ('（('.includes(s[i])) d++
    else if ('）)'.includes(s[i])) d = Math.max(0, d - 1)
  }
  if (d > 0) {
    const o = Math.max(s.lastIndexOf('（', p), s.lastIndexOf('(', p))
    if (o > 4) p = o
  }
  const b = Math.max(
    s.lastIndexOf('，', p),
    s.lastIndexOf('、', p),
    s.lastIndexOf('：', p),
    s.lastIndexOf('；', p)
  )
  if (b > p - 14 && b > 4) p = b
  return s.slice(0, p).trim() + '…'
}

/** 分段并保留每段自己的尾随标点（不改写顿号→逗号）；识别破折号 */
const SEG_RE_SRC = '([^，。；：、,;:\\u2014]+)([，。；：、,;:\\u2014]*)|(——|—|:)'

interface Seg {
  text: string
  sep: string
}

export function segments(t: string): Seg[] {
  const out: Seg[] = []
  const re = new RegExp(SEG_RE_SRC, 'g')
  let m: RegExpExecArray | null
  while ((m = re.exec(t)) !== null) {
    if (m[3]) {
      if (out.length) out[out.length - 1].sep += m[3]
      continue
    }
    if (!m[1]) continue
    out.push({ text: m[1].trim(), sep: m[2] || '' })
    if (re.lastIndex >= t.length) break
  }
  return out
}

/**
 * 长句 → 短句（原文子串）。
 * 规则：
 *  ① 完整首句在预算+容差内则整句保留；后续分句在预算内继续并入；
 *  ② 并入后超预算但首段偏短（<0.8×预算）→ 宁可整段并入（容差内）也不切在「14/18-20m」中间；
 *  ③ 首段过短（<0.6×预算，时间状语等）→ 截取下一段续接，避免只剩「未来1-2年」碎片。
 */
export function briefText(raw: string, budget: number = BRIEF_BUDGET): string {
  const t = stripRefs(raw).replace(/\s+/g, ' ').trim()
  if (!t) return ''
  if (t.length <= budget) return t
  const buy = budget + BRIEF_SLACK
  const segs = segments(t).filter((s) => s.text)
  if (!segs.length) return safeCut(t, budget)
  let out = segs[0].text
  if (out.length <= buy) {
    for (let i = 1; i < segs.length; i++) {
      const sep = segs[i - 1].sep || '，'
      const cand = out + sep + segs[i].text
      if (cand.length <= budget) {
        out = cand
        continue
      }
      if (cand.length <= buy && out.length < budget * 0.8) {
        out = cand
        break
      }
      const room = budget - out.length - sep.length
      if (out.length < budget * 0.6 && room >= 10) {
        out = out + sep + safeCut(segs[i].text, room)
      }
      break
    }
  }
  return out.length > buy ? safeCut(out, budget) : out
}

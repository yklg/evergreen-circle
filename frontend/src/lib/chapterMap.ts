/**
 * chapterMap.ts —— 「本章内容结构」的业务层：这一章该显示什么、怎么分支、什么时候降级。
 *
 * 与 textBrief.ts 的分工：briefText 是语言层（长句→短句），本文件是业务层
 * （§6.6.3 分支白名单 + §6.0.5 数据标签跨行推导 + §6.0.6 降级分支）。
 *
 * v4.1 分支白名单（用户已裁决移除「图表」「信源」）：
 *   核心判断 / 关键亮点 / 核心论点 / 数据(+N) / 正文(仅全空时降级)
 */
import type { ReportSection } from '../types'
import { briefText, stripRefs } from './textBrief'

export interface MapLeaf {
  text: string
  badge?: string
  /** stripRefs 后的完整原文（悬浮 tooltip 用；截断时用户可 hover 看全文） */
  raw?: string
}

export interface MapBranch {
  key: string
  label: string
  /** 折叠前该分支的叶子总数（渲染 +N 用） */
  leaves: MapLeaf[]
  note?: string
  /** 降级分支（§6.0.6 的「正文」计数）：渲染方据此改用一行说明，不再画伪导图 */
  degraded?: boolean
}

const trunc = (s: string, n: number) => {
  s = String(s)
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

/** 平衡括号剥离：先剥括号再算公共后缀（修掉「贪心取到 `） 市场份额`」的 bug） */
function stripParen(s: string): string {
  let out = ''
  let d = 0
  for (const ch of String(s)) {
    if (ch === '（' || ch === '(') {
      d++
      continue
    }
    if (ch === '）' || ch === ')') {
      d = Math.max(0, d - 1)
      continue
    }
    if (d === 0) out += ch
  }
  return out.replace(/\s+/g, ' ').trim()
}

export interface DataLabelsResult {
  labels: string[]
  note: string
  kind: 'rows' | 'matrix' | 'cols' | 'raw'
}

/**
 * §6.0.5 数据标签跨行推导（不猜）：
 *  - 全部含 `·` 且头部统一 → 头部作注记，标签取尾部（rows）
 *  - 全部含 `·` 且构成满矩阵（>6 行）→ 只列分组名 + 维度规模（matrix）
 *  - 无 `·`，有公共后缀（≥3 字）→ 剥公共后缀（cols）
 *  - 兜底 → 原样（raw）
 */
export function dataLabels(rawNames: string[]): DataLabelsResult {
  const cleaned = rawNames.map(stripParen)
  const uniq = (a: string[]) => [...new Set(a)]
  const parts = cleaned.map((n) => n.split('·').map((x) => x.trim()))
  const hasDot = parts.every((p) => p.length >= 2)
  if (hasDot) {
    const heads = parts.map((p) => p[0])
    const tails = parts.map((p) => p.slice(1).join('·'))
    if (uniq(heads).length === 1)
      return { labels: tails, note: trunc(heads[0], 11), kind: 'rows' }
    const H = uniq(heads)
    const T = uniq(tails)
    if (H.length * T.length === cleaned.length && cleaned.length > 6)
      return { labels: H, note: '× ' + T.length + ' 项', kind: 'matrix' }
  }
  const minLen = Math.min(...cleaned.map((n) => n.length))
  let suf = ''
  for (let k = 1; k <= minLen - 1; k++) {
    const c = cleaned[0].slice(-k)
    if (cleaned.every((n) => n.endsWith(c))) suf = c
    else break
  }
  if (suf.length >= 3)
    return {
      labels: cleaned.map((n) => n.slice(0, n.length - suf.length).trim()),
      note: suf.trim(),
      kind: 'cols',
    }
  return { labels: cleaned, note: '', kind: 'raw' }
}

/** 数据分支叶子：满矩阵列分组名；逐行列「标签 值」（各截 9/7 字防溢出） */
function dataBranchLeaves(section: ReportSection): { leaves: MapLeaf[]; note?: string } {
  const grid = section.data_grid
  if (!grid) return { leaves: [] }
  const d = dataLabels(grid.rows.map((x) => x.name))
  const leaves =
    d.kind === 'matrix'
      ? d.labels.slice(0, 6).map((t) => ({ text: trunc(t, 10) }))
      : grid.rows.slice(0, 6).map((x, i) => ({
          text: trunc(d.labels[i] ?? '', 9) + ' ' + trunc(String(x.value), 7),
        }))
  return { leaves, note: d.note || undefined }
}

/** §6.0.6 降级：整棵树为空但正文存在 → 给一行正文计数，不画空框（真实案例 ch13） */
function ensureNonEmpty(section: ReportSection, branches: MapBranch[]): MapBranch[] {
  if (branches.length || !section.paragraphs?.length) return branches
  const figCount = section.charts?.length ?? 0
  return [
    {
      key: 'fallback',
      label: '正文',
      degraded: true,
      leaves: [
        { text: `${section.paragraphs.length} 段${figCount ? ' · ' + figCount + ' 图' : ''}` },
      ],
    },
  ]
}

/**
 * 章节导图叶子（② 精简要点档）：
 * 引用剥离统一在此完成（修掉「组件各自渲染 raw 字段导致 [e_xxx] 泄漏」的结构性缺陷）。
 */
export function chapterMapLeaves(
  section: ReportSection,
  budget = 34
): MapBranch[] {
  const B: MapBranch[] = []

  if (section.key_takeaway) {
    B.push({
      key: 'takeaway',
      label: '核心判断',
      leaves: [
        {
          text: briefText(section.key_takeaway, budget),
          raw: stripRefs(section.key_takeaway),
        },
      ],
    })
  }

  if (section.highlights?.length) {
    B.push({
      key: 'highlights',
      label: '关键亮点',
      leaves: section.highlights.map((h) => ({
        text: briefText(h, budget),
        raw: stripRefs(h),
      })),
    })
  }

  if (section.claims?.length) {
    const hi = section.claims.filter(
      (c) => c.confidence === 'high' && c.cross_validated
    ).length
    B.push({
      key: 'claims',
      label: '核心论点',
      leaves: section.claims.map((c) => ({
        text: briefText(c.text, budget),
        raw: stripRefs(c.text),
        badge: c.cross_validated ? '已交叉验证' : undefined,
      })),
      note: hi ? hi + ' 高置信' : undefined,
    })
  }

  if (section.data_grid?.rows?.length) {
    const { leaves, note } = dataBranchLeaves(section)
    if (leaves.length) B.push({ key: 'data', label: '数据', leaves, note })
  }

  /* v4.1：charts / source_evidence_ids 不进导图（图表正文下方已有、信源属元信息） */
  return ensureNonEmpty(section, B)
}

/** 汇总模式用：分支 → 计数芯片（与 detail 共用同一棵树，规则不漂移） */
export function chapterMapChips(section: ReportSection): { label: string; count: number }[] {
  return chapterMapLeaves(section).map((b) => ({ label: b.label, count: b.leaves.length }))
}

/** L1′ 断言辅助：节点文案必须是原文的连续子串（允许结尾省略号） */
export function isSubstringOf(raw: string, node: string): boolean {
  return (
    raw.includes(node) ||
    (node.endsWith('…') && raw.startsWith(node.slice(0, -1)))
  )
}

export { stripRefs }

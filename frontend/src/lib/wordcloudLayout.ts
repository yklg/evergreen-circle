/**
 * 词云散布布局（P5）：Archimedes 螺旋 + AABB 碰撞检测。
 * 确定性纯函数：同输入同输出，无随机数。
 *
 * 字号归一**分层**：评价词与话题词各按本档的权重跨度取字号。
 * 为什么不能全集合一个 min/max —— 真实语料里话题词是「大理 130 次」量级、
 * 评价词是文档频次 1-2 次量级，同一跨度会把评价词全压到最小字号，
 * 于是词云又变回「只有地名看得见」（本轮要修的病灶本身）。
 */

export type WordKind = 'opinion' | 'topic'

export interface WordItem {
  word: string
  weight: number
  kind?: WordKind
}

export interface PlacedWord extends WordItem {
  x: number
  y: number
  fontSize: number
}

interface Rect {
  x: number
  y: number
  w: number
  h: number
}

const GOLDEN_ANGLE = 2.399963 // ~137.5° in radians

/** 档位字号区间：评价词抢视觉中心，话题词只做背景（计划 D2）。 */
const TIERS: Record<WordKind, { min: number; max: number }> = {
  opinion: { min: 18, max: 44 },
  topic: { min: 12, max: 15 },
}

/** 评价词先排 → 占据螺旋中心；话题词后排垫底。 */
const KIND_RANK: Record<WordKind, number> = { opinion: 0, topic: 1 }

function tierKind(item: WordItem): WordKind {
  return item.kind === 'opinion' ? 'opinion' : 'topic'
}

/** 归一分组键：载荷里一个 kind 都没有时全体归为一组 ⇒ 与分层前逐位同输出。 */
function tierKey(item: WordItem, tiered: boolean): string {
  return tiered ? tierKind(item) : 'all'
}

function estimateBox(word: string, fontSize: number): { w: number; h: number } {
  const charCount = Array.from(word).length
  const w = charCount * fontSize * 0.95
  const h = fontSize * 1.15
  return { w, h }
}

function rectsOverlap(a: Rect, b: Rect, pad: number): boolean {
  return !(
    a.x + a.w + pad < b.x ||
    b.x + b.w + pad < a.x ||
    a.y + a.h + pad < b.y ||
    b.y + b.h + pad < a.y
  )
}

function clampToContainer(rect: Rect, W: number, H: number): { x: number; y: number } {
  let x = Math.max(0, Math.min(rect.x, W - rect.w))
  let y = Math.max(0, Math.min(rect.y, H - rect.h))
  return { x, y }
}

export function layoutWords(
  words: WordItem[],
  W: number,
  H: number,
  maxFontSize = 42,
  minFontSize = 14,
  pad = 12,
  maxSteps = 9000
): PlacedWord[] {
  if (!words.length) return []

  const tiered = words.some((w) => w.kind === 'opinion' || w.kind === 'topic')

  const sorted = [...words].sort((a, b) => {
    if (!tiered) return b.weight - a.weight
    const rk = KIND_RANK[tierKind(a)] - KIND_RANK[tierKind(b)]
    return rk !== 0 ? rk : b.weight - a.weight
  })

  // 退化跨度（档内全等）保留 `|| 1` 语义 ⇒ t=0 ⇒ 落在该档最小字号。
  // 单层路径下这与分层前完全一致，是存量报告「一个像素都不动」的前提。
  const bounds: Record<string, { min: number; max: number }> = {}
  for (const w of sorted) {
    const key = tierKey(w, tiered)
    const cur = bounds[key]
    if (!cur) bounds[key] = { min: w.weight, max: w.weight }
    else {
      cur.min = Math.min(cur.min, w.weight)
      cur.max = Math.max(cur.max, w.weight)
    }
  }

  const placed: PlacedWord[] = []
  const placedRects: Rect[] = []

  for (let i = 0; i < sorted.length; i++) {
    const item = sorted[i]
    const key = tierKey(item, tiered)
    const tier = tiered ? TIERS[tierKind(item)] : { min: minFontSize, max: maxFontSize }
    const b = bounds[key]
    const t = (item.weight - b.min) / (b.max - b.min || 1)
    const fontSize = tier.min + t * (tier.max - tier.min)
    const { w, h } = estimateBox(item.word, fontSize)

    const cx = W / 2
    const cy = H / 2

    let theta = i * GOLDEN_ANGLE
    let r = 6 + 2.4 * theta
    let found = false

    for (let step = 0; step < maxSteps; step++) {
      const x = cx + 1.95 * r * Math.cos(theta)
      const y = cy - 0.9 * r * Math.sin(theta)

      const rect: Rect = { x, y, w, h }
      const overlaps = placedRects.some((pr) => rectsOverlap(rect, pr, pad))

      if (!overlaps) {
        const clamped = clampToContainer(rect, W, H)
        placed.push({ ...item, x: clamped.x, y: clamped.y, fontSize })
        placedRects.push({ x: clamped.x, y: clamped.y, w, h })
        found = true
        break
      }

      theta += 0.25
      r = 6 + 2.4 * theta
    }

    if (!found) {
      const fallbackX = cx + 1.95 * r * Math.cos(theta)
      const fallbackY = cy - 0.9 * r * Math.sin(theta)
      const clamped = clampToContainer({ x: fallbackX, y: fallbackY, w, h }, W, H)
      placed.push({ ...item, x: clamped.x, y: clamped.y, fontSize })
      placedRects.push({ x: clamped.x, y: clamped.y, w, h })
    }
  }

  return placed
}

/**
 * 词云散布布局（P5）：Archimedes 螺旋 + AABB 碰撞检测。
 * 确定性纯函数：同输入同输出，无随机数。
 */

export interface WordItem {
  word: string
  weight: number
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

  const sorted = [...words].sort((a, b) => b.weight - a.weight)
  const weights = sorted.map((w) => w.weight)
  const minW = Math.min(...weights)
  const maxW = Math.max(...weights)
  const weightRange = maxW - minW || 1

  const placed: PlacedWord[] = []
  const placedRects: Rect[] = []

  for (let i = 0; i < sorted.length; i++) {
    const item = sorted[i]
    const t = (item.weight - minW) / weightRange
    const fontSize = minFontSize + t * (maxFontSize - minFontSize)
    const { w, h } = estimateBox(item.word, fontSize)

    const cx = W / 2
    const cy = H / 2

    let theta = i * GOLDEN_ANGLE
    let r = 6 + 2.4 * theta
    let bestX = cx
    let bestY = cy
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

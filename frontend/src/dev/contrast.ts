/**
 * 设计期色彩算子（**测试与取证页共用这一份**，不得内联副本）。
 *
 * 放 `src/dev/` 而非 `src/lib/` 的理由：生产 bundle 不需要它 —— 应用代码里没有任何
 * 路径 import `src/dev/`，Vite 摇树后零字节进包；而取证页（`preview-bmap-road-contrast.html`）
 * 与 `roadContrast.test.ts` 必须算出**同一个数**，否则「取证页说达标、单测说没达标」
 * 就成了第二套真源 —— 那正是 `bmapStyle.ts` 文件头第 ①~⑤ 条反复在防的形状。
 */

/** `#rrggbb` → [r,g,b]（0–255）。非法输入直接抛，不做静默兜底。 */
export function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) throw new Error(`不是 6 位 hex：${JSON.stringify(hex)}`)
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function rgbToHex(r: number, g: number, b: number): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}

/** WCAG 2.x 相对亮度。 */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG 对比度，1.0–21.0。与色序无关。 */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/**
 * 半透明覆盖色压在不透明底色上的**实际呈色**。
 *
 * 存在的理由：等时圈是 `rgba(124,152,133,a)` 压在路面/地面上，肉眼看到的不是
 * styleJson 里写的 hex 而是压色后的结果。契约阈值若不对压色后求值，就会得出
 * 「路面 vs 地面达标，但圈内仍看不见」的假结论。
 */
export function blendOver(bgHex: string, overlayRgba: string): string {
  const [br, bg, bb] = hexToRgb(bgHex)
  const m = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/i.exec(overlayRgba)
  if (!m) throw new Error(`不是 rgb()/rgba()：${JSON.stringify(overlayRgba)}`)
  const a = m[4] === undefined ? 1 : Number(m[4])
  return rgbToHex(
    Number(m[1]) * a + br * (1 - a),
    Number(m[2]) * a + bg * (1 - a),
    Number(m[3]) * a + bb * (1 - a),
  )
}

/** 保留两位小数的对比度，供表格与断言消息共用同一呈现口径。 */
export function cr(a: string, b: string): number {
  return Math.round(contrastRatio(a, b) * 100) / 100
}

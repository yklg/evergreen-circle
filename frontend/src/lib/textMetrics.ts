/**
 * 文字盒度量 —— 无 DOM、确定性、可单测。
 *
 * 为什么需要它：SVG 里 `text` 的实际占位决定画布要多大才不裁切，但运行时
 * `getComputedTextLength` / `getBBox` 在 SSR、水合与 jsdom 下都不可用（jsdom 30 里
 * 二者直接是 undefined）。所以度量必须**算**出来，而不是量出来。
 *
 * 常量来源：2026-09-25 真实 Chrome（PingFang SC）`getBBox()` 实测，不是拍脑袋的估值。
 * font-size 11 下 `菜市场` 宽 33.0 = 3 × 1em，字形盒高 16.0 = 1.455em（ascent 12.0 / descent 4.0）。
 *
 * ⚠️ 中文**不能**按 0.95em 估：那是 `wordcloudLayout` 面向拉丁词的经验值，对 CJK 偏小。
 * 少估 2.1 单位会让派生画布少留同样多空间，被内边距吃掉 —— 表现为"暂时不裁"，
 * 换字体或换标签长度就复发。调用方若确需别的因子，显式传 opts 覆盖。
 */

export interface TextBox {
  /** 估算占位宽（用户单位） */
  w: number
  /** ascent + descent，即字形盒总高 */
  h: number
  /** 基线以上高度：字形盒顶 = 基线 y − ascent */
  ascent: number
  /** 基线以下高度：字形盒底 = 基线 y + descent */
  descent: number
}

export interface TextMetricsOptions {
  cjkWidthEm?: number
  latinWidthEm?: number
  ascentEm?: number
  descentEm?: number
}

/** CJK / 全角实测：1 码点 = 1em 宽；字形盒 1.455em 高。 */
export const WIDE_TEXT_METRICS = {
  cjkWidthEm: 1.0,
  latinWidthEm: 0.6,
  ascentEm: 1.09,
  descentEm: 0.37,
} as const

/**
 * 逐码点判宽。用码点区间比较而非 `\u` 正则字符类 ——
 * 后者在源码里极易被写成错位的范围（实测把「菜市场」判成拉丁文，估宽 19.8 对真实 33.0）。
 */
function isWideCodePoint(cp: number): boolean {
  return (
    (cp >= 0x3000 && cp <= 0x303f) || // CJK 标点 (U+3000–U+303F)
    (cp >= 0x3400 && cp <= 0x4dbf) || // 扩展 A
    (cp >= 0x4e00 && cp <= 0x9fff) || // 基本汉字
    (cp >= 0xf900 && cp <= 0xfaff) || // 兼容汉字
    (cp >= 0xac00 && cp <= 0xd7af) || // 谚文音节
    (cp >= 0xff00 && cp <= 0xffef) // 全角形式
  )
}

export function estimateTextBox(
  text: string,
  fontSize: number,
  opts?: TextMetricsOptions,
): TextBox {
  const cjkWidthEm = opts?.cjkWidthEm ?? WIDE_TEXT_METRICS.cjkWidthEm
  const latinWidthEm = opts?.latinWidthEm ?? WIDE_TEXT_METRICS.latinWidthEm
  const ascentEm = opts?.ascentEm ?? WIDE_TEXT_METRICS.ascentEm
  const descentEm = opts?.descentEm ?? WIDE_TEXT_METRICS.descentEm

  let em = 0
  for (const ch of String(text)) {
    em += isWideCodePoint(ch.codePointAt(0) ?? 0) ? cjkWidthEm : latinWidthEm
  }

  return {
    w: em * fontSize,
    h: (ascentEm + descentEm) * fontSize,
    ascent: ascentEm * fontSize,
    descent: descentEm * fontSize,
  }
}

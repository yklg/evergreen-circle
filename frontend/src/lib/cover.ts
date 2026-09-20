/* 契约：本封面图会被 DOM 文字叠加渲染（见 ReportPage 英雄区），
 * 因此**禁止在 SVG 内烘录任何文字** —— 标题 / 品牌行 / 标语一律由 DOM 渲染。
 * 历史重叠 bug（封面图内的标题·品牌行·标语与 DOM 标题前后相撞）正源于此。
 *
 * 报告封面解析（共享工具）：列表页与详情页共用，消除重复实现。
 *
 * 背景：历史报告 cover_image 存的是失效外部生图 URL（copilot-cn.bytedance.net），
 * 浏览器拦截 → 灰占位。后端 _make_cover_svg 已为【新】报告生成 data URL 封面。
 * 本工具作为展示层兜底：对本地路径/data URL 直出、对失效外部 URL 或缺失 → 本地生成 SVG，
 * 无需迁移数据库即可让历史报告显示封面。
 */

import { BRAND } from './brand'

export interface CoverSource {
  title: string
  brands?: string[]
  cover_image?: string
}

function makeCoverSvg(title: string, brands: string[]): string {
  const t = (title || '目的地调研').slice(0, 20)
  const b = (brands.slice(0, 3).join(' · ') || BRAND.coverByline)
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">' +
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
    '<stop offset="0" stop-color="#0f766e"/><stop offset="1" stop-color="#134e4a"/>' +
    '</linearGradient></defs>' +
    '<rect width="800" height="450" fill="url(#g)"/>' +
    '<circle cx="650" cy="80" r="150" fill="#ffffff" opacity="0.06"/>' +
    '<circle cx="110" cy="390" r="90" fill="#ffffff" opacity="0.05"/>' +
    `<text x="48" y="70" fill="#a7f3d0" font-family="sans-serif" font-size="20" letter-spacing="2">${BRAND.en.toUpperCase()} · 调研报告</text>` +
    `<text x="46" y="225" fill="#ffffff" font-family="sans-serif" font-size="40" font-weight="700">${t}</text>` +
    `<text x="48" y="272" fill="#ccfbf1" font-family="sans-serif" font-size="22">${b}</text>` +
    '<text x="48" y="410" fill="#99f6e4" font-family="sans-serif" font-size="16" opacity="0.85">结论可溯源 · 证据可沉淀</text>' +
    '</svg>'
  return 'data:image/svg+xml,' + encodeURIComponent(svg)
}

export function coverFor(r: CoverSource): string {
  const c = r.cover_image
  // 本地路径（/assets/...）或后端生成的 data URL → 直出；
  // 任何外部 http(s) URL（含历史失效的 bytedance 生图地址）或缺失 → 本地生成。
  if (c && !c.startsWith('http')) return c
  return makeCoverSvg(r.title, r.brands ?? [])
}

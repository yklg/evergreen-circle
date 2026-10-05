// @vitest-environment jsdom
/**
 * `public/favicon.svg` 的 XML 良构判据 —— 补品牌图标链上缺失的那个消费者。
 *
 * 为什么必须有这一条（回归 2026-09-27 → 2026-10-05）：
 * favicon 是被浏览器当作 **XML 文档**解析的，没有 HTML 那套容错。当时换上的嫩芽图标
 * 在注释里写了 CSS 自定义属性名，其开头的连续两个减号在 XML 注释体内非法
 * ⇒ 整份 SVG 解析失败 ⇒ 浏览器取不到图标 ⇒ 标签页退回历史里唯一解析成功过的
 * Vite 默认闪电，挂了 8 天，且无痕窗口也照旧（不是缓存问题）。
 *
 * 而整条链上没有任何一环按 XML 消费过这个资产，所以它一路全绿：
 * - `brand.test.ts` 对图标只跑字符串正则（查色值、查 rel/href），一律放行；
 * - `make_brand_icon.py` 把 SVG **内联进 HTML** 再截图，HTML 解析器容忍该序列，
 *   于是 `apple-touch-icon.png` 和验收页 `preview-brand-icon.html` 看着都是好叶子。
 * 同一份字节，走 HTML 解析器活、走 XML 解析器死 —— 只有这里这一环抓得住。
 *
 * 实现说明：资产经 Vite 的 `?raw` 读入，因此不需要 `fileURLToPath(import.meta.url)`。
 * 这也是本文件必须独占 jsdom 环境的原因 —— jsdom 下 `import.meta.url` 不是 file 协议，
 * 所以用 import.meta.url 定位文件的 `brand.test.ts` 仍留在 node 环境。
 */
import { describe, it, expect } from 'vitest'
import svg from '../../public/favicon.svg?raw'

describe('favicon.svg 作为 XML 文档可被浏览器解析', () => {
  it('DOMParser 不产生 parsererror，且根元素是 svg', () => {
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
    const errs = doc.getElementsByTagName('parsererror')
    const detail = errs.length > 0 ? (errs[0].textContent ?? '').replace(/\s+/g, ' ').trim() : ''
    expect(errs.length, `favicon.svg 不是良构 XML，浏览器会取不到图标：${detail}`).toBe(0)
    expect(doc.documentElement.nodeName).toBe('svg')
  })
})

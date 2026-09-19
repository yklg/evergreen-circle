/**
 * 品牌单一真相源（Single Source of Truth）。
 *
 * ## 为什么存在
 * 修复前品牌字面量散落在 `index.html` / `VSidebar` / `SlidesPage` / `cover.ts` 等
 * ≥5 处，改名必然漏改（典型的"硬编码漂移"反模式）。
 * 修复后：**改品牌 = 改本文件一处**。
 *
 * ## 与 index.html 的关系（唯一例外，有守卫）
 * `index.html` 是静态壳，首屏（JS 执行前）/ SEO 用的 `<title>` 必须写死，
 * 无法 import 本模块。为避免两处漂移，`brand.test.ts` 有一条**漂移守卫**断言：
 * `index.html` 的 `<title>` 必须与 `BRAND.title` 一致 —— 改一处忘另一处会直接测试红。
 * （与仓库既有的 `backend/tests/test_api_mirror_guard.py` 同款思路。）
 *
 * ## 边界
 * 本文件只放"对外可见的品牌标识"。**用户的昵称/公司默认值不是品牌**
 * （见 `store/profileStore.ts` 的 DEFAULT_NAME / DEFAULT_COMPANY），故不在此处。
 */
export const BRAND = {
  /** 英文品牌名（侧边栏 Wordmark、幻灯片落款等用） */
  en: 'EvergreenCircle',
  /** 中文品牌名 */
  zh: '常青圈',
  /** 完整中文品牌名（文档标题、正式称谓） */
  full: '常青圈 EvergreenCircle',
  /** 浏览器标签标题 / document.title */
  title: '常青圈 EvergreenCircle · 15 分钟生活圈智能体检与规划助手',
  /** 首页副标题（价值主张） */
  tagline: '输入中心点，基于真实路网计算 15 分钟步行等时圈，体检设施覆盖、识别服务盲区',
  /** 报告封面品牌行兜底（无竞品名时使用） */
  coverByline: 'EvergreenCircle AI',
  /** 移动端地址栏 / 主题色（与 index.css 的 --verda-primary 同源） */
  themeColor: '#7c9885',
} as const

/** 品牌主色（品牌资源的唯一色值来源；favicon.svg 同值） */
export const BRAND_COLOR = BRAND.themeColor

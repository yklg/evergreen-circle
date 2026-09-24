/**
 * 常青圈 · BMapGL 底图风格（C7 底图风格调适 · S2 低饱和浅灰，已确认）。
 *
 * 目标：真实百度底图融入项目浅色视觉——底色对齐现有画布 `#f9faf8`；
 * **道路 / 水系 / 绿地的分级与配色一律交还百度默认**（2026-09-24 真机逐键探针：自绘它们的
 * 键在 BMapGL 上要么静默无效、要么把整层打掉，见 ⑪⑫ —— 故本文件不写任何道路规则）；
 * **底图不出现任何第三方设施信息**（既无设施名，也无百度自带的 POI 图钉），只留路名与
 * 行政区名做空间参照，避免与覆盖层（等时圈/POI Marker）争色、更避免评审把**别人的点**
 * 读成我们的数据。通过 `map.setMapStyleV2({ styleJson: LC_MAP_STYLE_LIGHT })` 生效。
 *
 * 优先级：**内置模板优先**。后端 `BAIDU_MAP_STYLE_ID` 默认不下发（`main.life_circle_map_config()`
 * 受 `BAIDU_ALLOW_CONSOLE_STYLE` 抑制）——因为控制台样式里的注记开关**代码无法验证**，
 * 且 `setMapStyleV2` 的 `styleId` 与 `styleJson` **互斥二选一**（百度官方文档），
 * 无法「用它的配色 + 代码关注记」。纪律必须活在版本控制里（阶段 0.2 / 决策 D4）。
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ⚠️ 以下五条是**注记侧** 2026-09-22 用真实底图实测出来的，不要凭直觉改（每一条都踩过）：
 *
 * ① **只关 `poilabel` 远远不够**。实测 `{poilabel, labels: off}` 之后，
 *    图上仍有「和谐家园 / 香枫庭院 / 居然之家 / 交通驾校 / 佳和盛世一期」等名字，
 *    以及**全部百度 POI 图钉**。POI 注记按多个家族拆分，而家族名并非全部可用：
 *    实测 `estatelabel / shoppinglabel / companylabel / restaurantlabel / financelabel / …`
 *    共 20 个候选名**全部无效**（写了等于没写，百度静默忽略）⇒ **枚举法不可行**。
 *
 * ② **`labels` 与 `labels.icon` 是两个独立 elementType**。官方 JSAPI 示例（"去除非景点类
 *    POI 标注"）同时关两者；实测只关 `labels` 时**图钉一个不少**——而那些图钉正是
 *    「第三方点冒充自家数据」的最强观感来源，必须单独关。
 *
 * ③ **必须用 `featureType: 'all'` 通配**，否则关不掉那些叫不出名字的 POI 家族。
 *    但通配会把路名/区划名一起关掉，故需第 ④ 步回收。
 *
 * ④ **回收白名单只能写 `visibility`，绝不能带 `color`**。官方语义是「同一元素多条样式，
 *    以最后一条生效」；给白名单规则再加一个 `color`（哪怕写在同一条 stylers 里）会把
 *    刚开回的可见性**再次打掉** —— 实测带 color 的版本在 zoom 13 上几乎一片空白（只剩底图色块）。
 *    代价：保留的路名/地名用百度默认字色，不能自定义成项目灰。
 *
 * ⑤ **顺序即语义**：白名单必须排在通配关之后（数组顺序 = 生效优先级的后手）。
 *    顺序被颠倒 = 注记全部关闭 = 地图失去参照系（用户「不知道自己在哪」），
 *    故单测显式锁定「关在前、开在后」。
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * 注记实测结论（凯里老街，zoom 13/15/17 三档复核）：
 *   - zoom 17：只剩「凯棉路 / 迎宾大道」等路名；无设施名、无图钉 ✅
 *   - zoom 13：仍有「黔东南苗族侗族自治州 / 凯里市 / 凯里南站 / 滨江大道 / 沪昆高速」等地名与路名 ✅
 *   - 对照（百度默认）：满图「居然之家 / 紫蝶谷购物广场 / 贵州信达会计有限公司 / 社区卫生服务中心」+ 图钉 ❌
 *
 * 注记取证页：`预览-底图注记-2026-09-22/底图注记-规则v6.html`（G1/G2 为最终口径，G3 为带 color 的反例）。
 * 面层取证页：`frontend/preview-bmap-road-contrast.html`（`?zoom=15&mode=singles-c` 并排 U0~U5）。
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ⚠️ 以下五条是**面层侧** 2026-09-24 用真实底图逐键探针实测出来的
 *    （`?mode=singles` 矩阵，凯里老街 zoom 15，1170×420，全像素 491,400）。
 *    比注记侧更反直觉，尤其 ⑪ —— 不要凭直觉写道路色值：
 *
 * ⑩ **百度默认底图锚点表**（P4 不下发任何 styleJson 实测；用途是**日后比对是否漂移**，
 *    不是阈值来源）。分级靠**色相与描边**而非亮度对比（主干道 vs 地面仅 1.082，
 *    比一般道路的 1.090 还低）——不要拿"对比度阈值"去验分级，那会得出错误的结论：
 *      · 地面 land `#f5f5f5` 66.2%（基准 1.000）
 *      · 一般道路 `#ffffff` 5.8~6.5%（vs 地 1.090）｜主干道 `#ffebb4` 1.96%（1.082）
 *      · 高速 `#ffb269` 0.66%（1.629）｜水面 `#75e0f9` 0.99%（1.397）｜绿地 `#b5f2bf` 0.65%（1.173）
 *
 * ⑪ **任何道路面层键都会让整条道路层不可见**。实测 `road/geometry` 设 `#ff0000` 与设
 *    `#ffffff` 得到**完全相同**的直方图（地灰 76.04%、主干黄 0）⇒ 致命的是**规则存在本身**，
 *    而非颜色。这正是本次事故的机制：U0→U5 逐像素 diff 显示 **40,290 个道路像素被涂成
 *    地面色**（28,836 路白 + 8,774 主干黄 + 2,680 高速橙）。`highway/geometry` 同害
 *    （高速橙 809→0，替换色出现 0）——所以本文件一条道路规则都不写。
 *
 * ⑫ **面层侧唯一经真机验证有效的键是 `land`**。`water / green / building` 涂
 *    `#ff00ff / #00ff00 / #0000ff` 命中像素 **0**（静默忽略）；`local / arterial` 的
 *    `geometry` 与 `geometry.stroke` 实测均无任何变化。故 `LC_CANVAS_TONE` 只写 land ——
 *    **未列入本条的键一律不得写入**（写了不是无效就是有害）。
 *
 * ⑬ **面层规则只允许 `elementType: 'geometry'`**；出现 `labels` 即越界（注记轴在 `LC_NOTES_*`）。
 *
 * ⑭ **键与色值的改动门禁**：任何面层改动必须同时过 `__tests__/roadContrast.test.ts` 与
 *    `src/dev/verifiedStyleKeys.ts` 的实测枚举清单；枚举清单过期时**重跑探针**，不得手工补键。
 * ─────────────────────────────────────────────────────────────────────────────
 */

/**
 * 允许保留注记的要素白名单 —— 「空间参照」而非「第三方数据」。
 *
 * 入选标准：**能回答「这是哪、怎么走」**，不承载任何第三方经营主体信息。
 * 行政区划（districtlabel/district/city/town/continent）+ 各级道路（road/arterial/highway/local）
 * + 轨道（subway/railway）。⚠️ 剔除任何 `*label` 形态的 POI 家族（含 estate/shopping/company…）。
 */
export const LC_KEEP_LABELS = [
  'districtlabel',
  'district',
  'city',
  'town',
  'continent',
  'road',
  'arterial',
  'highway',
  'local',
  'subway',
  'railway',
] as const

/**
 * 画布面色：**唯一**经真机验证有效的面层键（见 ⑫），保住「底色对齐画布 `#f9faf8`」。
 *
 * ⚠️ 未列入的键一律不得写入 —— `water/green/building` 写了等于没写（静默忽略，属死代码，
 * 会让人误以为水面/绿地是项目色）；`road/arterial/highway/local` 写了会把整层打掉（见 ⑪）。
 * 不写即保持百度默认，这正是我们要的：道路分级由百度自绘。
 */
const LC_CANVAS_TONE: Record<string, unknown>[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f9faf8' } },
]

/** ① + ②：全关文字注记与图钉（含那些叫不出名字的 POI 家族）。 */
const LC_HIDE_ALL_NOTES: Record<string, unknown>[] = [
  { featureType: 'all', elementType: 'labels', stylers: { visibility: 'off' } },
  { featureType: 'all', elementType: 'labels.icon', stylers: { visibility: 'off' } },
]

/** ③：把空间参照开回来 —— **只写 visibility**（见 ④）。 */
const LC_REOPEN_REFERENCE: Record<string, unknown>[] = LC_KEEP_LABELS.map((featureType) => ({
  featureType,
  elementType: 'labels',
  stylers: { visibility: 'on' },
}))

/** 关闭态注记纪律：先通配关、后白名单开（顺序即语义，见 ⑤）。 */
const LC_NOTES_OFF: Record<string, unknown>[] = [...LC_HIDE_ALL_NOTES, ...LC_REOPEN_REFERENCE]

/**
 * 开启态：在面层之上显式补发 `{all/labels: on}` + `{all/labels.icon: on}`。
 *
 * 发现一：`setMapStyleV2` 是**后发覆盖**语义 —— 只补发面层不会撤销 `all/labels: off`，
 * 开关会"按了没反应"。故开启态必须**整段不含任何 `visibility:'off'`**（TC-01 显式锁），
 * 直接以面层 + 全局 on 重发，把第三方设施名与图钉（含 POI 图钉）一起开回来。
 * ⚠️ 不得保留 `LC_HIDE_ALL_NOTES`（带 `visibility:'off'`），否则与 TC-01 冲突。
 */
const LC_NOTES_ON: Record<string, unknown>[] = [
  { featureType: 'all', elementType: 'labels', stylers: { visibility: 'on' } },
  { featureType: 'all', elementType: 'labels.icon', stylers: { visibility: 'on' } },
]

/**
 * 拆层组合：**画布面色常驻**，注记是唯一可切换轴。
 *
 * 旧版把面层与注记平铺在同一个扁平数组里，`lcMapStyle()` 两个分支都以 `...LC_FACE_STYLE`
 * 开头 —— 结构上注记开关永远切不到面层，且「道路规则别被删」只能靠人记住：八条面层规则里
 * 四条把道路涂白，无人越线告警（本次事故原形）。拆层后 `LC_CANVAS_TONE` 不出现在任何 notes
 * 分支的参数位上，**面层在结构上无法被注记轴切掉**。
 */
function lcCompose(notes: Record<string, unknown>[]): Record<string, unknown>[] {
  return [...LC_CANVAS_TONE, ...notes]
}

/** 预计算常量（非惰性拼接）：调用方 `toBe(LC_MAP_STYLE_LIGHT)` 依赖同一引用（C1）。 */
export const LC_MAP_STYLE_LIGHT: Record<string, unknown>[] = lcCompose(LC_NOTES_OFF)
export const LC_MAP_STYLE_NOTES_ON: Record<string, unknown>[] = lcCompose(LC_NOTES_ON)

/** 注记样式唯一出口（取值走唯一出口纪律）：开→NOTES_ON / 关→LIGHT。 */
export function lcMapStyle(notesOn: boolean): Record<string, unknown>[] {
  return notesOn ? LC_MAP_STYLE_NOTES_ON : LC_MAP_STYLE_LIGHT
}

/**
 * 常青圈 · BMapGL 底图风格（C7 底图风格调适 · S2 低饱和浅灰，已确认）。
 *
 * 目标：真实百度底图融入项目浅色视觉——底色对齐现有画布 `#f9faf8`，
 * 道路/水系/建筑低饱和；**底图不出现任何第三方设施信息**（既无设施名，也无百度自带的
 * POI 图钉），只留路名与行政区名做空间参照，避免与覆盖层（等时圈/POI Marker）争色、
 * 更避免评审把**别人的点**读成我们的数据。
 * 通过 `map.setMapStyleV2({ styleJson: LC_MAP_STYLE_LIGHT })` 生效。
 *
 * 优先级：**内置模板优先**。后端 `BAIDU_MAP_STYLE_ID` 默认不下发（`main.life_circle_map_config()`
 * 受 `BAIDU_ALLOW_CONSOLE_STYLE` 抑制）——因为控制台样式里的注记开关**代码无法验证**，
 * 且 `setMapStyleV2` 的 `styleId` 与 `styleJson` **互斥二选一**（百度官方文档），
 * 无法「用它的配色 + 代码关注记」。纪律必须活在版本控制里（阶段 0.2 / 决策 D4）。
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ⚠️ 以下四条是 **2026-09-22 用真实底图实测**出来的，不要凭直觉改（每一条都踩过）：
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
 * 实测结论（凯里老街，zoom 13/15/17 三档复核）：
 *   - zoom 17：只剩「凯棉路 / 迎宾大道」等路名；无设施名、无图钉 ✅
 *   - zoom 13：仍有「黔东南苗族侗族自治州 / 凯里市 / 凯里南站 / 滨江大道 / 沪昆高速」等地名与路名 ✅
 *   - 对照（百度默认）：满图「居然之家 / 紫蝶谷购物广场 / 贵州信达会计有限公司 / 社区卫生服务中心」+ 图钉 ❌
 *
 * 取证页面：`预览-底图注记-2026-09-22/底图注记-规则v6.html`（G1/G2 为最终口径，G3 为带 color 的反例）。
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

/** 面层配色（先于注记规则给出，保证注记规则是数组末段、顺序稳定可测）。 */
const LC_FACE_STYLE: Record<string, unknown>[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f9faf8' } },
  { featureType: 'water', elementType: 'geometry', stylers: { color: '#e2ecf3' } },
  { featureType: 'green', elementType: 'geometry', stylers: { color: '#e9efe6' } },
  { featureType: 'building', elementType: 'geometry', stylers: { color: '#f2f4f2' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#e6e9e7' } },
  { featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#dfe4df' } },
  { featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#d8ddd9' } },
]

/** ① + ②：全关文字注记与图钉（含那些叫不出名字的 POI 家族）。 */
const LC_HIDE_ALL_NOTES: Record<string, unknown>[] = [
  { featureType: 'all', elementType: 'labels', stylers: { visibility: 'off' } },
  { featureType: 'all', elementType: 'labels.icon', stylers: { visibility: 'off' } },
]

/** ③：把空间参照开回来 —— **只写 visibility**（见文件头 ⑤）。 */
const LC_REOPEN_REFERENCE: Record<string, unknown>[] = LC_KEEP_LABELS.map((featureType) => ({
  featureType,
  elementType: 'labels',
  stylers: { visibility: 'on' },
}))

export const LC_MAP_STYLE_LIGHT: Record<string, unknown>[] = [
  ...LC_FACE_STYLE,
  ...LC_HIDE_ALL_NOTES,
  ...LC_REOPEN_REFERENCE,
]

/**
 * 开关「开」态：在面层之上显式补发 `{all/labels: on}` + `{all/labels.icon: on}`。
 *
 * 发现一：`setMapStyleV2` 是**后发覆盖**语义 —— 只补发面层不会撤销 `all/labels: off`，
 * 开关会"按了没反应"。故开启态必须**整段不含任何 `visibility:'off'`**（TC-01 显式锁），
 * 直接以面层 + 全局 on 重发，把第三方设施名与图钉（含 POI 图钉）一起开回来。
 * ⚠️ 不得保留 `LC_HIDE_ALL_NOTES`（带 `visibility:'off'`），否则与 TC-01 冲突。
 */
export const LC_MAP_STYLE_NOTES_ON: Record<string, unknown>[] = [
  ...LC_FACE_STYLE,
  { featureType: 'all', elementType: 'labels', stylers: { visibility: 'on' } },
  { featureType: 'all', elementType: 'labels.icon', stylers: { visibility: 'on' } },
]

/** 注记样式唯一出口（取值走唯一出口纪律）：开→NOTES_ON / 关→LIGHT。 */
export function lcMapStyle(notesOn: boolean): Record<string, unknown>[] {
  return notesOn ? LC_MAP_STYLE_NOTES_ON : LC_MAP_STYLE_LIGHT
}

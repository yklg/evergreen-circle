/**
 * 真机实测 · BMapGL 样式键枚举清单（grand-shoal-moth 步骤 0 交付物）。
 *
 * ## 为什么只能靠实测
 *
 * 百度**不发布 style-spec**：[官方自定义地图文档](https://lbsyun.baidu.com/index.php?title=jspopular/guide/custom)
 * 只示范 `featureType: 'road'` + `elementType: 'geometry.stroke'`，对合法枚举值无一字清单。
 * 业界通行的「按厂商 schema 校验样式文档」在 BMapGL 上**不可套用**。
 * 更麻烦的是：百度对未知键 **静默忽略、不报错不告警**（本仓 2026-09-22 已因此踩过——
 * 20 个 POI 家族候选名全部无效，见 `lib/bmapStyle.ts` 文件头 ①）。
 * 所以「写了 ≠ 生效」必须由真机探针逐键问清，结论固化成本文件。
 *
 * ## 验证条件
 *
 * - 时间：2026-09-24
 * - 视口：凯里老街 `[107.97580, 26.57340]`，`zoom 15`（探针支持 13/15/17）
 * - 渲染：BMapGL WebGL，headless Chrome + ANGLE Metal，`map_style_id` 为空（未被控制台样式抢占）
 * - 判据：截图逐像素归类（`/tmp` 脚本 BMP 直方图 + 逐像素对照），**不靠肉眼**——
 *   因为「看着像变了」在低对比度浅色底图上极不可靠
 * - 探针：`preview-bmap-road-contrast.html?mode=singles|singles-b|singles-c|tones`
 *
 * ## 纪律
 *
 * - 本清单是**事实记录**，不是设计选择。过期（百度改版）时须**重跑探针**，
 *   **不得手工补键**——手工补的键没有真机背书，正是本清单要防的东西。
 * - 未验证的键不得进入清单；宁可缺项让断言红，不可凭猜测放行。
 * - `GEOMETRY_*` 与 `LABELS_*` 是**两个不同枚举域**：`arterial` 在注记侧可用
 *   **不代表**面层侧可用（本次实测恰好证明面层侧的 `arterial` 就是无效的）。
 *   合成一套就是假防线。
 */

/** 单个键的实测凭据。 */
export interface KeyEvidence {
  /** 面层侧键名；注记侧为白名单 featureType、此处固定 `*` 表示通配写法 */
  featureType: string
  /** 实测生效情况 */
  verdict: 'works' | 'ignored' | 'harmful'
  /** 探针实例号（见 roadContrastProbe.ts 的 PANELS） */
  probe: string
  zoom: number
  /** 实测观察到的现象（原始记录，不做解释） */
  observed: string
}

/**
 * 面层侧（`elementType` 以 `geometry` 开头）**实测有效**的 featureType。
 *
 * 只有 `land`。这意味着：**地图的道路/水系/绿地配色在本 SDK 上不可程序化控制**，
 * 唯一可靠的做法是交还百度默认。
 */
export const GEOMETRY_VERIFIED: ReadonlySet<string> = new Set(['land'])

/** 注记侧（`elementType` 为 `labels` / `labels.icon`）**实测有效**的 featureType。 */
export const LABELS_VERIFIED: ReadonlySet<string> = new Set([
  'all',
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
])

/** 全部实测记录（含**无效**与**有害**的键——它们是"别再试了"的证据，同样要留）。 */
export const KEY_EVIDENCE: readonly KeyEvidence[] = [
  // ── 面层：有效的唯一一个 ──
  {
    featureType: 'land',
    verdict: 'works',
    probe: 'S5 / V2',
    zoom: 15,
    observed: 'S5 单设 land=#ffffff：背景由默认 #f5f5f5 整体变白，且道路（黄/橙/白）一条不少；U1→U2 逐像素 95.9% 变为下发色 #f9faf8',
  },
  // ── 面层：静默忽略 ──
  {
    featureType: 'water',
    verdict: 'ignored',
    probe: 'V1',
    zoom: 15,
    observed: '单设 water=#ff00ff（品红）：全图品红像素 0（采样 24.5 万点）。注：默认浅水色本就 ≈ #e2ecf3，与线上取值同色，极易误判为"生效"',
  },
  {
    featureType: 'green',
    verdict: 'ignored',
    probe: 'V1',
    zoom: 15,
    observed: '单设 green=#00ff00（纯绿）：全图纯绿像素 0',
  },
  {
    featureType: 'building',
    verdict: 'ignored',
    probe: 'V1',
    zoom: 15,
    observed: '单设 building=#0000ff（纯蓝）：全图纯蓝像素 0',
  },
  {
    featureType: 'local',
    verdict: 'ignored',
    probe: 'S2 / T5',
    zoom: 15,
    observed: 'geometry 与 geometry.stroke 分别设 #00c000：与不下发样式的 S0 直方图逐项一致（主干黄 2428 / 高速橙 815 / 路白 4331 vs 4336），无任何变化',
  },
  {
    featureType: 'arterial',
    verdict: 'ignored',
    probe: 'S3 / S6 / T1',
    zoom: 15,
    observed: 'geometry=#0000ff、geometry.stroke=#0000ff 均无变化；与 S0 基线逐项一致',
  },
  // ── 面层：有害（会破坏道路渲染）──
  {
    featureType: 'road',
    verdict: 'harmful',
    probe: 'S1 / T2',
    zoom: 15,
    observed: 'geometry 设 #ff0000 与设 #ffffff 得到**完全相同**的直方图（地灰 76.04% / 主干黄 0 / 高速橙 0）⇒ 致命的是"这条规则的存在"而非颜色，整条道路层被涂成地面色',
  },
  {
    featureType: 'highway',
    verdict: 'harmful',
    probe: 'S4 / U4',
    zoom: 15,
    observed: 'geometry=#ff9d00：高速橙像素由 809 归零，而替换色 #ff9d00 出现 0 像素 ⇒ 分级被抹掉且新色不显示',
  },
  {
    featureType: 'road',
    verdict: 'ignored',
    probe: 'T0',
    zoom: 15,
    observed: 'geometry.stroke=#ff0000：该实例瓦片未渲染完（tilesLoaded 5/6），观测**作废**，本次不作结论；从其余 stroke 侧键的表现推断可信度低',
  },
  {
    featureType: 'highway',
    verdict: 'ignored',
    probe: 'T1',
    zoom: 15,
    observed: 'geometry.stroke=#0000ff：高速橙 815→694（-15%），无任何蓝色像素 ⇒ 不足以表达分级',
  },
  // ── 注记：纪律仍在，且是唯一有效的可信度手段 ──
  {
    featureType: 'all',
    verdict: 'works',
    probe: 'U1 / U2',
    zoom: 15,
    observed: 'labels + labels.icon 置 off 后：第三方设施名与全部 POI 图钉归零（对照 U0 满图图钉），与 2026-09-22 实测一致',
  },
  {
    featureType: 'districtlabel…railway（白名单 11 项）',
    verdict: 'works',
    probe: 'U1 / U2',
    zoom: 15,
    observed: '只写 visibility:on 回收后：路名（滨江大道/环城西路/沪昆高速…）与区划名保留，无设施名',
  },
]

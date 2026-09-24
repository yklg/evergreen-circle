/**
 * 底图道路可读性 · 真机取证页（grand-shoal-moth · v4 定稿）。
 *
 * 打开：`http://localhost:3400/preview-bmap-road-contrast.html?mode=singles-c&zoom=15`
 *
 * ## 本页回答的四类问题（v4）：键 → 锚点 → 候选 → 面色复核
 *
 * **S/T 键探针**（`?mode=singles` / `?mode=singles-b`）—— 面层侧到底接受哪些键。
 * 起因：`bmapStyle.ts` 第 ① 条记过「20 个 POI 家族候选名写了等于没写、百度静默忽略」，
 * 而 `labels` 侧接受 `arterial/highway/local` **不等于** `geometry` 侧接受 ——
 * 两个不同枚举域。不先真机量一遍就写断言，得到的是「测试全绿、图上仍没路」。
 * 结论已固化进 `verifiedStyleKeys.ts`（面层有效键**只有** `land`）。
 *
 * **P0/P4 锚点**（`?mode=default`）—— 百度默认底图的实际渲染状态。
 * v4 的重要发现：**主干道 vs 地面 1.082，比一般道路的 1.090 还低** ⇒
 * 分级靠色相与描边而非亮度对比。任何「对比度 ≥ 1.x」的门禁都会把百度自己的默认底图
 * 判成不合格，故契约断言改为**负向不变量**（见 `__tests__/roadContrast.test.ts`）。
 *
 * **U 组候选对照**（`?mode=singles-c`）—— A/B 两组已否掉「自绘道路面层」这条路，
 * 于是把「交还百度默认」的几种取法并排比。⭐U2 = U6 为终版。
 *
 * **V 组面色复核**（`?mode=tones`）—— `water/green/building` 三键是否真生效。
 * 结论：**都没生效**（刺眼色命中 0 像素），故终版面色只保留 `land` 一条。
 *
 * 样式取自 `lib/bmapStyle`、算子取自 `dev/contrast`，与线上和单测同一份真源。
 * 本目录（`src/dev/`）不被任何应用入口引用，故不进生产包（已核 dist 零命中）；
 * 但会被 `tsc` 与 `eslint` 纳入检查 —— 这是刻意的：取证代码烂掉等于防线烂掉。
 */
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { getMapConfig, loadBMapGL } from '../lib/bmap'
import { lcMapStyle } from '../lib/bmapStyle'
import { cr } from './contrast'

type Rule = { featureType: string; elementType: string; stylers: Record<string, unknown> }
type Rgba = [number, number]

const CENTER = (kaili as unknown as { scene: { center: Rgba } }).scene.center
const ZOOM = Number(new URLSearchParams(location.search).get('zoom') ?? 15)

/** 地面保持项目现值：取证要隔离的变量是「道路分级键」，不是底色。 */
const LAND = '#f9faf8'

/**
 * P0 探针：四级各涂一种互不相近的刺眼色，地面刷纯白。
 * 判读：图上出现**几种**颜色 = 面层侧接受**几个**分级键。
 * 只出现一种 ⇒ 键被接受但面层不分级（后写覆盖前写）⇒ 走计划里的降级阶梯 L1/L2。
 */
const P0_PROBE: Rule[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#ff0000' } },
  { featureType: 'local', elementType: 'geometry', stylers: { color: '#00c000' } },
  { featureType: 'arterial', elementType: 'geometry', stylers: { color: '#0000ff' } },
  { featureType: 'highway', elementType: 'geometry', stylers: { color: '#ff9d00' } },
]

/** 候选 A（计划步骤 2 定稿表）：暖调三级 + 描边，地面不动。 */
const P2_CANDIDATE_A: Rule[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: LAND } },
  { featureType: 'water', elementType: 'geometry', stylers: { color: '#e2ecf3' } },
  { featureType: 'green', elementType: 'geometry', stylers: { color: '#e9efe6' } },
  { featureType: 'building', elementType: 'geometry', stylers: { color: '#f2f4f2' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#f7f1e3' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#e3dcc9' } },
  { featureType: 'local', elementType: 'geometry', stylers: { color: '#f7f1e3' } },
  { featureType: 'local', elementType: 'geometry.stroke', stylers: { color: '#e3dcc9' } },
  { featureType: 'arterial', elementType: 'geometry', stylers: { color: '#f0e4c9' } },
  { featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#d5c4a0' } },
  { featureType: 'highway', elementType: 'geometry', stylers: { color: '#e2d2ad' } },
  { featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#b39d6e' } },
]

/** 候选 B（对照组）：靠压暗地面抬白路面 —— 计划已否决，留作「为什么否决」的实物证据。 */
const P3_CANDIDATE_B: Rule[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f4f5f2' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#dfe3de' } },
  { featureType: 'arterial', elementType: 'geometry', stylers: { color: '#e8e3d5' } },
  { featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#cfc7b3' } },
  { featureType: 'highway', elementType: 'geometry', stylers: { color: '#ded7c2' } },
  { featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#b9ae95' } },
]

type Panel = {
  id: string
  title: string
  /** 判读口径直接印在卡片上，避免事后凭记忆解释。 */
  verdict: string
  style: Rule[] | null
}

/**
 * 模式二：**单键矩阵**（`?mode=singles`）。
 *
 * 起因：首轮 P0 把 land + 四级 `geometry` 塞进同一份 styleJson，结果四位候选色
 * 一个都没出现、且百度默认的黄/橙道路也被刷白——**无法归因是"哪个键无效"还是
 * "land 规则本身盖住了道路"**。混在一起的探针只能给出「整体不像话」，
 * 给不出枚举清单需要的「这个键有效/无效」。故拆成每图一键。
 *
 * S0 是对照（不下发），其余每图只加一条规则；判据是「能否在图上看到该键指定的颜色」。
 */
const SINGLES: Panel[] = [
  {
    id: 's0',
    title: 'S0 对照 · 不下发任何样式（百度默认）',
    verdict: '基线：应看到黄/橙主干道与高速——后续各图与之逐像素对照',
    style: null,
  },
  {
    id: 's1',
    title: 'S1 仅 road/geometry = #ff0000',
    verdict: '出现红 ⇒ road 面层键有效（父级）；无红 ⇒ 无效或道路无 fill 面',
    style: [{ featureType: 'road', elementType: 'geometry', stylers: { color: '#ff0000' } }],
  },
  {
    id: 's2',
    title: 'S2 仅 local/geometry = #00c000',
    verdict: '出现绿 ⇒ local 面层键有效；无绿 ⇒ 该键在本 SDK 无效（静默忽略）',
    style: [{ featureType: 'local', elementType: 'geometry', stylers: { color: '#00c000' } }],
  },
  {
    id: 's3',
    title: 'S3 仅 arterial/geometry = #0000ff',
    verdict: '出现蓝 ⇒ arterial 面层键有效；无蓝 ⇒ 无效',
    style: [{ featureType: 'arterial', elementType: 'geometry', stylers: { color: '#0000ff' } }],
  },
  {
    id: 's4',
    title: 'S4 仅 highway/geometry = #ff9d00',
    verdict: '橙黄与默认高速近似，故与 S0 对照看「高速是否变成更饱和的橙」',
    style: [{ featureType: 'highway', elementType: 'geometry', stylers: { color: '#ff9d00' } }],
  },
  {
    id: 's5',
    title: 'S5 仅 land/geometry = #ffffff',
    verdict: '关键对照：若黄/橙道路随之消失 ⇒ land 规则本身会盖住道路（根因方向完全不同）',
    style: [{ featureType: 'land', elementType: 'geometry', stylers: { color: '#ffffff' } }],
  },
  {
    id: 's6',
    title: 'S6 仅 arterial/geometry.stroke = #0000ff',
    verdict: '若蓝只出现在道路轮廓 ⇒ 该键（stroke 域）有效，可作为分级表达',
    style: [{ featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#0000ff' } }],
  },
]

const DEFAULT_PANELS: Panel[] = [
  {
    id: 'p0',
    title: 'P0 键探针（四级各涂一色）',
    verdict: '判读：出现 4 种颜色 ⇒ 面层接受分级键；只有 1 种 ⇒ 键有效但不分级，走降级阶梯',
    style: P0_PROBE,
  },
  {
    id: 'p1',
    title: 'P1 现状（线上 LIGHT 样式）',
    verdict: '问题锚点：应当「几乎看不见道路」，与用户截图一致',
    style: lcMapStyle(false) as Rule[],
  },
  {
    id: 'p2',
    title: 'P2 候选 A（暖调三级 + 描边）',
    verdict: '目标态：街道网格可见、三级可区分、仍属低饱和',
    style: P2_CANDIDATE_A,
  },
  {
    id: 'p3',
    title: 'P3 候选 B（压暗地面，已否决）',
    verdict: '对照：证明「把可读性外包给背景」的单机制不如色相分离',
    style: P3_CANDIDATE_B,
  },
  {
    id: 'p4',
    title: 'P4 百度默认（不下发任何样式）',
    verdict: '阈值锚点来源：量它各级道路 vs 地面的实际渲染对比度',
    style: null,
  },
]

/** 模式三：人工视觉比对用（`?mode=default`，默认）。 */
/**
 * 单键矩阵 · B 组（`?mode=singles-b`）。
 *
 * A 组已否掉一批键：`road/geometry` 一旦出现（任何颜色）整条道路层即不可见；
 * `local|arterial/geometry` 与 `arterial/geometry.stroke` 被静默忽略。
 * 故 B 组转向**官方文档唯一示范过的键** `elementType: 'geometry.stroke'`，
 * 并单独测「是"写了 road/geometry"这件事致命，还是那个颜色致命」。
 */
const SINGLES_B: Panel[] = [
  {
    id: 't0',
    title: 'T0 仅 road/geometry.stroke = #ff0000（官方文档示范键）',
    verdict: '出现红 ⇒ 道路是"描边渲染"，分级色应落在 stroke 域——修复方向随之确定',
    style: [{ featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#ff0000' } }],
  },
  {
    id: 't1',
    title: 'T1 仅 highway/geometry.stroke = #0000ff',
    verdict: '只染高速描边 ⇒ 该分级键在 stroke 域是否有效',
    style: [{ featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#0000ff' } }],
  },
  {
    id: 't2',
    title: 'T2 仅 road/geometry = #ffffff（与默认路白同值）',
    verdict: '若道路仍消失 ⇒ 致命的是"这条规则的存在"而非颜色；若正常 ⇒ 是颜色问题',
    style: [{ featureType: 'road', elementType: 'geometry', stylers: { color: '#ffffff' } }],
  },
  {
    id: 't3',
    title: 'T3 仅 land/geometry = #f5f5f5（与默认地色同值）',
    verdict: '对照组：证明"写一条同值规则"本身无副作用',
    style: [{ featureType: 'land', elementType: 'geometry', stylers: { color: '#f5f5f5' } }],
  },
  {
    id: 't4',
    title: 'T4 road/geometry.stroke = #ff0000 ＋ land/geometry = #f7f2ea',
    verdict: '候选 A 的真实落点形状（地面+道路描边），看能否既保底图观感又保住路',
    style: [
      { featureType: 'land', elementType: 'geometry', stylers: { color: '#f7f2ea' } },
      { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#ff0000' } },
    ],
  },
  {
    id: 't5',
    title: 'T5 仅 local/geometry.stroke = #00c000',
    verdict: '"一般道路"在 stroke 域是否有独立键',
    style: [{ featureType: 'local', elementType: 'geometry.stroke', stylers: { color: '#00c000' } }],
  },
]

/**
 * 单键矩阵 · C 组（`?mode=singles-c`）：**候选方案的正面对照**。
 *
 * A/B 两组已确认「自绘道路面层」在这套 SDK 上不可靠（4 个分级键静默忽略、
 * 父级 `road/geometry` 一写就整层不可见）。于是把候选摆开比：
 * 直接交还百度默认面层、只保留我们的注记纪律，会得到什么。
 *
 * 全部规则**从线上常量切分而来**（`lcMapStyle(false)` 按 `elementType` 拆两段），
 * 不写第二份副本——否则验的就不是线上那份样式。
 */
const SHIPPED = lcMapStyle(false) as Rule[]
const NOTES_RULES = SHIPPED.filter((r) => r.elementType.startsWith('labels'))
const FACE_RULES = SHIPPED.filter((r) => !r.elementType.startsWith('labels'))
/** 只保留 land/water/green/building 的面色，剔除全部 road 相关规则 */
const TONE_RULES = FACE_RULES.filter(
  (r) => !['road', 'arterial', 'highway', 'local'].includes(r.featureType),
)
// v4 后 `FACE_RULES` 与 `TONE_RULES` 同形（面层只剩 land）—— 保留两个名字，
// 是因为它们**表达的是不同的问题**（前者问"线上面层是什么"，后者问"去掉道路后剩什么"），
// 将来若要复核某条 road 规则，两者会重新分叉。

/**
 * **历史反例**：修复前的 `LC_FACE_STYLE` 八条，逐字节存档（自 `git show HEAD:` 取出）。
 *
 * 唯一一处允许硬编码色值的地方 —— 它的用途就是「证明修复前长什么样」，
 * 不能从线上常量取（那已经是被修好的版本了）。八条里四条把道路涂白：
 * `road/geometry=#ffffff` 盖掉全部三级道路，`arterial`/`highway` 只写 stroke、
 * `geometry` 缺失继承纯白 —— 这正是 U0→U5 逐像素 40,290 个道路像素变地面色的来源。
 */
const LEGACY_FACE_PRE_FIX: Rule[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f9faf8' } },
  { featureType: 'water', elementType: 'geometry', stylers: { color: '#e2ecf3' } },
  { featureType: 'green', elementType: 'geometry', stylers: { color: '#e9efe6' } },
  { featureType: 'building', elementType: 'geometry', stylers: { color: '#f2f4f2' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#e6e9e7' } },
  { featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#dfe4df' } },
  { featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#d8ddd9' } },
]

const SINGLES_C: Panel[] = [
  {
    id: 'u0',
    title: 'U0 不下发任何样式（百度默认锚点）',
    verdict: '基线：三级道路齐全（地灰/路白/主干黄/高速橙）。与 U1 逐像素对照即知注记纪律的代价',
    style: null,
  },
  {
    id: 'u1',
    title: 'U1 只下发注记纪律（面层交还百度默认）',
    verdict: '候选甲：道路分级原样保留，第三方设施名与图钉按纪律关掉',
    style: NOTES_RULES,
  },
  {
    id: 'u2',
    title: '⭐ U2 注记纪律 ＋ 面色（land 一条，无任何 road 规则）＝ 终版',
    verdict: '候选乙（已采纳）：候选甲加回画布底色 #f9faf8，且完全不碰道路键 —— 与 U6 逐像素应当一致',
    style: [...TONE_RULES, ...NOTES_RULES],
  },
  {
    id: 'u3',
    title: 'U3 ＝ U2 ＋ road/geometry.stroke = #d8cbb0',
    verdict: '在"完全不碰 road/geometry"前提下，描边域能否参与道路表达（实测：不足以表达分级，故未采纳）',
    style: [
      ...TONE_RULES,
      { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#d8cbb0' } },
      ...NOTES_RULES,
    ],
  },
  {
    id: 'u4',
    title: 'U4 ＝ U2 ＋ arterial/highway 的 geometry 填色',
    verdict: '复核 A 组结论：arterial/highway 面层键仍被静默忽略（应与 U2 无变化）',
    style: [
      ...TONE_RULES,
      { featureType: 'arterial', elementType: 'geometry', stylers: { color: '#f0e4c9' } },
      { featureType: 'highway', elementType: 'geometry', stylers: { color: '#e2d2ad' } },
      ...NOTES_RULES,
    ],
  },
  {
    id: 'u5',
    title: 'U5 事故原形（修复前的 LC_FACE_STYLE，八条存档）',
    verdict: '问题锚点：道路应整体不可见 —— 与 U0/U2 的差就是本次事故的全部（40,290 像素被涂成地面色）',
    style: [...LEGACY_FACE_PRE_FIX, ...NOTES_RULES],
  },
  {
    id: 'u6',
    title: 'U6 终版线上（`lcMapStyle(false)` 现取值）',
    verdict: '定稿：应与 U2 逐像素一致；与 U5 的对照即"修复生效"的直接证据',
    style: SHIPPED,
  },
]

/**
 * 面色键探针（`?mode=tones`）：`water/green/building` 三个键是否真的生效。
 *
 * C 组的 U1→U2 差异里，`land` 被确证（95.9% 的像素变成我们的地色），但
 * water/green/building 的变化量对不上我们写下的色值——**可能是生效后又被默认层覆盖**，
 * 也可能只是"因为 land 变了而浮出来"。按枚举清单纪律：未确证的一律不得写入，
 * 故涂刺眼色一次问清。
 */
const SINGLES_TONES: Panel[] = [
  {
    id: 'v0',
    title: 'V0 不下发任何样式（对照）',
    verdict: '基线',
    style: null,
  },
  {
    id: 'v1',
    title: 'V1 water=#ff00ff ／ green=#00ff00 ／ building=#0000ff',
    verdict: '三个要素不重叠，故一图可判三键：出现哪个刺眼色即该键生效',
    style: [
      { featureType: 'water', elementType: 'geometry', stylers: { color: '#ff00ff' } },
      { featureType: 'green', elementType: 'geometry', stylers: { color: '#00ff00' } },
      { featureType: 'building', elementType: 'geometry', stylers: { color: '#0000ff' } },
    ],
  },
  {
    id: 'v2',
    title: 'V2 现面色规则原样（land/water/green/building，线上取值）',
    verdict: '对照 V1：若 V1 生效而 V2 的颜色"看不出来"，说明是被默认层压掉而非规则无效',
    style: TONE_RULES,
  },
]

const MODE_RAW = new URLSearchParams(location.search).get('mode') ?? 'default'
const MODES: Record<string, Panel[]> = {
  default: DEFAULT_PANELS,
  singles: SINGLES,
  'singles-b': SINGLES_B,
  'singles-c': SINGLES_C,
  'tones': SINGLES_TONES,
}
const MODE = MODE_RAW in MODES ? MODE_RAW : 'default'
const PANELS: Panel[] = MODES[MODE]

function fill(id: string, html: string): void {
  const el = document.getElementById(id)
  if (el) el.innerHTML = html
}

/**
 * 机器可读的就绪信号：截图脚本靠它判断「瓦片真的画完了」。
 * 起因：无头 Chrome 在 load 事件后立刻截图，截到五张空白面板——
 * 靠 `sleep` 猜时长的取证是**又一次**「截图看着像失败还是真失败」的歧义。
 */
type ProbeHook = { maps: unknown[]; tilesLoaded: number; state: string }

function probeHook(): ProbeHook {
  const w = window as unknown as { __probe?: ProbeHook }
  w.__probe ??= { maps: [], tilesLoaded: 0, state: 'init' }
  return w.__probe
}

/** 把一份 style 的路面/描边色与地面的对比度算出来，供与真机观感互相印证。 */
function contrastTable(style: Rule[] | null): string {
  if (!style) return '（默认底图，无 styleJson —— 对比度须由像素采样得出）'
  const land = style.find((r) => r.featureType === 'land' && r.elementType === 'geometry')
  const landColor = (land?.stylers?.color as string | undefined) ?? '—'
  const rows = ['road', 'local', 'arterial', 'highway']
    .map((ft) => {
      const g = style.find((r) => r.featureType === ft && r.elementType === 'geometry')
      const s = style.find((r) => r.featureType === ft && r.elementType === 'geometry.stroke')
      const gc = g?.stylers?.color as string | undefined
      const sc = s?.stylers?.color as string | undefined
      return `<tr><td>${ft}</td><td>${gc ?? '<b>缺失</b>'}</td><td>${
        gc && landColor !== '—' ? cr(gc, landColor) : '—'
      }</td><td>${sc ?? '缺失'}</td><td>${sc && gc ? cr(sc, gc) : '—'}</td></tr>`
    })
    .join('')
  return `<table class="cmp"><thead><tr><th>featureType</th><th>geometry</th><th>vs 地面</th><th>stroke</th><th>vs 自身路面</th></tr></thead><tbody>${rows}</tbody></table><div class="muted">地面 ${landColor}</div>`
}

async function main(): Promise<void> {
  const hook = probeHook()
  const cfg = await getMapConfig()
  const pre = [
    `browser_ak：${cfg.browserAk ? '已取得 ✅' : '<b>缺失 ❌</b>（地图无法渲染）'}`,
    `map_style_id：<code>${cfg.mapStyleId || '(空)'}</code> ${
      cfg.mapStyleId ? '<b>❌ 控制台样式会整体压过 styleJson，本次取证无效</b>' : '✅ 未抢占'
    }`,
    `中心：凯里老街 [${CENTER[0].toFixed(5)}, ${CENTER[1].toFixed(5)}] · zoom ${ZOOM}`,
  ].join('<br>')
  fill('precheck', pre)
  if (!cfg.browserAk) {
    hook.state = 'no-ak'
    return
  }

  const B = await loadBMapGL(cfg.browserAk)
  if (!B) {
    fill('precheck', `${pre}<br><b>❌ BMapGL 加载失败</b>`)
    hook.state = 'no-sdk'
    return
  }

  for (const p of PANELS) {
    const host = document.getElementById(`map-${p.id}`)
    if (!host) continue
    const map = new B.Map(host, { zoom: ZOOM, enableHighResZoom: true })
    hook.maps.push(map)
    map.addEventListener?.('tilesloaded', () => {
      hook.tilesLoaded += 1
    })
    map.centerAndZoom(new B.Point(CENTER[0], CENTER[1]), ZOOM)
    map.enableScrollWheelZoom?.()
    if (p.style) map.setMapStyleV2({ styleJson: p.style })
    fill(`note-${p.id}`, `${p.verdict}<br>${contrastTable(p.style)}`)
  }
  hook.state = 'dispatched'
  fill('status', `${PANELS.length} 张图已下发（mode=${MODE}）。等瓦片与矢量底图稳定后再截图。`)
}

fill(
  'table',
  PANELS.map(
    (p) =>
      `<section class="card"><h2>${p.title}</h2><div class="map" id="map-${p.id}"></div><div class="note" id="note-${p.id}">加载中…</div></section>`,
  ).join(''),
)

probeHook().state = 'booting'
void main()

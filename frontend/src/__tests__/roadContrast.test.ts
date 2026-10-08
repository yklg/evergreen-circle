/**
 * 底图面层契约（grand-shoal-moth · v4 定稿）—— 道路可读性的**负向不变量**。
 *
 * ## 被守护的事故
 *
 * 用户在 `localhost:3400/compare` 上看不到城市道路：没有主干道/次干道的颜色分级，
 * 街道网格几乎不可见（同一区域在百度官方预览页道路清晰）。机制经真机逐像素 diff 确证：
 * `LC_FACE_STYLE` 只给 `arterial`/`highway` 写了 `geometry.stroke`、没写 `geometry`，
 * 三级道路全部继承 `road/geometry = #ffffff` ⇒ 百度用来表达等级的黄/橙主干道被统一刷白，
 * U0→U5 逐像素显示 **40,290 个道路像素被涂成地面色**。
 *
 * ## 为什么断言是「负向」的
 *
 * 原方案想用「对比度阈值」锁住道路分级。步骤 0 的 P4 锚点实测推翻了它：
 * 百度默认底图上**主干道 vs 地面只有 1.082，比一般道路的 1.090 还低** ——
 * 分级靠**色相与描边**表达，不靠亮度差。任何 `≥ 1.x` 的亮度阈值都会把
 * 百度自己的默认底图判成不合格。所以本文件锁的是：
 * **哪些键绝对不许写** + **枚举域不许越界** + **面层不许被注记轴切掉**。
 *
 * 色值层面的「好看不好看」不归本文件管；本文件管的是「写了就等于把路抹掉」。
 *
 * 算子取自 `src/dev/contrast.ts`、枚举清单取自 `src/dev/verifiedStyleKeys.ts` ——
 * 与取证页同一份真源，不存在第二套口径。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { LC_MAP_STYLE_LIGHT, LC_MAP_STYLE_NOTES_ON, lcMapStyle } from '../lib/bmapStyle'
import { LC_ISO_COLORS, LC_ISO_COLORS_B, lcFillSpec } from '../lib/livingCircle'
import { GEOMETRY_VERIFIED, KEY_EVIDENCE, LABELS_VERIFIED } from '../dev/verifiedStyleKeys'
import { blendOver, cr, hexToRgb } from '../dev/contrast'

type Rule = { featureType: string; elementType: string; stylers: Record<string, unknown> }

/** 画布底色（= 面层 `land` 取值）。三处 SVG 快照的地色必须与它同值。 */
const CANVAS_BG = '#f9faf8'

/** 百度默认底图的实测地面色 —— 锚点表的基准。 */
const BAIDU_LAND = '#f5f5f5'

const faceOf = (rules: readonly unknown[]): Rule[] =>
  (rules as Rule[]).filter((r) => !String(r.elementType).startsWith('labels'))
const notesOf = (rules: readonly unknown[]): Rule[] =>
  (rules as Rule[]).filter((r) => String(r.elementType).startsWith('labels'))
const key = (ft: string, et: string): string => `${ft}/${et}`

const LIGHT = lcMapStyle(false)
const NOTES_ON = lcMapStyle(true)

const read = (rel: string): string => readFileSync(resolve(process.cwd(), rel), 'utf8')

/* ══════════════════════════════════════════════════════════════════════════
 * A · 面层负向不变量：这些键一条都不许写
 * ══════════════════════════════════════════════════════════════════════════ */

/**
 * 实测判定为**静默忽略**或**有害**的面层键（每条的实测现象见 `verifiedStyleKeys.ts`）。
 *
 * 名单短得可疑是有原因的：面层侧唯一有效的键只有 `land`。这不是"我们没试够"，
 * 而是这台 SDK 的事实 —— 20 个 POI 家族候选名全部无效的同类经验，文件头 ①② 已记过。
 */
const FORBIDDEN_FACE: [featureType: string, elementType: string, why: string][] = [
  ['road', 'geometry', 'S1/T2：设 #ff0000 与设 #ffffff 得到完全相同的直方图 ⇒ 规则存在本身即把整层涂成地面色'],
  ['road', 'geometry.stroke', 'T0：该实例瓦片未渲染完、观测作废；未验证不得写入'],
  ['arterial', 'geometry', 'S3/U4：涂 #0000ff 与 #f0e4c9 均无变化（静默忽略）'],
  ['arterial', 'geometry.stroke', 'S6/T1：无任何变化'],
  ['highway', 'geometry', 'S4/U4：高速橙 809→0 且替换色出现 0 ⇒ 分级被抹掉'],
  ['highway', 'geometry.stroke', 'T1：高速橙 -15% 且无蓝色像素 ⇒ 不足以表达分级'],
  ['local', 'geometry', 'S2：与不下发样式的 S0 直方图逐项一致'],
  ['local', 'geometry.stroke', 'T5：同 S0'],
]

describe('A · 面层负向不变量（本次事故的直接防线）', () => {
  it('道路面层键一条都不许写 —— 写了不是静默无效就是把整层打掉', () => {
    for (const mode of [false, true]) {
      const rules = lcMapStyle(mode)
      for (const [ft, et, why] of FORBIDDEN_FACE) {
        const hit = (rules as Rule[]).find((r) => r.featureType === ft && r.elementType === et)
        expect(
          hit,
          `${key(ft, et)} 出现在 lcMapStyle(${mode}) —— ${why}（见 bmapStyle.ts ⑪⑫）`,
        ).toBeUndefined()
      }
    }
  })

  it('两态的面层规则恰好是 `land/geometry` 一条，且色值 = 画布底色', () => {
    for (const mode of [false, true]) {
      const face = faceOf(lcMapStyle(mode))
      expect(face.map((r) => key(r.featureType, r.elementType)), `面层规则集合漂移（mode=${mode}）`).toEqual([
        'land/geometry',
      ])
      expect(face[0].stylers.color, 'land 面色必须对齐画布 #f9faf8').toBe(CANVAS_BG)
    }
  })

  it('面层有效键集合只有一个成员 —— 清单本身即「为什么交还百度默认」的证据', () => {
    expect([...GEOMETRY_VERIFIED]).toEqual(['land'])
    // 注记侧白名单是另一回事（`arterial` 在注记侧有效、面层侧无效），不得互相背书
    expect(LABELS_VERIFIED.size).toBeGreaterThanOrEqual(11)
    for (const ft of ['road', 'arterial', 'highway', 'local']) {
      expect(LABELS_VERIFIED.has(ft), `${ft} 应在注记侧白名单里`).toBe(true)
      expect(GEOMETRY_VERIFIED.has(ft), `${ft} 不得出现在面层有效集里`).toBe(false)
    }
  })

  it('三处 SVG 快照（live 降级 / 报告快照 / 归一化遮罩）的地色与面层同值', () => {
    // §13 W1 之后，降级画布与报告快照的底 rect 只剩**一份实现**（`LcSvgCanvas` 的 `LcCanvasBackdrop`）。
    // 原来那句"三处各自硬编码、只改一处就出色差台阶"的风险被结构性消灭了，闸因此**收紧**：
    // 装配里必须有那颗地色字面量，两个消费方必须渲染它、且不许再自带副本。
    expect(read('src/components/lifecircle/LcSvgCanvas.tsx'), `共享装配缺少 fill="${CANVAS_BG}" 的底 rect`)
      .toContain(`fill="${CANVAS_BG}"`)
    for (const rel of [
      'src/components/lifecircle/LcMap.tsx',
      'src/components/lifecircle/LifeCircleReportView.tsx',
    ]) {
      const src = read(rel)
      expect(src, `${rel} 没渲染共享底网格装配`).toContain('<LcCanvasBackdrop />')
      expect(src, `${rel} 又自带了一份地色副本 ⇒ 色差台阶回到原点`).not.toContain(`fill="${CANVAS_BG}"`)
    }
    // 归一化遮罩是另一张画布（对比页圈形示意），没参与本次收装配 ⇒ 继续逐字比它的 rect。
    expect(read('src/components/lifecircle/NormalizedOverlay.tsx'), `遮罩缺少 fill="${CANVAS_BG}" 的底 rect`)
      .toContain(`fill="${CANVAS_BG}"`)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * B · TC-R05 枚举门禁：把真机探针的结论变成永久资产
 * ══════════════════════════════════════════════════════════════════════════ */

const ELEMENT_TYPES = new Set(['geometry', 'geometry.stroke', 'labels', 'labels.icon'])

/** 门禁本体：返回问题列表（空 = 通过）。抽成函数是为了能对坏输入自证会红。 */
function auditRules(rules: readonly Rule[]): string[] {
  const problems: string[] = []
  for (const r of rules) {
    if (!ELEMENT_TYPES.has(r.elementType)) {
      problems.push(`elementType 不在实测有效集内：${r.elementType}`)
      continue
    }
    const isFace = r.elementType.startsWith('geometry')
    // 两个枚举域分开校验：注记侧清单不得为面层背书，反之亦然
    const domain = isFace ? GEOMETRY_VERIFIED : LABELS_VERIFIED
    if (!domain.has(r.featureType)) {
      problems.push(
        `${isFace ? '面层' : '注记'}域的未验证 featureType：${r.featureType}（域内有效：${[...domain].join('/')}）`,
      )
    }
  }
  return problems
}

describe('B · TC-R05 枚举门禁（百度不发布 style-spec，故只能钉住实测结论）', () => {
  it('两态下发的每条规则都落在实测枚举清单内', () => {
    for (const mode of [false, true]) {
      const problems = auditRules(lcMapStyle(mode) as Rule[])
      expect(problems, `lcMapStyle(${mode}) 越界：\n${problems.join('\n')}`).toEqual([])
    }
  })

  it('门禁自身会红 —— 拿实测判定为「静默忽略」的键喂它，必须报错', () => {
    // 只断言"当前代码通过"是假防线：函数写错了也永远绿。故反向自证。
    expect(auditRules([{ featureType: 'water', elementType: 'geometry', stylers: { color: '#ffffff' } }]))
      .toEqual([expect.stringContaining('面层')])
    expect(auditRules([{ featureType: 'poilabel', elementType: 'labels', stylers: { visibility: 'off' } }]))
      .toEqual([expect.stringContaining('注记')])
    expect(auditRules([{ featureType: 'land', elementType: 'geometry.fill', stylers: { color: '#ffffff' } }]))
      .toEqual([expect.stringContaining('elementType')])
  })

  it('实测判定「不生效 / 有害」的面层键共 7 个，全部有据可查', () => {
    const rejected = new Set(
      KEY_EVIDENCE.filter(
        (e) => e.verdict !== 'works' && !e.featureType.includes('…') && e.probe.match(/^[STUV]/),
      ).map((e) => e.featureType),
    )
    // 面层域实测否掉的键：water/green/building（静默忽略）+ local/arterial（静默忽略）+ road/highway（有害）
    expect([...rejected].sort()).toEqual(
      ['arterial', 'building', 'green', 'highway', 'local', 'road', 'water'].sort(),
    )
    for (const e of KEY_EVIDENCE) {
      expect(e.observed.length, `${e.featureType}(${e.probe}) 的实测记录不能是空话`).toBeGreaterThan(10)
      expect(e.zoom, `${e.featureType} 缺验证比例尺`).toBeGreaterThanOrEqual(13)
    }
  })

  it('`road` 只允许出现在注记轴上（面层轴上的 road 是事故原形）', () => {
    expect(
      (LIGHT as Rule[]).filter((r) => r.featureType === 'road').map((r) => r.elementType),
    ).toEqual(['labels'])
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * C · 面层常驻性（决策 3：不加第三颗 pill，但也不许被注记开关切掉）
 * ══════════════════════════════════════════════════════════════════════════ */

describe('C · 面层常驻 + 结构自检', () => {
  it('注记开/关两态的面层逐字节相等（面层在结构上不属于注记轴）', () => {
    expect(faceOf(NOTES_ON)).toEqual(faceOf(LIGHT))
  })

  it('面层排在最前（后发覆盖语义下，注记规则不得把面层压掉）', () => {
    expect(faceOf(LIGHT)).toHaveLength(1)
    expect((LIGHT as Rule[])[0].elementType).toBe('geometry')
    expect((NOTES_ON as Rule[])[0].elementType).toBe('geometry')
  })

  it('导出常量是预计算同一引用（`toBe` 而非 `toEqual` —— 调用方靠引用判「下发的就是内置模板」）', () => {
    expect(lcMapStyle(false)).toBe(LC_MAP_STYLE_LIGHT)
    expect(lcMapStyle(true)).toBe(LC_MAP_STYLE_NOTES_ON)
  })

  it('TC-R11 结构自检：每条规则结构合法（非法结构会被百度静默忽略，与本次同形）', () => {
    for (const rules of [LIGHT, NOTES_ON]) {
      for (const r of rules as Rule[]) {
        const at = key(r.featureType, r.elementType)
        expect(typeof r.featureType, `${at} featureType 非字符串`).toBe('string')
        expect(r.featureType.length, `${at} featureType 为空`).toBeGreaterThan(0)
        expect(ELEMENT_TYPES.has(r.elementType), `${at} elementType 非实测有效值`).toBe(true)
        expect(r.stylers, `${at} 缺 stylers`).toBeTruthy()
        const s = r.stylers
        if (s.color !== undefined) expect(s.color, `${at} color 不是 6 位 hex`).toMatch(/^#[0-9a-f]{6}$/i)
        if (s.visibility !== undefined) expect(['on', 'off'], `${at} visibility 非 on/off`).toContain(s.visibility)
        expect(
          s.color !== undefined || s.visibility !== undefined,
          `${at} 既无 color 也无 visibility —— 等于没写`,
        ).toBe(true)
      }
    }
  })

  it('域纪律：面层只写 color、注记只写 visibility（注记带 color 会把可见性再次打掉，见 ④）', () => {
    for (const rules of [LIGHT, NOTES_ON]) {
      for (const r of faceOf(rules)) {
        expect(r.stylers.color, `${key(r.featureType, r.elementType)} 面层必须写 color`).toBeTruthy()
        expect(r.stylers.visibility, '面层不得出现 visibility（注记轴越界）').toBeUndefined()
      }
      for (const r of notesOf(rules)) {
        expect(r.stylers.visibility, `${key(r.featureType, r.elementType)} 注记必须写 visibility`).toBeTruthy()
        expect(
          r.stylers.color,
          `${key(r.featureType, r.elementType)} 注记带了 color —— 实测会让整层注记再次消失（bmapStyle.ts ④）`,
        ).toBeUndefined()
      }
    }
  })

  it('开启态整段不含 visibility:off（否则"开"了注记会被自己的隐藏规则覆盖，R3）', () => {
    expect(JSON.stringify(LC_MAP_STYLE_NOTES_ON)).not.toContain('"off"')
    expect(JSON.stringify(LC_MAP_STYLE_LIGHT)).toContain('"off"')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * D · OBS-01 锚点表（用途 = 日后比对是否漂移，**不是**阈值来源）
 * ══════════════════════════════════════════════════════════════════════════ */

/** 百度默认底图实测（凯里老街 zoom 15，1170×420，全像素 491,400）。 */
const ANCHORS: [name: string, color: string, share: number, vsLand: number][] = [
  ['地面 land', BAIDU_LAND, 66.2, 1.0],
  ['一般道路', '#ffffff', 5.8, 1.09],
  ['主干道 arterial', '#ffebb4', 1.96, 1.08],
  ['高速 highway', '#ffb269', 0.66, 1.63],
  ['水面', '#75e0f9', 0.99, 1.4],
  ['绿地', '#b5f2bf', 0.65, 1.17],
]

describe('D · OBS-01 锚点表（外部基准，防止阈值自我证明）', () => {
  it('锚点色值与对比度自洽（用同一算子复算）', () => {
    for (const [name, color, share, vsLand] of ANCHORS) {
      expect(cr(color, BAIDU_LAND), `${name} 的对比度与锚点表不符`).toBe(vsLand)
      expect(share, `${name} 占比超范围`).toBeGreaterThan(0)
      expect(share).toBeLessThanOrEqual(100)
    }
  })

  it('主干道对比度低于一般道路 —— 分级靠色相与描边，不得用亮度阈值验分级', () => {
    const arterial = ANCHORS.find(([n]) => n.startsWith('主干道'))![3]
    const local = ANCHORS.find(([n]) => n === '一般道路')![3]
    expect(arterial).toBeLessThan(local)
    // 若有人把「≥ 1.1」写成门禁，百度自己的默认底图就会不合格 —— 这条就是防止那次复辟
    expect(arterial).toBeLessThan(1.1)
  })

  it('U2 决策的量化代价：把地面换成 #f9faf8 后各级对比度的变化（记录，非门禁）', () => {
    const cost: [color: string, vsOurs: number][] = [
      ['#ffffff', 1.05],
      ['#ffebb4', 1.13],
      ['#ffb269', 1.7],
      ['#75e0f9', 1.45],
      ['#b5f2bf', 1.22],
    ]
    for (const [color, expected] of cost) {
      expect(cr(color, CANVAS_BG), `${color} vs ${CANVAS_BG} 与记录不符`).toBe(expected)
    }
    // 结论性地记一笔：换地色让一般道路 1.09→1.05（降），但主干道 1.08→1.13、高速 1.63→1.70（升）
    expect(cr('#ffffff', CANVAS_BG)).toBeLessThan(cr('#ffffff', BAIDU_LAND))
    expect(cr('#ffebb4', CANVAS_BG)).toBeGreaterThan(cr('#ffebb4', BAIDU_LAND))
  })

  it('锚点表与 `bmapStyle.ts` 文件头 ⑩ 同源（两处数字必须一起改）', () => {
    const src = read('src/lib/bmapStyle.ts')
    expect(src, '文件头缺少地面占比锚点').toContain('66.2%')
    expect(src, '文件头缺少主干道锚点').toContain('1.082')
    expect(src, '文件头缺少一般道路锚点').toContain('1.090')
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * E · 等时圈透明度（放大项：同色填充叠在同色路面上会二次遮挡）
 * ══════════════════════════════════════════════════════════════════════════ */

const opacities = (set: readonly { fill: string }[]): number[] =>
  set.map((c) => lcFillSpec(c.fill).opacity)

describe('E · 等时圈四级色阶', () => {
  it('A 组（单图）四级 opacity 精确锁定', () => {
    expect(opacities(LC_ISO_COLORS)).toEqual([0.3, 0.2, 0.12, 0.06])
  })

  it('B 组（对比页右图）四级 opacity 精确锁定', () => {
    expect(opacities(LC_ISO_COLORS_B)).toEqual([0.28, 0.18, 0.1, 0.05])
  })

  it('两组都是 4 档、严格递减、最内圈 ≤ 0.40（不压底图道路）', () => {
    for (const [name, set] of [
      ['A', LC_ISO_COLORS],
      ['B', LC_ISO_COLORS_B],
    ] as const) {
      const ops = opacities(set)
      expect(ops, `${name} 组档数变了 —— LcMap 与报告快照按「zi % length」取色`).toHaveLength(4)
      expect(new Set(ops).size, `${name} 组 opacity 有重复（色阶失去区分度）`).toBe(4)
      for (let i = 1; i < ops.length; i++) {
        expect(ops[i], `${name} 组第 ${i + 1} 档不得 ≥ 上一档（必须内深外浅）`).toBeLessThan(ops[i - 1])
      }
      expect(Math.max(...ops), `${name} 组最内圈压色过重`).toBeLessThanOrEqual(0.4)
    }
  })

  it('A/B 同档差值受控（对比页双图并排，色阶观感不得失衡）', () => {
    const a = opacities(LC_ISO_COLORS)
    const b = opacities(LC_ISO_COLORS_B)
    for (let i = 0; i < a.length; i++) {
      expect(a[i], `第 ${i + 1} 档：A 不得浅于 B`).toBeGreaterThanOrEqual(b[i])
      expect(Math.abs(a[i] - b[i]), `第 ${i + 1} 档 A/B 差值过大`).toBeLessThanOrEqual(0.05)
    }
  })

  it('fill 必须保持 rgba 字符串（BMapGL 忽略 fillColor 的 alpha，只能由 lcFillSpec 拆）', () => {
    for (const c of [...LC_ISO_COLORS, ...LC_ISO_COLORS_B]) {
      expect(c.fill, `等时圈 fill 必须是 rgba(...)：${c.fill}`).toMatch(/^rgba\(/)
      expect(c.stroke, `描边色非法：${c.stroke}`).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * F · TC-R09 三处呈现同源
 * ══════════════════════════════════════════════════════════════════════════ */

const LC_MAP_SRC = read('src/components/lifecircle/LcMap.tsx')
const REPORT_SRC = read('src/components/lifecircle/LifeCircleReportView.tsx')
/** §13 W1 之后，降级画布与报告快照的等时圈族带／底 rect 只剩这一份实现。 */
const ASSEMBLY_SRC = read('src/components/lifecircle/LcSvgCanvas.tsx')

describe('F · TC-R09 跨呈现层同源（live Polygon / fallback SVG / 报告图例）', () => {
  it('呈现层都从 `livingCircle` 引取色，不各自定义', () => {
    // W1 前：报告快照自己索引 `LC_ISO_COLORS`。W1 后：索引只剩装配里那一处，两个消费方经
    // `<LcIsochroneBands>` 取带 —— 所以这条闸改成"装配引常量 ＋ 两档都渲染装配"，比原来严。
    expect(LC_MAP_SRC, 'LcMap 未引用单图色表').toContain('LC_ISO_COLORS')
    expect(LC_MAP_SRC, 'LcMap 未引用对比页色表').toContain('LC_ISO_COLORS_B')
    expect(ASSEMBLY_SRC, '共享装配未引用色表常量（内联色值＝第二套真源）').toContain('LC_ISO_COLORS')
    for (const [name, src] of [
      ['LcMap', LC_MAP_SRC],
      ['LifeCircleReportView', REPORT_SRC],
    ] as const) {
      expect(src, `${name} 没渲染共享等时圈族带装配`).toContain('<LcIsochroneBands')
    }
  })

  it('呈现层不得内联 rgba 色值副本（复制粘贴绕过 = 第二套真源）', () => {
    const literals = [...LC_ISO_COLORS, ...LC_ISO_COLORS_B].map((c) => c.fill.replace(/\s+/g, ''))
    for (const [name, src] of [
      ['LcMap', LC_MAP_SRC],
      ['LifeCircleReportView', REPORT_SRC],
      ['LcSvgCanvas', ASSEMBLY_SRC],
    ] as const) {
      const flat = src.replace(/\s+/g, '')
      for (const lit of literals) {
        expect(flat, `${name} 内联了等时圈色值 ${lit} —— 应引用常量`).not.toContain(lit)
      }
    }
  })

  it('三处取色点都经 `LC_ISO_COLORS*` 索引（含对比页双色表与降级 SVG）', () => {
    expect(LC_MAP_SRC, 'live Polygon 缺少双色表选择').toMatch(/colorSets/)
    expect(LC_MAP_SRC, 'live Polygon 未按 reportIndex 取色').toMatch(/colorSets\[ri\]\s*\?\?\s*LC_ISO_COLORS/)
    // 降级画布与报告快照自 W1 起共用同一颗带：取色恒按**载荷原序**取模。两档的真实差别只在绘制
    // 顺序（`drawOuterFirst`），这条正则因此同时守住了"色只有一份口径"——谁再往里加第二处索引会红。
    expect(ASSEMBLY_SRC, '共享装配未按圈层取色').toMatch(
      /LC_ISO_COLORS\[zones\.indexOf\(z\) % LC_ISO_COLORS\.length\]/,
    )
    expect((ASSEMBLY_SRC.match(/LC_ISO_COLORS\[zones\.indexOf/g) ?? []).length, '装配里按圈层取色应当只有一处')
      .toBe(1)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * G · 算子自检（算子错了，上面所有数字都失去意义）
 * ══════════════════════════════════════════════════════════════════════════ */

describe('G · contrast 算子自检', () => {
  it('黑白对比度为 21，同色为 1', () => {
    expect(cr('#000000', '#ffffff')).toBe(21)
    expect(cr(CANVAS_BG, CANVAS_BG)).toBe(1)
  })

  it('hexToRgb 接受带/不带 `#`，非法输入直接抛（不静默兜底）', () => {
    expect(hexToRgb('#f9faf8')).toEqual([249, 250, 248])
    expect(hexToRgb('f9faf8')).toEqual([249, 250, 248])
    expect(() => hexToRgb('#fff')).toThrow()
    expect(() => hexToRgb('#f9faf8ff')).toThrow()
  })

  it('blendOver：半透明覆盖色压出不透明结果', () => {
    expect(blendOver('#ffffff', 'rgba(0,0,0,0.5)')).toBe('#808080')
    expect(blendOver('#ffffff', 'rgb(0,0,0)')).toBe('#000000')
    expect(() => blendOver('#ffffff', '#000000')).toThrow()
  })

  it('锚点复算值与真机一致（算子漂移会让锚点表悄悄失真）', () => {
    expect(cr('#ffebb4', BAIDU_LAND)).toBe(1.08)
    expect(cr('#f9faf8', BAIDU_LAND)).toBe(1.04)
  })
})

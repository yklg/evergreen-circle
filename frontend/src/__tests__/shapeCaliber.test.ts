/**
 * 形状口径（第五把尺）的前端判据集。
 *
 * 重点是第 ② 组「跨端镜像」：后端键里声明的是球面 `bearing()` 分箱，而渲染层只有等距
 * 平面可用。今天两者逐箱相同（实测单点方位差 ≤0.0024°、无顶点压在箱界），但那是巧合
 * 而不是保证 —— 这条判据的作用就是哪天出现临界顶点时，红的是测试，不是屏上的方向。
 */
import { describe, expect, it } from 'vitest'

import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import {
  SHAPE_SUSPECT_CIRCULARITY,
  shapeBinOf,
  shapeCaveatNote,
  shapeOfZone,
  shapeSentence,
  shapeSuspectNote,
  shapeUnmeasuredWords,
  shapeWeakStrong,
} from '../lib/livingCircle'
import { lcMeters } from '../lib/livingCircle'
import type { LivingCircleReport, ShapeCaliber } from '../types'

const REPORTS: [string, LivingCircleReport][] = [
  ['kaili-ev2', kailiEv2 as unknown as LivingCircleReport],
  ['kaili', kaili as unknown as LivingCircleReport],
  ['beijing-jinsong', jinsong as unknown as LivingCircleReport],
]

/* ── ① 在场与缺席 ─────────────────────────────────────────── */

describe('形状口径 · 在场判据', () => {
  it.each(REPORTS)('%s：15/20 两档都读得出形状', (_n, lc) => {
    for (const m of [15, 20]) expect(shapeOfZone(lc, m)).not.toBeNull()
  })

  it.each(REPORTS)('%s：5/10 内圈不发键 ⇒ 出口返回 null（不是 0，也不是"很圆"）', (_n, lc) => {
    for (const m of [5, 10]) expect(shapeOfZone(lc, m)).toBeNull()
  })

  it('载荷整个没有 shape 键（存量件形态）⇒ 所有出口都静默', () => {
    const bare = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    bare.isochrones.forEach((z) => {
      delete (z as { shape?: ShapeCaliber }).shape
    })
    expect(shapeOfZone(bare, 15)).toBeNull()
    expect(shapeSentence(bare, 15)).toBeNull()
    expect(shapeSuspectNote(bare, 15)).toBeNull()
    expect(shapeCaveatNote(bare, 15)).toBeNull()
  })
})

/* ── ② 跨端镜像：前端分箱必须复现后端键 ─────────────────── */

describe('形状口径 · 跨端分箱镜像', () => {
  /**
   * 前端只有等距平面（`lcMeters`），后端键里的半径出自球面 `haversine_m` —— 两者在
   * 1km 尺度上差约 1m，这是**度量差**不是**分箱差**。所以这条判据钉的是真正要紧的
   * 三件事：每个方位的最大值来自同一个顶点（方向一致）、米级容差、最弱/最强方位同格。
   * 哪天有顶点压上箱界，红的是"方向不一致"这一条，而不是无意义的逐米相等。
   */
  it.each(REPORTS)('%s：15/20 两档逐箱 argmax 顶点与后端一致，半径差 ≤2m', (_n, lc) => {
    // S25：原来只钉 15min。段控把 20min 也搬上屏后，两档的环不是同一颗
    // （凯里 90 / 134 顶点；劲松两档最弱方位还不同：正西 vs 西南）⇒ 逐箱镜像按档各跑一遍。
    for (const minutes of [15, 20]) {
    const zone = lc.isochrones.find((z) => z.minutes === minutes)
    const sh = zone?.shape
    expect(sh, `${minutes}min 档该有形状键`).toBeTruthy()
    const center = lc.scene.center
    const manual = [0, 0, 0, 0, 0, 0, 0, 0]
    const argmax: (number[] | null)[] = Array(8).fill(null)
    zone!.geojson.coordinates[0].forEach(([lng, lat], vi) => {
      const [mx, my] = lcMeters(center, lng, lat)
      const r = Math.sqrt(mx * mx + my * my)
      const k = shapeBinOf(center, lng, lat)
      if (r > manual[k]) {
        manual[k] = r
        argmax[k] = [lng, lat, vi]
      }
    })
    // 本条按「八向全测到」写；真夹具今天确实全测到（sh-2 起 null 才有含义）——
    // 前提变了要当场红，不要让它悄悄退化成「只比了非空的那几格」。
    expect(sh!.bins_m.every((v) => v !== null),
      `${minutes}min 档出现了未测到的格子，本条的比法要跟着改`).toBe(true)
    const bins = sh!.bins_m as number[]
    manual.forEach((v, k) => {
      expect(Math.abs(v - bins[k])).toBeLessThanOrEqual(2)
      const [lng, lat] = sh!.bins_m.length === 8 ? (argmax[k] as [number, number, number]) : [0, 0, 0]
      // 该顶点确实落在前端算出的那个箱里（方向自证）
      expect(shapeBinOf(center, lng, lat)).toBe(k)
    })
    const mine = { weak: manual.indexOf(Math.min(...manual)), strong: manual.indexOf(Math.max(...manual)) }
    const theirs = shapeWeakStrong(sh!)
    // 极值**并列**时只比数值、不比下标：`shapeWeakStrong` 的语义是"同值取靠前者"（跨端稳定那条
    // 声明），而这里独立重算用未取整浮点 ⇒ 并列会被末位噪声打破。S25 实测撞到：
    // 劲松 20min 键里 正北 与 正东 同为 1273m —— 旧断言会红在算术噪声上，不是口径分叉。
    const tie = (arr: number[], v: number) => arr.filter((x) => Math.abs(x - v) < 0.05).length > 1
    expect(Math.abs(manual[mine.weak] - bins[theirs.weak])).toBeLessThanOrEqual(2)
    expect(Math.abs(manual[mine.strong] - bins[theirs.strong])).toBeLessThanOrEqual(2)
    if (!tie(bins, bins[theirs.weak])) expect(mine.weak, `${minutes}min 档`).toBe(theirs.weak)
    if (!tie(bins, bins[theirs.strong])) expect(mine.strong, `${minutes}min 档`).toBe(theirs.strong)
    expect(Math.abs(manual[mine.weak] / manual[mine.strong] - (sh!.weak_ratio as number))).toBeLessThan(0.005)
    }
  })

  it('并列极值是真事（劲松 20min 正北＝正东＝1273m）⇒ 屏上念哪个由"同值取靠前"定', () => {
    // 把上面那个 if 钉住：不是"懒得比下标"，而是这档确实并列。哪天数据不再并列，这里先红
    // ⇒ 提醒把 tie 分支收掉，而不是留一条永不再触发的豁免（幽灵豁免的同型纪律）。
    const j = jinsong as unknown as LivingCircleReport
    const sh = shapeOfZone(j, 20)!
    const bs = sh.bins_m as number[]
    const max = Math.max(...bs)
    const at = bs.map((v, i) => (v === max ? i : -1)).filter((i) => i >= 0)
    expect(at.length).toBeGreaterThan(1)
    expect(shapeWeakStrong(sh).strong).toBe(Math.min(...at))
    expect([sh.bins_word[at[0]], sh.bins_word[at[1]]]).toEqual(['正北', '正东'])
  })

  it('方位词只有一份出处：句子用的词必须来自键，不是前端另抄的表', () => {
    const lc = REPORTS[0][1]
    for (const m of [15, 20]) {
      const sh = shapeOfZone(lc, m)!
      const { weak } = shapeWeakStrong(sh)
      expect(shapeSentence(lc, m), `${m}min 档`).toContain(sh.bins_word[weak])
    }
    const sh = shapeOfZone(lc, 15)!
    expect(sh.bins_word).toHaveLength(8)
    expect(sh.bins_word[0]).toBe('正北')
  })
})

/* ── ③ 读侧再判一次：口径漂移一律不画 ─────────────────── */

describe('形状口径 · 篡改即失效', () => {
  const tamper = (patch: (sh: ShapeCaliber) => void, minutes = 15) => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === minutes)!
    patch(zone.shape as ShapeCaliber)
    return lc
  }
  // S25：口径漂移的判据必须**两档各判一次** —— 段控上屏后 20min 那颗也是屏上真相源。
  const bothTiers = (check: (m: number) => void) => { for (const m of [15, 20]) check(m) }

  it('分相被改成 floor（会把缺口并进相邻方向）⇒ 不画（15 与 20 两档都拒）', () => {
    bothTiers((m) => expect(shapeOfZone(tamper((sh) => { sh.bin_phase = 'floor' }, m), m)).toBeNull())
  })
  it('原点被换成质心（球面实算圆度会动 0.029、劲松最弱方位直接改口）⇒ 不画（15 与 20 两档都拒）', () => {
    bothTiers((m) => expect(shapeOfZone(tamper((sh) => { sh.origin = 'centroid' }, m), m)).toBeNull())
  })
  it('方位角实现漂移成平面 atan2 ⇒ 不画（15 与 20 两档都拒）', () => {
    bothTiers((m) => expect(shapeOfZone(tamper((sh) => { sh.azimuth_fn = 'atan2' }, m), m)).toBeNull())
  })
  it('分箱宽度漂移 ⇒ 不画（15 与 20 两档都拒）', () => {
    bothTiers((m) => expect(shapeOfZone(tamper((sh) => { sh.bin_deg = 30 }, m), m)).toBeNull())
  })
  it('标量与 bins 对不上（第二生产者留下的旧值）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.weak_ratio = 0.99 }), 15)).toBeNull()
    expect(shapeOfZone(tamper((sh) => { sh.circularity = 0.95 }), 15)).toBeNull()
  })
  it('两档互相独立：只坏 20min 那颗，15min 照读（反之亦然）', () => {
    // 段控把两档都搬上屏后，这条定"坏一档时屏上是什么"：读侧是**按档**判的，
    // 既不许"一档被污染 ⇒ 整块不发屏"，也不许"污染档静默沿用另一档的值"。
    const dirty20 = tamper((sh) => { sh.bin_phase = 'floor' }, 20)
    expect(shapeOfZone(dirty20, 20)).toBeNull()
    expect(shapeOfZone(dirty20, 15)).not.toBeNull()
    const dirty15 = tamper((sh) => { sh.bin_phase = 'floor' }, 15)
    expect(shapeOfZone(dirty15, 15)).toBeNull()
    expect(shapeOfZone(dirty15, 20)).not.toBeNull()
  })
  it('圆度只差 0.005 ⇒ 也不画（S22 两端同尺：这量级后端 B17 同样判违规）', () => {
    // 收紧前这里放行（旧容差 1e-2）而后端 1e-3 拒 ⇒ "签发严、读侧松"，
    // 绕过 B17 的手写 mock / 外部镜像反而能上屏。两侧现在共用一把尺。
    const base = shapeOfZone(kailiEv2 as unknown as LivingCircleReport, 15)!
    expect(shapeOfZone(tamper((sh) => { sh.circularity = +(base.circularity + 0.005).toFixed(3) }), 15)).toBeNull()
    // 正对照：0.0005 这种量级（键存三位小数带来的必然误差）不许误杀 ——
    // 真数据全样实测最大偏差 0.000384。
    expect(shapeOfZone(tamper((sh) => { sh.circularity = +(base.circularity + 0.0005).toFixed(4) }), 15)).not.toBeNull()
  })
  it('箱值非法（含 0 ⇒ 等于宣称某个方位一步都出不去）⇒ 不画', () => {
    expect(shapeOfZone(tamper((sh) => { sh.bins_m = [0, ...sh.bins_m.slice(1)] }), 15)).toBeNull()
  })
  it('词表里有重复（换序/填错的典型形态）⇒ 不画', () => {
    // 读侧**不许自备一份正确词表**（I-07 词表只有一份，随键下发），所以这里只能判结构：
    // 八个位置出现重复 ⇒ 一定不是同一张表。"整体转一格"那种无重复的错序只有签发闸能判，
    // 由后端 B17 的 bins_word 序核对守着（tests/test_shape_caliber.py::test_b17_catches_word_table_rotated_out_of_order）。
    expect(shapeOfZone(tamper((sh) => { sh.bins_word = [sh.bins_word[0], sh.bins_word[0], ...sh.bins_word.slice(2)] }), 15)).toBeNull()
    // 正对照：真词表八个词互不相同，剥掉这条判据就会把正常载荷也打死
    expect(new Set((kailiEv2 as unknown as LivingCircleReport).isochrones.find((z) => z.minutes === 15)!.shape!.bins_word).size).toBe(8)
  })
  it('声明字段集合与读侧校验清单逐位对齐（谁加字段忘了配对，这里先红）', () => {
    // S28 的前端这条腿：生产端发出的键集合 == 后端判据消费的集合 == 前端真在核对的清单。
    // 少一边就是"发了没人消费"的幽灵字段——本轮三条审查打穿的四条缺口全是这个形状。
    const CONSUMED_BY_READER = [
      'bins_m', 'bins_word', 'bin_deg', 'bin_phase', 'origin', 'azimuth_fn', 'circularity', 'weak_ratio',
    ]
    for (const [name, lc] of REPORTS) {
      for (const m of [15, 20]) {
        const sh = (lc.isochrones.find((z) => z.minutes === m)?.shape ?? {}) as Record<string, unknown>
        expect(Object.keys(sh).sort(), `${name}@${m}min`).toEqual([...CONSUMED_BY_READER].sort())
      }
    }
  })
})

/* ── ④ 文案：只说方向，不说好坏 ─────────────────────────── */

describe('形状口径 · 措辞边界', () => {
  it.each(REPORTS)('%s：15/20 两档句子都只指方向，且各指回本档的弱方位', (_n, lc) => {
    for (const m of [15, 20]) {
      const sh = shapeOfZone(lc, m)!
      const text = shapeSentence(lc, m) ?? ''
      expect(text, `${m}min 档该出句子`).not.toBe('')
      expect(text).toMatch(/^最弱方向：/)
      expect(text).toContain('m')
      expect(text).toContain(sh.bins_word[shapeWeakStrong(sh).weak])
      for (const banned of ['优', '良', '差', '更好', '越圆', '评分', '分]']) {
        expect(text, `${m}min 档`).not.toContain(banned)
      }
    }
  })

  it('两档最弱方位**可以不同**（劲松 15min 正西 / 20min 西南）⇒ 段控上屏后读数必须带档名', () => {
    // S25 顺带产出的 S29 依据：两档各念各的方向，不带档名就是自相矛盾。
    const j = jinsong as unknown as LivingCircleReport
    const word = (m: number) => {
      const sh = shapeOfZone(j, m)!
      return sh.bins_word[shapeWeakStrong(sh).weak]
    }
    expect(word(15)).not.toBe(word(20))
    expect([word(15), word(20)]).toEqual(['正西', '西南'])
  })

  it('常驻声明里写明不参与评分，并带四件口径（两档各一次）', () => {
    for (const m of [15, 20]) {
      const n2 = shapeCaveatNote(REPORTS[0][1], m) ?? ''
      expect(n2, `${m}min 档也要有常驻声明`).toContain('不参与综合评分')
    }
    const note = shapeCaveatNote(REPORTS[0][1], 15) ?? ''
    expect(note).toContain('不参与综合评分')
    expect(note).toContain('scene.center')
    expect(note).toContain('center')
  })
})

/* ── ⑤ 告警阈值两侧对照（正对照，防阈值判据空转）───────── */

describe('形状口径 · 退化告警两侧对照', () => {
  const withCircularity = (v: number, minutes = 15): LivingCircleReport => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === minutes)!
    const sh = zone.shape as ShapeCaliber
    // 圆度 = 等面积半径 ÷ 最远半径。面积不动时，只有把**整圈**按同比例缩放才能把最远
    // 半径压到目标值上（只改一格是改不动最大值的 —— 上一版就犯了这个错，构造出的
    // 载荷圆度没变，于是"高于阈值必现"这条正对照其实在测 null）。
    const eqR = Math.sqrt((zone.area_km2 * 1e6) / Math.PI)
    const target = eqR / v
    const bs = sh.bins_m as number[]   // 这份辅助件只拿全测到的真夹具造正对照
    const f = target / Math.max(...bs)
    const scaled = bs.map((b) => Math.round(b * f * 10) / 10)
    sh.bins_m = scaled
    sh.circularity = Math.round((eqR / Math.max(...scaled)) * 1000) / 1000
    sh.weak_ratio = Math.round((Math.min(...scaled) / Math.max(...scaled)) * 1000) / 1000
    return lc
  }

  it('高于阈值 ⇒ 告警必现（15 与 20 两档各构造一次）', () => {
    // 原来只喂 15min。段控切档时那句 warn 随**当前档**出现/消失 ⇒ 两侧对照两档各做，
    // 否则 20min 档的告警分支等于没测。
    for (const m of [15, 20]) {
      const lc = withCircularity(SHAPE_SUSPECT_CIRCULARITY + 0.01, m)
      expect(shapeSuspectNote(lc, m), `${m}min 档应命中告警`).toContain('疑为模型造形')
    }
  })
  it('低于阈值 ⇒ 整句不出现（返回 null，不是空串；两档各一次）', () => {
    for (const m of [15, 20]) {
      const lc = withCircularity(SHAPE_SUSPECT_CIRCULARITY - 0.05, m)
      expect(shapeSuspectNote(lc, m), `${m}min 档`).toBeNull()
    }
  })
  it('真件都不该命中告警（凯里 0.713 / 劲松 0.794 量级）', () => {
    for (const [, lc] of REPORTS) {
      expect(shapeSuspectNote(lc, 15)).toBeNull()
      expect(shapeSuspectNote(lc, 20)).toBeNull()
    }
  })
})

describe('形状口径 · 未测到（sh-2：null 不是 0 米）', () => {
  /**
   * 造一份「某些方向未测到」的载荷，并按剩下的格子把两颗标量改对。
   *
   * ⚠️ 要留 `drop = ALL_BUT_MAX` 而不是随便留一格：圆度是 `等面积半径 ÷ 最远可达`，
   * 只留最小的那格会算出 > 1（实测 1.025）⇒ 被 (0,1] 那道闸正当拒掉，测不到本意。
   * 这里用哨兵值表达「只留最大那一格」。
   */
  const ALL_BUT_MAX = -1
  const markUnmeasured = (
    dropIdx: number[] | typeof ALL_BUT_MAX, minutes = 15, weakRatio: number | null | 'auto' = 'auto',
  ) => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === minutes)!
    const sh = zone.shape as ShapeCaliber
    const bs = sh.bins_m as number[]
    const keep = bs.indexOf(Math.max(...bs))     // 并列时取第一个，保证只剩一格
    const drop = dropIdx === ALL_BUT_MAX
      ? bs.map((_, i) => i).filter((i) => i !== keep) : dropIdx
    sh.bins_m = bs.map((v, i) => (drop.includes(i) ? null : v))
    const vals = sh.bins_m.filter((v): v is number => v !== null)
    const eqR = Math.sqrt((zone.area_km2 * 1e6) / Math.PI)
    sh.circularity = Math.round((eqR / Math.max(...vals)) * 1000) / 1000
    sh.weak_ratio = weakRatio === 'auto'
      ? (vals.length >= 2 ? Math.round((Math.min(...vals) / Math.max(...vals)) * 1000) / 1000 : null)
      : weakRatio
    return lc
  }

  it('有方向未测到 ⇒ 照常画：诚实的缺口不许让整块面板消失', () => {
    const lc = markUnmeasured([0, 1])
    const sh = shapeOfZone(lc, 15)
    expect(sh, 'null 被读侧当成了非法值 ⇒ 缺一向等于全没有').not.toBeNull()
    expect(sh!.bins_m[0]).toBeNull()
    expect(shapeUnmeasuredWords(sh!)).toEqual(['正北', '东北'])
  })

  it('把未测到写回 0.0（sh-1 的谎）⇒ 不画', () => {
    const lc = markUnmeasured([0, 1])
    const zone = lc.isochrones.find((z) => z.minutes === 15)!
    ;(zone.shape as ShapeCaliber).bins_m = (zone.shape as ShapeCaliber).bins_m
      .map((v) => (v === null ? 0 : v))
    expect(shapeOfZone(lc, 15)).toBeNull()
  })

  it('只测到 1 个方向：发 null 合法，发 1.0 不画', () => {
    // 1.0 的既有含义是「八方一样远、形状很圆」，用它顶替「没可比对象」正好说反。
    expect(shapeOfZone(markUnmeasured(ALL_BUT_MAX), 15)).not.toBeNull()
    const lc = markUnmeasured(ALL_BUT_MAX, 15, 1.0)
    expect(shapeOfZone(lc, 15)).toBeNull()
  })

  it('八格全未测到 ⇒ 不画（这种载荷该整套不发键）', () => {
    const lc = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    const zone = lc.isochrones.find((z) => z.minutes === 15)!
    ;(zone.shape as ShapeCaliber).bins_m = Array(8).fill(null)
    expect(shapeOfZone(lc, 15)).toBeNull()
  })

  it('措辞出口把「未测到」说出来：数量与方向都给，且任何地方都不出现 0 m', () => {
    const lc = markUnmeasured([0, 7])
    const s = shapeSentence(lc, 15)!
    expect(s).toContain('另有 2 个方向未测到顶点（正北、西北）')
    expect(s).not.toMatch(/\b0 m/)
    // 只测到一面时不再拼「最弱/最强」那半句 —— 没有可比对象
    const one = shapeSentence(markUnmeasured(ALL_BUT_MAX), 15)!
    expect(one).toContain('只测到 1 个方向的顶点')
    expect(one).not.toContain('比值')
  })
})

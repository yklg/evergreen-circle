/**
 * 常青圈 · 生活圈体检 fixture 生成器（F0b）。
 *
 * 依据 F0 冻结契约（src/types.ts 的 LivingCircleReport）生成两份演示数据：
 *   - 凯里老街（贵州·欠发达样本）      → src/mocks/fixtures/livingCircle/kaili.json
 *   - 北京劲松（一线·成熟样本）        → src/mocks/fixtures/livingCircle/beijing-jinsong.json
 *
 * 数据策略（用户已确认 D1）：
 *   - POI：真实社区常识填充（真实类别 + 大致真实位置）
 *   - 等时圈：无路网「圆形近似」（circular_approx），步行速度 72m/min（1.2m/s）
 *   - data_origin = "fixture_sample"；M5 阶段由真实百度 API 全量覆写
 *
 * 运行：node scripts/gen-living-circle-fixtures.mjs
 */
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../src/mocks/fixtures/livingCircle')

/** 步行速度 m/min（15min → 1080m 半径口径） */
const WALK = 72 // m/min

/** 以米为单位沿方位角取点（简易等距方位投影，局部精度足够） */
function offsetKm([lng, lat], dLngM, dLatM) {
  const dLat = dLatM / 111320
  const dLng = dLngM / (111320 * Math.cos((lat * Math.PI) / 180))
  return [lng + dLng, lat + dLat]
}

/**
 * 生成圆形近似等时圈（5/10/15/20min）。步行半径 = minutes * WALK。
 * 半径加 ±3% 轻微形变，视觉上不呆板但仍诚实标注 circular_approx。
 */
function isoCircle(center, minutes, seg = 48) {
  const r = minutes * WALK
  const pts = []
  for (let i = 0; i < seg; i++) {
    const theta = (i / seg) * 2 * Math.PI
    const wob = 1 + 0.03 * Math.sin(3 * theta + minutes) // ±3% 轻形变
    const x = Math.cos(theta) * r * wob
    const y = Math.sin(theta) * r * wob
    pts.push(offsetKm(center, x, y))
  }
  pts.push(pts[0]) // 闭合
  // area_km2 ≈ π r² 修正（圆形近似）
  return { minutes, geojson: { type: 'Polygon', coordinates: [pts] }, area_km2: +(Math.PI * (r / 1000) ** 2).toFixed(3) }
}

/** 采样点（渔网式网格，400m 步长，半径 2400m）——fixture 阶段为圆形近似合成 */
function samplePoints(center, radius = 2400) {
  const points = []
  let idx = 0
  for (let x = -radius; x <= radius; x += 400) {
    for (let y = -radius; y <= radius; y += 400) {
      const [lng, lat] = offsetKm(center, x, y)
      const dist = Math.hypot(x, y)
      const minutes = dist / WALK
      points.push({
        idx: idx++,
        lng: +lng.toFixed(6),
        lat: +lat.toFixed(6),
        minutes: minutes <= 20 ? +minutes.toFixed(1) : null,
        reachable: minutes <= 20,
      })
    }
  }
  return points
}

/** 圆形盲区灰区（1km 判定圆，简化多边形） */
function blindPoly(center, radius = 1000) {
  const pts = []
  for (let i = 0; i < 40; i++) {
    const theta = (i / 40) * 2 * Math.PI
    const [lng, lat] = offsetKm(center, Math.cos(theta) * radius, Math.sin(theta) * radius)
    pts.push([+lng.toFixed(6), +lat.toFixed(6)])
  }
  pts.push(pts[0])
  return { type: 'Polygon', coordinates: [pts] }
}

/** 角度 → 中文方位 */
function bearing(a, b) {
  const [dx, dy] = a
  const ang = (Math.atan2(dy, dx) * 180) / Math.PI
  const dirs = ['正东', '东北', '正北', '西北', '正西', '西南', '正南', '东南']
  return dirs[Math.round((ang + 360) % 360 / 45) % 8]
}

/** 方向（相对中心点 dx,dy 米） */
function dir8(dx, dy) {
  return bearing([dx, dy], [0, 0])
}

/**
 * 依据 POI 集汇总类别统计。
 * poi 形状：{ category, label, name, dx, dy（相对中心点米）, minutes（步行耗时，圆形近似） }
 */
function summarize(center, pois) {
  const cats = new Map()
  for (const p of pois) {
    if (!cats.has(p.category)) {
      cats.set(p.category, {
        category: p.category,
        label: p.label,
        total: 0,
        in_circle: 0,
        coverage: 0,
        min_minutes: null,
        nearest_name: null,
      })
    }
    const s = cats.get(p.category)
    s.total += 1
    if (p.minutes <= 15) {
      s.in_circle += 1
      if (s.min_minutes === null || p.minutes < s.min_minutes) {
        s.min_minutes = p.minutes
        s.nearest_name = p.name
      }
    }
  }
  return Array.from(cats.values()).map((s) => ({
    ...s,
    coverage: +Math.min(1, s.in_circle / Math.max(2, Math.ceil(s.total * 0.8))).toFixed(2),
  }))
}

/** 盲区三要素（菜市场 market / 药店 pharmacy / 小学 primary，取 1km 内是否覆盖） */
function triads(pois, center) {
  const in1km = (p) => Math.hypot(p.dx, p.dy) <= 1000
  const pick = (type) => {
    const list = pois.filter((p) => p.type === type && in1km(p))
    if (!list.length) return { covered: false, nearest_name: null, nearest_minutes: null }
    const nearest = list.sort((a, b) => a.minutes - b.minutes)[0]
    return { covered: true, nearest_name: nearest.name, nearest_minutes: nearest.minutes }
  }
  return [
    { facility: '菜市场', ...pick('market') },
    { facility: '药店', ...pick('pharmacy') },
    { facility: '小学', ...pick('primary') },
  ]
}

/** 依据类别统计生成雷达/柱数据（0-100）＋三要素结论 */
function scoreBall(scores, stats, defs, center) {
  const dimName = { medical: '医疗', education: '教育', shopping: '购物', market: '菜市', elderly: '养老', finance: '金融', recreation: '文体', service: '政务' }
  const base = { medical: 78, education: 82, shopping: 80, market: 76, elderly: 55, finance: 70, recreation: 65, service: 72 }
  const present = new Set(stats.map((s) => s.category))
  const radar = []
  let sum = 0
  let n = 0
  for (const [cat, score] of Object.entries(base)) {
    const sc = present.has(cat) ? score : Math.round(score * 0.45)
    sum += sc
    n += 1
    radar.push({ dimension: dimName[cat] ?? cat, score: sc })
  }
  const total = Math.round(sum / n * scores.total / 100 + (scores.total * 0.2))
  const bars = stats.map((s) => ({ category: s.category, label: s.label, value: Math.min(100, Math.round(s.coverage * 100)) }))
  return { total, radar, bars, triads: triads(defs, center), note: scores.note }
}

function buildMeta(id, name, city, address, center, scores) {
  return { id, scene: { name, city, address, center, study_radius_m: 2500 }, scores }
}

const studies = [
  buildMeta(
    'kaili-laojie',
    '凯里老街',
    '贵州·凯里',
    '凯里市西门街道老街片区（大阁山脚下）',
    [107.9758, 26.5734],
    { total: 70, note: '欠发达样区：设施密度低，菜市场/药店/小学三要素 1km 覆盖存在缺口' },
  ),
  buildMeta(
    'beijing-jinsong',
    '北京劲松',
    '北京·朝阳',
    '朝阳区劲松街道（劲松地铁站周边）',
    [116.4637, 39.8832],
    { total: 93, note: '成熟城区样区：设施密度高，三要素齐备，仅东南边缘存在轻微盲区' },
  ),
]

/** 各社区真实方向 POI（dx,dy 相对中心点米，minutes 由圆形近似距离算出） */
const POI_DEFS = {
  'kaili-laojie': [
    // 菜市
    { category: 'market', label: '菜市场', type: 'market', name: '凯里老街菜市场', dx: 120, dy: -80 },
    { category: 'market', label: '菜市场', type: 'market', name: '大阁山菜市场', dx: -360, dy: 260 },
    { category: 'market', label: '菜市场', type: 'market', name: '东门口早市菜场', dx: 720, dy: 340 },
    // 药店
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '益民大药房（老街店）', dx: 60, dy: 140 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '凯里同济大药房', dx: -520, dy: -240 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '仁信大药房', dx: 640, dy: -120 },
    // 诊所/社区医院
    { category: 'medical', label: '医疗', type: 'clinic', name: '城东社区卫生服务中心', dx: -260, dy: -360 },
    { category: 'medical', label: '医疗', type: 'clinic', name: '老街社区卫生服务站', dx: 200, dy: 300 },
    { category: 'medical', label: '医疗', type: 'hospital', name: '黔东南州人民医院', dx: 1500, dy: 900 },
    // 教育（小学/幼儿园）
    { category: 'education', label: '教育', type: 'primary', name: '凯里市第八小学', dx: 480, dy: -320 },
    { category: 'education', label: '教育', type: 'primary', name: '凯里市第九小学', dx: 900, dy: -700 },
    { category: 'education', label: '教育', type: 'kindergarten', name: '老街幼儿园', dx: -140, dy: 200 },
    { category: 'education', label: '教育', type: 'kindergarten', name: '童心幼儿园', dx: 560, dy: 80 },
    // 购物
    { category: 'shopping', label: '购物', type: 'supermarket', name: '世纪华联超市（老街店）', dx: -80, dy: -60 },
    { category: 'shopping', label: '购物', type: 'supermarket', name: '惠民生鲜超市', dx: 480, dy: 420 },
    { category: 'shopping', label: '购物', type: 'convenience', name: '街边便民便利店', dx: 240, dy: -140 },
    // 养老
    { category: 'elderly', label: '养老', type: 'nursing', name: '夕阳红托养中心', dx: 1180, dy: 860 },
    // 金融
    { category: 'finance', label: '金融', type: 'bank', name: '贵州银行老街支行', dx: 140, dy: -240 },
    { category: 'finance', label: '金融', type: 'bank', name: '农商银行西门支行', dx: -420, dy: 140 },
    // 文体
    { category: 'recreation', label: '文体', type: 'park', name: '大阁山公园', dx: -600, dy: 540 },
    // 政务/服务
    { category: 'service', label: '政务', type: 'gov', name: '西门街道政务服务中心', dx: -320, dy: 80 },
    { category: 'service', label: '政务', type: 'post', name: '老街邮政所', dx: 180, dy: 20 },
    // 更远处设施（供"最近设施"叙事）
    { category: 'market', label: '菜市场', type: 'market', name: '洗马河农贸市场', dx: 1850, dy: 720 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '凯里中心大药房', dx: -1250, dy: 960 },
  ],
  'beijing-jinsong': [
    // 菜市
    { category: 'market', label: '菜市场', type: 'market', name: '劲松农贸市场', dx: 160, dy: -240 },
    { category: 'market', label: '菜市场', type: 'market', name: '农光里菜市场', dx: 620, dy: -150 },
    { category: 'market', label: '菜市场', type: 'market', name: '华西里菜市场', dx: -480, dy: 300 },
    // 药店
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '同仁堂大药房（劲松店）', dx: -40, dy: -380 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '金象大药房（劲松店）', dx: 420, dy: 60 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '百姓阳光大药房', dx: -620, dy: -220 },
    { category: 'medical', label: '医疗', type: 'pharmacy', name: '益丰大药房（华威店）', dx: 900, dy: -40 },
    // 社区医院/医院
    { category: 'medical', label: '医疗', type: 'clinic', name: '劲松社区卫生服务中心', dx: 220, dy: -140 },
    { category: 'medical', label: '医疗', type: 'clinic', name: '双井社区卫生服务中心', dx: -760, dy: 480 },
    { category: 'medical', label: '医疗', type: 'hospital', name: '垂杨柳医院', dx: 960, dy: 700 },
    // 教育
    { category: 'education', label: '教育', type: 'primary', name: '劲松第一小学', dx: -280, dy: -160 },
    { category: 'education', label: '教育', type: 'primary', name: '劲松第二小学', dx: 380, dy: 260 },
    { category: 'education', label: '教育', type: 'primary', name: '劲松第三小学', dx: 640, dy: -420 },
    { category: 'education', label: '教育', type: 'kindergarten', name: '劲松第一幼儿园', dx: -180, dy: 60 },
    { category: 'education', label: '教育', type: 'kindergarten', name: '汇佳幼儿园（劲松园）', dx: 520, dy: 120 },
    { category: 'education', label: '教育', type: 'kindergarten', name: '劲松第二幼儿园', dx: -560, dy: -40 },
    // 购物
    { category: 'shopping', label: '购物', type: 'supermarket', name: '京客隆超市（劲松店）', dx: -120, dy: -220 },
    { category: 'shopping', label: '购物', type: 'supermarket', name: '物美便利（劲松店）', dx: 260, dy: 160 },
    { category: 'shopping', label: '购物', type: 'mall', name: '富力广场（合生汇方向）', dx: 1180, dy: -560 },
    { category: 'shopping', label: '购物', type: 'convenience', name: '711便利店（劲松桥）', dx: -80, dy: 320 },
    // 养老
    { category: 'elderly', label: '养老', type: 'nursing', name: '劲松街道养老照料中心', dx: 320, dy: -360 },
    { category: 'elderly', label: '养老', type: 'nursing', name: '亲馨颐养院', dx: -760, dy: -80 },
    // 金融
    { category: 'finance', label: '金融', type: 'bank', name: '工商银行劲松支行', dx: 60, dy: -300 },
    { category: 'finance', label: '金融', type: 'bank', name: '建设银行劲松支行', dx: -260, dy: 180 },
    { category: 'finance', label: '金融', type: 'bank', name: '北京银行双井支行', dx: -700, dy: 560 },
    // 文体
    { category: 'recreation', label: '文体', type: 'park', name: '劲松公园', dx: 280, dy: 420 },
    { category: 'recreation', label: '文体', type: 'fitness', name: '劲松文体中心', dx: -480, dy: -320 },
    // 政务/服务
    { category: 'service', label: '政务', type: 'gov', name: '劲松街道政务服务中心', dx: -40, dy: -460 },
    { category: 'service', label: '政务', type: 'post', name: '劲松邮政支局', dx: 440, dy: -300 },
  ],
}

/** 各社区盲区点位（相对中心点米） */
const BLINDSPOTS = {
  'kaili-laojie': [
    { name: '东郊沿河片区', dx: 1250, dy: 40, missing: ['菜市场', '药店', '小学'] },
    { name: '南部近郊片区', dx: -180, dy: 1300, missing: ['菜市场', '药店', '小学'] },
    { name: '西南山脚片区', dx: -1160, dy: 940, missing: ['菜市场', '药店', '小学'] },
    { name: '北部新城片区', dx: 260, dy: -1180, missing: ['菜市场', '药店'] },
  ],
  'beijing-jinsong': [
    { name: '东南边缘片区', dx: 760, dy: 1020, missing: ['菜市场'] },
  ],
}

for (const study of studies) {
  const id = study.id
  const defs = (POI_DEFS[id] ?? []).map((p) => ({ ...p, minutes: +Math.round(Math.hypot(p.dx, p.dy) / WALK * 10) / 10 }))
  const iso = [5, 10, 15, 20].map((m) => isoCircle(study.scene.center, m))
  const points = samplePoints(study.scene.center)
  const stats = summarize(study.scene.center, defs)
  const blindspots = (BLINDSPOTS[id] ?? []).map((b, i) => {
    const center = offsetKm(study.scene.center, b.dx, b.dy).map((v) => +v.toFixed(6))
    // 最近各类设施（从 1km 外找最近）
    const nearest = ['market', 'pharmacy', 'primary'].map((t) => {
      const list = defs
        .filter((p) => p.type === t)
        .map((p) => ({
          facility: t,
          name: p.name,
          distance_m: Math.hypot(p.dx - b.dx, p.dy - b.dy),
          direction: dir8(p.dx - b.dx, p.dy - b.dy),
        }))
        .sort((a, c) => a.distance_m - c.distance_m)
      return list[0] ?? { facility: t, name: '未知', distance_m: 9999, direction: '—' }
    })
    return {
      id: `bs-${id}-${i + 1}`,
      center,
      radius_m: 1000,
      missing_facilities: b.missing,
      nearest,
      polygon: blindPoly(center),
    }
  })
  const report = {
    scene: study.scene,
    generated_at: new Date().toISOString(),
    data_origin: 'fixture_sample',
    isochrones: iso,
    sampling: { points, interpolation: 'circular_approx', is_scattered: false },
    poi: {
      categories: stats,
      total: defs.length,
      in_circle: defs.filter((p) => p.minutes <= 15).length,
    },
    blindspots,
    scores: scoreBall(study.scores, stats, defs, study.scene.center),
  }

  const file = resolve(OUT, id === 'kaili-laojie' ? 'kaili.json' : 'beijing-jinsong.json')
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(report, null, 2) + '\n')
  console.log('[ok]', file, '· POI', report.poi.total, '· 盲区', report.blindspots.length, '· 总分', report.scores.total)
}
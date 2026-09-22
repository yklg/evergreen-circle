/** N6 景点分布图 · 数据资产层：目的地手绘模板（湖形/路网）与名称归一。
 *
 * 分层约定（架构评审 P1）：模板是**数据**，按目的地 key 查表 + 默认回退；
 * 组件（VSpotSketch）只消费本模块，不得散落 per-destination 硬编码。
 * 路径坐标系与投影画布一致：viewBox 0 0 640 420。 */

export type SketchTemplate = {
  /** 归一化后的目的地 key（同族共用，如 大理/大理古城） */
  key: string
  /** 湖形/城区轮廓（闭合路径，米黄底上描淡色形） */
  blobPath: string
  /** 路网/廊道示意（开放路径集，只作氛围装饰） */
  roadPaths: string[]
  /** true = 无专属模板，退化为抽象示意底形（海报上必须标注「示意底形」） */
  schematic?: boolean
}

const ABSTRACT: SketchTemplate = {
  key: '',
  blobPath:
    'M470 70 C520 130 525 240 480 310 C450 355 405 358 392 312 C372 240 388 132 420 84 C437 58 456 52 470 70 Z',
  roadPaths: [
    'M60 300 C180 260 300 300 420 250',
    'M120 120 C240 160 360 120 560 170',
  ],
  schematic: true,
}

/** 已收录模板（首轮仅大理；新增目的地 = 在此加一条数据，零组件改动）。 */
export const SPOT_SKETCH_TEMPLATES: Record<string, SketchTemplate> = {
  大理: {
    key: '大理',
    blobPath:
      'M468 58 C512 118 522 226 484 302 C458 352 418 360 402 318 C380 254 392 138 422 80 C436 52 454 46 468 58 Z',
    roadPaths: [
      'M96 322 C206 296 318 322 430 282',
      'M120 108 C236 148 352 112 520 158',
    ],
  },
}

/** 模板 key 名称归一（评审④）：去空白与常见行政/景区后缀，令同族地名命中同一模板。 */
export function normalizeTemplateKey(dest: unknown): string {
  let s = String(dest ?? '').trim()
  for (const suffix of ['白族自治州', '族自治州', '古城', '景区', '旅游区', '市', '县', '区', '州']) {
    if (s.length > suffix.length + 1 && s.endsWith(suffix)) {
      s = s.slice(0, -suffix.length)
      break
    }
  }
  return s.replace(/\s+/g, '')
}

export function matchSketchTemplate(dest: unknown): SketchTemplate {
  const key = normalizeTemplateKey(dest)
  const hit = SPOT_SKETCH_TEMPLATES[key]
  if (hit) return hit
  return { ...ABSTRACT, key: key || ABSTRACT.key }
}

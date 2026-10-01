// @vitest-environment jsdom
/**
 * 降级画布的**盲区可见性覆盖**契约（登记缺陷用，当前为严格预期失败）。
 *
 * ## 它要钉住的那句承诺
 *
 * 体检单与表列 `blindspot_count` 按 `report.blindspots.length` 计 N 处盲区，
 * 而 `LcMap` 的 live 分支把这些盲区的点集喂进了 `fitPts`（`LcMap.tsx:730-735`）
 * ⇒ 真地图会自动收视野、N 处全看得见。
 * 降级画布用的是**写死的** `LC_CANVAS.R = 2500`（`lib/livingCircle.ts:21`，与报告自己的
 * `study_radius_m` 无关）⇒ 中心落在 2500m 之外的盲区，点位与多边形全被 viewBox 裁掉。
 *
 * ⇒ 同一份报告，正文写 3 处盲区，降级画布只容得下 2 处（越界的那处点位与多边形全在框外）。
 * 这不是"参照圈被裁一半"那种观感问题，是**图上数字与正文数字对不上**。
 *
 * ## 暴露面（按逐轴判据实测，不是径向距离）
 *
 * 画布是 860×620 的**矩形**框，所以"看不看得见"必须逐轴判 `0<=px<=W && 0<=py<=H`；
 * 拿"离中心 > R"当判据会把斜向 45° 的格误判成越界（两轴各只占 0.707 倍）。
 * 全库去重后：14 个场景、22 处盲区，逐轴越界 **1 处** = `bs-凯里老街-2`
 * （px=(894,273)，而 W=860），出现在 `lc-a2a284de` 等 3 份同内容报告里。
 *
 * ## 为什么先让它红
 *
 * 本仓已有同类纪律：`lifeCircleForensicUi.test.tsx:270` 对**证据盘**断言"点必须落在画布内"。
 * 但**盲区**这一层一条都没有 —— 所以这个缺口能一直活着。本文件补的就是那一条。
 * 先以正向断言跑出真实红（读数见下），再转 `it.fails` 登记：**将来把画布框架修好后
 * 这条会转绿，而 `it.fails` 在转绿时主动报错**，逼着摘标 —— 等价后端 `xfail(strict=True)`。
 *
 * ## 数据来源（不连库）
 *
 * 偏移取自真实报告 `lc-a2a284de`（凯里老街）实测：三处盲区离中心
 * `(-381,-928)` / `(2700,300)` / `(2059,2157)` 米，`study_radius_m=2500`。
 * 载荷构造走生产出口 `lcFromMeters`，不在测试里另写一份逆投影。
 */
import { describe, expect, it } from 'vitest'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { LC_CANVAS, lcFromMeters, lcToPx } from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

const BASE = kaili as unknown as LivingCircleReport
const CENTER = BASE.scene.center

/** 真实报告里那三处盲区相对样区中心的米偏移（见文件头）。 */
const MEASURED_OFFSETS_M: Array<[number, number]> = [
  [-381, -928],
  [2700, 300],
  [2059, 2157],
]

function blindAt(i: number, mx: number, my: number) {
  const c = lcFromMeters(CENTER, mx, my)
  return {
    id: `bs-cov-${i}`,
    center: c,
    radius_m: 800,
    missing_facilities: ['primary'],
    nearest: [{ facility: 'primary', name: '某小学', distance_m: 1155, direction: '东北' }],
    polygon: {
      type: 'Polygon',
      coordinates: [[lcFromMeters(c, -150, -150), lcFromMeters(c, 150, -150), lcFromMeters(c, 150, 150), lcFromMeters(c, -150, 150)]],
    },
    severity: 'light',
  } as unknown as LivingCircleReport['blindspots'][number]
}

const REPORT: LivingCircleReport = {
  ...BASE,
  blindspots: MEASURED_OFFSETS_M.map(([mx, my], i) => blindAt(i, mx, my)),
}

/** 盲区中心是否落在降级画布的可视框内。 */
function insideCanvas(c: [number, number]): boolean {
  const [px, py] = lcToPx(CENTER, c[0], c[1])
  return px >= 0 && px <= LC_CANVAS.W && py >= 0 && py <= LC_CANVAS.H
}

describe('降级画布必须容得下正文声明的每一处盲区（缺陷登记）', () => {
  it('夹具前提自报：三处偏移按生产投影算出的 px 与越界情况', () => {
    const rows = REPORT.blindspots.map((b) => {
      const [px, py] = lcToPx(CENTER, b.center[0], b.center[1])
      return { px: Math.round(px), py: Math.round(py), inside: insideCanvas(b.center) }
    })
    // 复算自报规模：画布 860×620，R=2500m ⇒ 每米 x=0.172px、y=0.124px
    expect(LC_CANVAS).toEqual({ R: 2500, W: 860, H: 620 })
    expect(rows).toEqual([
      { px: 364, py: 425, inside: true },
      { px: 894, py: 273, inside: false },
      { px: 784, py: 43, inside: true },
    ])
  })

  /**
   * 严格预期失败（等价后端 `xfail(strict=True)`）。
   *
   * 登记时实测的失败种类（**先以正向断言跑红、确认不是导入崩溃，才转成本写法**）：
   *   AssertionError: 正文计 3 处，降级画布只容得下 2 处: expected 2 to be 3
   *
   * 将来把降级画布的可视框改成按报告内容/study_radius 取（或把那处越界盲区归位）之后，
   * 这条会转绿 —— 而 `it.fails` 在转绿时**主动报错**，逼着摘掉标记。
   */
  it.fails('盲区处数 == 降级画布内可见处数（正文写 3 处，图上就该看得见 3 处）', () => {
    const visible = REPORT.blindspots.filter((b) => insideCanvas(b.center))
    expect(visible.length, `正文计 ${REPORT.blindspots.length} 处，降级画布只容得下 ${visible.length} 处`).toBe(
      REPORT.blindspots.length,
    )
  })
})

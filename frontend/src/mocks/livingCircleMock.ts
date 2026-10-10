/**
 * 常青圈 · 生活圈体检 mock 数据层（F0c）。
 *
 * 数据模式已提升为运行时开关（store/dataModeStore，侧边栏「数据模式」tab）——
 * 本文件不再导出 USE_MOCK / LC_DATA_MODE 常量（v3，P1-1：任务 data_mode 由模式开关派生）。
 * fixture 只读不写，M5 阶段由真实百度 API 快照替换（保持同契约）。
 */
import type { LivingCircleReport, LngLat } from '../types'
import kailiEv2Json from './fixtures/livingCircle/kaili-ev2.json'
import kailiJson from './fixtures/livingCircle/kaili.json'
import jinsongJson from './fixtures/livingCircle/beijing-jinsong.json'

/** 内置样例社区（工作台示例卡 + 轮询入口共用同一数据源，保证一致） */
export interface SampleCommunity {
  id: string
  title: string
  city: string
  blurb: string
  report: LivingCircleReport
}

export const SAMPLE_COMMUNITIES: SampleCommunity[] = [
  {
    // 排在 [0] 是有意的：`getLifeCircleMock` 对未知 id 回退首个样例，首页图标也按
    // `i === 0` 取 MapPin ⇒ 第 0 位就是演示档默认打开的那份。选它是因为只有这一份带
    // `caliber.cells_ledger`（逐格台账 + 1 处盲区），另两份是台账上线前的冻结件。
    id: 'kaili-ev2',
    title: '凯里老街 · 逐格台账口径',
    city: '贵州·凯里',
    blurb: '09-30 那一批 ev-2 真跑件（#87 词表之前）· 1 处服务盲区 · 逐格台账判盲 8 格',
    report: kailiEv2Json as unknown as LivingCircleReport,
  },
  {
    id: 'kaili',
    title: '凯里老街',
    city: '贵州·凯里',
    blurb: '欠发达样区 · 教育门槛项未计满（33%）；72 格只判过 9 格 ⇒ 盲区 0 处不等于没有盲区',
    report: kailiJson as unknown as LivingCircleReport,
  },
  {
    id: 'beijing-jinsong',
    title: '北京劲松',
    city: '北京·朝阳',
    blurb: '成熟城区样区 · 三要素齐备；99 格只判过 21 格 ⇒ 盲区 0 处不等于没有盲区',
    report: jinsongJson as unknown as LivingCircleReport,
  },
]

/**
 * 演示态默认对比的一对样区：名册首项 + 第一个**不同城**的样区。
 *
 * 为什么不写死"取前两份"：名册允许同一城市并存多份冻结件（台账上线前那份 + ev-2 这份），
 * 按位置取会把对比页配成同城一对，另一座城市直接从那一页消失。
 * 出口只这一处 —— 页面与它的测试都调它，免得两边各写一遍挑法然后互相漂。
 */
export function demoCompareSamples(): [SampleCommunity, SampleCommunity] {
  const first = SAMPLE_COMMUNITIES[0]
  const other = SAMPLE_COMMUNITIES.find((c) => c.city !== first.city) ?? SAMPLE_COMMUNITIES[1]
  return [first, other]
}

/** 按样例 id 取体检报告（fixture 态即静态返回；真实态走后端，见 M3） */
export function getLifeCircleMock(sceneId: string | null): LivingCircleReport | null {
  const hit = SAMPLE_COMMUNITIES.find((c) => c.id === sceneId)
  return hit ? hit.report : (SAMPLE_COMMUNITIES[0]?.report ?? null)
}

/** 按中心点匹配最近的样例报告（自定义中心点在 F 阶段复用最近样例，M 阶段替换为在线计算） */
export function matchNearestMock(center: LngLat): LivingCircleReport {
  let best = SAMPLE_COMMUNITIES[0].report
  let bestD = Infinity
  for (const c of SAMPLE_COMMUNITIES) {
    const [a0, a1] = c.report.scene.center
    const d = (a0 - center[0]) ** 2 + (a1 - center[1]) ** 2
    if (d < bestD) {
      bestD = d
      best = c.report
    }
  }
  return best
}
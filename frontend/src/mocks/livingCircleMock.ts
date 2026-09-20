/**
 * 常青圈 · 生活圈体检 mock 数据层（F0c）。
 *
 * 数据模式已提升为运行时开关（store/dataModeStore，侧边栏「数据模式」tab）——
 * 本文件不再导出 USE_MOCK / LC_DATA_MODE 常量（v3，P1-1：任务 data_mode 由模式开关派生）。
 * fixture 只读不写，M5 阶段由真实百度 API 快照替换（保持同契约）。
 */
import type { LivingCircleReport, LngLat } from '../types'
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
    id: 'kaili',
    title: '凯里老街',
    city: '贵州·凯里',
    blurb: '欠发达样区 · 核心圈设施可及，外围 1km 存在 4 处服务盲区',
    report: kailiJson as unknown as LivingCircleReport,
  },
  {
    id: 'beijing-jinsong',
    title: '北京劲松',
    city: '北京·朝阳',
    blurb: '成熟城区样区 · 三要素齐备，仅东南边缘 1 处轻微盲区',
    report: jinsongJson as unknown as LivingCircleReport,
  },
]

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
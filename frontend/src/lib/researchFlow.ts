/**
 * 目的地调研统一发起入口（镜像 lifeCircleFlow 形态）。
 *
 * 首页与工作台各处「建任务 + registry 落 running」的重复逻辑收敛到本模块，
 * 保证两种入口启动后的进度/终态行为完全一致，防止再次分叉。
 *
 * 类型契约：入参一律用权威 type（guide/assessment，来自 taskDomains）；
 * registry 同时写 purpose（demoPurpose 方言）以喂演示回放器——真实态后端
 * 按 body.type 落库，purpose 不再作为建任务依据。
 */
import { createTask } from './api'
import { useTaskRegistry } from '../store/taskRegistry'
import { resolveTypeOr, demoPurposeOf, type DomainType } from './taskDomains'

/** 空输入时的类型化兜底句（用户原话非空则原样透传，不做跨域包装）。 */
const FALLBACK_QUERY: Record<DomainType, string> = {
  guide: '帮我做一份目的地游玩攻略',
  assessment: '帮我做一份目的地调研评估',
  living_circle: '帮我做一次 15 分钟生活圈体检',
}

/** 组装提交 query：原话优先（含地名/天数/同行人等真实需求），空值按类型兜底。 */
export function buildResearchQuery(input: string, type: string = 'guide'): string {
  const text = input.trim()
  if (text) return text
  return FALLBACK_QUERY[resolveTypeOr(type, 'guide')]
}

/**
 * 建任务 + registry 落 running。成功后返回 { taskId, kind }，
 * 调用方负责按 submitLanding(type, dataMode) 导航（真实→clarify / 演示→workspace）。
 */
export async function launchResearch(
  query: string,
  depth = 'deep',
  type: string = 'guide',
): Promise<{ taskId: string; kind: string }> {
  const domain = resolveTypeOr(type, 'guide')
  const { taskId, kind = 'research' } = await createTask(query, depth, undefined, domain)
  useTaskRegistry.getState().upsert({
    taskId,
    kind,
    // 演示回放桥：replayResearchStream 历史上按 purpose(guide/assess) 取话术
    purpose: demoPurposeOf(domain),
    query,
    status: 'running',
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  })
  return { taskId, kind }
}

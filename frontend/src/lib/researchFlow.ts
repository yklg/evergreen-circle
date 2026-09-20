/**
 * 目的地调研统一发起入口（镜像 lifeCircleFlow 形态）。
 *
 * 首页与工作台各处「建任务 + registry 落 running」的重复逻辑收敛到本模块，
 * 保证两种入口启动后的进度/终态行为完全一致，防止再次分叉。
 */
import { createTask } from './api'
import { useTaskRegistry } from '../store/taskRegistry'

/** 目的地调研 query 模板唯一收敛（首页 / 工作台共用，防措辞分叉）。 */
export function buildResearchQuery(place: string, purpose = ''): string {
  const out = purpose === 'guide' ? '攻略' : '评估'
  return `以15分钟便民生活圈视角调研「${place}」，产出${out}报告`
}

/**
 * 建任务 + registry 落 running。成功后返回 { taskId, kind }，
 * 调用方负责 `navigate('/workspace/:taskId')` 触发工作台 SSE 真实推进。
 * query 由调用方经 buildResearchQuery 组装；purpose 决定 kind 归一（见 viewRegistry.kindForPurpose）。
 */
export async function launchResearch(
  query: string,
  depth = 'deep',
  purpose = '',
): Promise<{ taskId: string; kind: string }> {
  const { taskId, kind = 'research' } = await createTask(query, depth, undefined, purpose)
  useTaskRegistry.getState().upsert({
    taskId,
    kind,
    purpose,
    query,
    status: 'running',
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  })
  return { taskId, kind }
}
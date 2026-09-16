/** 模型矩阵解析纯函数（与 React/组件无关，便于单测）。
   被 SettingsPage 的 candidateModels / modelMismatch / recommendedModels / syncAndSave / applyProviderPreset 复用。 */

import type { LLMProviderPreset } from './llmProviders'

/** 把厂商推荐 models 数组映射到模型矩阵 4 字段（见「切厂商模型联动修复计划」§1.1）：
    - 默认/核心章（重活）→ M[0]（厂商主推/最强）
    - 辅助章 → M[1]（第二档）
    - 杂务快速 → M[末]（末尾通常是 fast/flash/air 轻量档）
    models 为空（如火山方舟按 ep-xxx 接入点调用）→ 清空，交由用户手填。 */
export function presetModels(p: Pick<LLMProviderPreset, 'models'>): Record<string, string> {
  const M = p.models
  if (M.length === 0) {
    return { llm_model: '', llm_model_core: '', llm_model_aux: '', llm_model_fast: '' }
  }
  if (M.length === 1) {
    return { llm_model: M[0], llm_model_core: M[0], llm_model_aux: M[0], llm_model_fast: M[0] }
  }
  return {
    llm_model: M[0],
    llm_model_core: M[0],
    llm_model_aux: M[1],
    llm_model_fast: M[M.length - 1],
  }
}

/** 数组去重（保序） */
export function dedupe(arr: string[]): string[] {
  return Array.from(new Set(arr))
}

/** 非对话类模型（TTS / 语音 / 嵌入 / 图像 / 审核 / 实时 等），不应进对话候选集。 */
const NONCHAT =
  /tts|whisper|dall[-_]?e|text-embedding|embed[-_]|moderation|realtime|imagen|speech|audio[-_]|transcribe|rerank/i

/** 过滤非对话类模型，仅保留对话/chat 模型（大小写不敏感）。 */
export function chatOnly(list: string[]): string[] {
  return list.filter((m) => !NONCHAT.test(m))
}

/** 把 live 模型列表归一为「对话候选集」：剔除非对话类 + 去重。
   安全阀：若过滤+去重后为空（live 全是 tts/embedding 之类），回退未过滤去重，
   绝不返回空（避免候选集致死）。 */
export function normalizeLive(list: string[]): string[] {
  const chat = dedupe(chatOnly(list))
  return chat.length > 0 ? chat : dedupe(list)
}

/** 候选模型集（纯函数）：live 权威、curated 兜底、**绝不并集**。
   - live 非空 → normalizeLive(live)（权威接管，结构性消除「curated 毒值」类 bug）
   - live 空   → 回退 curated（离线兜底）
   契约 CG1：candidatesFor 内部必须调用 normalizeLive，不得就地重写过滤逻辑。 */
export function candidatesFor(
  p: Pick<LLMProviderPreset, 'models'>,
  live: string[],
): string[] {
  if (live.length > 0) return normalizeLive(live)
  return p.models
}

/** 把 live 模型列表规整为「角色有序」推荐集：剔除多模态(vision)实验模型，
   强模型(pro/max/plus/大上下文)前置作 default/core，轻量(flash/lite/air/mini/turbo)后置作 fast。
   与 curated `models` 的语义一致，但来源是实时列表，避免依赖手工维护的 curated。 */
export function reorderForRoles(list: string[]): string[] {
  const filtered = list.filter((m) => !/vision/i.test(m))
  const strong = /pro|max|plus|128k|32k|large|mini-\d|larget/i
  const weak = /flash|lite|air|mini|turbo|8k|light/i
  const head = filtered.filter((m) => strong.test(m))
  const tail = filtered.filter((m) => weak.test(m) && !strong.test(m))
  const mid = filtered.filter((m) => !strong.test(m) && !weak.test(m))
  return [...head, ...mid, ...tail]
}

/** 同步目标推荐集（纯函数，便于单测）——mixed-guard：
   live 优先且只取「curated ∩ live」，绝不把 curated 毒值（live 不含的 ID）泄漏进推荐。

   分支（与测试 R1–R8 一一对应）：
   - 草稿厂商 ≠ 已保存厂商（R4）→ 不读 live，返回 curated（防草稿态跨厂商污染）
   - live 为空（R5）→ 返回 curated（离线兜底）
   - curated 全存活（R1）→ 保序沿用 curated（其角色意图已验证有效，不扰动 Moonshot 等）
   - curated 部分存活（R2/R8）→ 保序保留存活者 + reorderForRoles(live) 补位（不含毒值）
   - curated 全毒（R3/R7）→ reorderForRoles(live) 兜底；
     若 live 全为非对话类（安全阀触发）也据未过滤 live 重算，绝不返回空

   契约 CG2：最终 valid 必来自 curated ∩ live（或 live 安全阀），无 curated-only 泄漏。 */
export function resolveRecommended(
  p: Pick<LLMProviderPreset, 'id' | 'models'>,
  savedId: string | undefined,
  liveModels: string[],
): string[] {
  // R4：草稿 ≠ 已保存 → 不并入 live
  if (p.id !== savedId) return p.models
  // R5：live 空 → curated 兜底
  if (liveModels.length === 0) return p.models

  // live 权威归一（剔非对话类 + 去重；全非对话类时走安全阀，不返回空）
  const liveSet = new Set(normalizeLive(liveModels))
  // valid = curated ∩ live（CG2：唯一允许的 curated 来源）
  const valid = p.models.filter((m) => liveSet.has(m))

  // R1：curated 全存活（≥2）→ 保序沿用 curated
  if (valid.length === p.models.length && p.models.length >= 2) return p.models
  // R2 / R8：部分存活（含 1）→ 保序保留存活者 + 补位（补位空则仅存活者，不抛不补 undefined）
  if (valid.length >= 1) {
    const rest = reorderForRoles(liveModels).filter((m) => !valid.includes(m))
    return [...valid, ...rest]
  }
  // R3 / R7：curated 全毒 → reorderForRoles(live) 兜底（安全阀下据未过滤 live 重算）
  const r = reorderForRoles(liveModels)
  return r.length > 0 ? r : p.models
}

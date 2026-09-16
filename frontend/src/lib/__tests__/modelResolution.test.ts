import { describe, it, expect } from 'vitest'
import {
  reorderForRoles,
  presetModels,
  dedupe,
  chatOnly,
  normalizeLive,
  candidatesFor,
  resolveRecommended,
} from '../modelResolution'
import type { LLMProviderPreset } from '../llmProviders'

/* 修正后的真实 curated（C1：deepseek-v4-flash → deepseek-flash 官方真名）。
   后续 R1/R4/R5 用此 fixture 验证「真实场景」；R2/R3 用内联毒值验证过滤。 */
const deepseek: Pick<LLMProviderPreset, 'id' | 'models'> = {
  id: 'deepseek',
  models: ['deepseek-v4-pro', 'deepseek-flash'],
}

describe('reorderForRoles (S3a)', () => {
  it('T1.1 DeepSeek live 原始顺序：剔除 vision + pro 前置', () => {
    expect(
      reorderForRoles([
        'deepseek-v4-flash',
        'deepseek-v4-pro',
        'deepseek-v4-flash-vision-exp',
      ]),
    ).toEqual(['deepseek-v4-pro', 'deepseek-v4-flash'])
  })

  it('T1.2 已有序时保持稳定', () => {
    expect(reorderForRoles(['deepseek-v4-pro', 'deepseek-flash'])).toEqual([
      'deepseek-v4-pro',
      'deepseek-flash',
    ])
  })

  it('T1.3 全为多模态 → 空', () => {
    expect(reorderForRoles(['xxx-vision-exp'])).toEqual([])
  })

  it('T1.4 非 DeepSeek 命名（Moonshot）：strong 前置', () => {
    expect(
      reorderForRoles([
        'kimi-latest',
        'moonshot-v1-128k',
        'moonshot-v1-32k',
        'moonshot-v1-8k',
      ]),
    ).toEqual(['moonshot-v1-128k', 'moonshot-v1-32k', 'kimi-latest', 'moonshot-v1-8k'])
  })

  it('T1.5 空输入 → 空', () => {
    expect(reorderForRoles([])).toEqual([])
  })
})

describe('presetModels (既有映射，S3 复用)', () => {
  it('T2.1 0 模型（火山）→ 全空', () => {
    expect(presetModels({ models: [] })).toEqual({
      llm_model: '',
      llm_model_core: '',
      llm_model_aux: '',
      llm_model_fast: '',
    })
  })

  it('T2.2 1 模型 → 四字段全同', () => {
    expect(presetModels({ models: ['m1'] })).toEqual({
      llm_model: 'm1',
      llm_model_core: 'm1',
      llm_model_aux: 'm1',
      llm_model_fast: 'm1',
    })
  })

  it('T2.3 ≥2 模型：core=M[0] / aux=M[1] / fast=M[末]', () => {
    expect(presetModels({ models: ['a', 'b', 'c', 'd', 'e'] })).toEqual({
      llm_model: 'a',
      llm_model_core: 'a',
      llm_model_aux: 'b',
      llm_model_fast: 'e',
    })
  })
})

describe('dedupe', () => {
  it('保序去重', () => {
    expect(dedupe(['a', 'b', 'a', 'c', 'b'])).toEqual(['a', 'b', 'c'])
  })
})

describe('chatOnly / normalizeLive (N1–N5)', () => {
  it('N1 NONCHAT 大小写不敏感：Whisper-1/TTS-1/DALL-E-3 全剔除', () => {
    expect(chatOnly(['Whisper-1', 'TTS-1', 'DALL-E-3'])).toEqual([])
  })

  it('N2 chat 模型保留：gpt-4o/claude-3.5/qwen-long/kimi-latest', () => {
    expect(
      chatOnly(['gpt-4o', 'claude-3.5-sonnet', 'qwen-long', 'kimi-latest']),
    ).toEqual(['gpt-4o', 'claude-3.5-sonnet', 'qwen-long', 'kimi-latest'])
  })

  it('N3 空入空出', () => {
    expect(chatOnly([])).toEqual([])
    expect(normalizeLive([])).toEqual([])
  })

  it('N4 去重 + 过滤叠加：gpt-4o/tts-1/gpt-4o → gpt-4o', () => {
    expect(normalizeLive(['gpt-4o', 'tts-1', 'gpt-4o'])).toEqual(['gpt-4o'])
  })

  it('N5 安全阀：live 全为非对话类 → 回退未过滤去重，不返回空', () => {
    expect(normalizeLive(['tts-1', 'whisper-1'])).toEqual(['tts-1', 'whisper-1'])
  })
})

describe('candidatesFor (C1–C4 · 权威链路不变量)', () => {
  it('C1 live 非空 → normalizeLive 权威接管（剔除 tts）', () => {
    expect(candidatesFor({ models: ['a', 'b'] }, ['gpt-4o', 'tts-1'])).toEqual(['gpt-4o'])
  })

  it('C2 live 空 → 回退 curated', () => {
    expect(candidatesFor({ models: ['a', 'b'] }, [])).toEqual(['a', 'b'])
  })

  it('C3 不并集：curated 含毒 + live 无毒 → 结果无 Poison', () => {
    // 契约 CG1/CG2：绝不把 curated 毒值泄漏进候选
    expect(
      candidatesFor(
        { models: ['deepseek-v4-pro', 'deepseek-v4-flash'] },
        ['deepseek-v4-pro', 'deepseek-flash'],
      ),
    ).toEqual(['deepseek-v4-pro', 'deepseek-flash'])
  })

  it('C4 live 全非对话类 → 安全阀（同 N5），不致死', () => {
    expect(candidatesFor({ models: ['a'] }, ['tts-1', 'whisper-1'])).toEqual([
      'tts-1',
      'whisper-1',
    ])
  })
})

describe('resolveRecommended (R1–R8 · mixed-guard)', () => {
  it('R1 curated 全存活（真名）→ 保序沿用 curated', () => {
    expect(
      resolveRecommended(deepseek, 'deepseek', [
        'deepseek-v4-pro',
        'deepseek-flash',
        'deepseek-v4-flash-vision-exp',
      ]),
    ).toEqual(['deepseek-v4-pro', 'deepseek-flash'])
  })

  it('R2 curated 部分存活（含毒 v4-flash）→ 补位且无 Poison', () => {
    expect(
      resolveRecommended(
        { id: 'deepseek', models: ['deepseek-v4-pro', 'deepseek-v4-flash'] },
        'deepseek',
        ['deepseek-v4-pro', 'deepseek-flash'],
      ),
    ).toEqual(['deepseek-v4-pro', 'deepseek-flash'])
  })

  it('R3 curated 全毒 → 回退 reorderForRoles(live)', () => {
    expect(
      resolveRecommended(
        { id: 'deepseek', models: ['deepseek-chat', 'deepseek-reasoner'] },
        'deepseek',
        ['deepseek-v4-pro', 'deepseek-flash'],
      ),
    ).toEqual(['deepseek-v4-pro', 'deepseek-flash'])
  })

  it('R4 草稿≠已保存 → 不并入 live，返回 curated', () => {
    expect(
      resolveRecommended(deepseek, 'moonshot', ['deepseek-v4-pro', 'deepseek-flash']),
    ).toEqual(['deepseek-v4-pro', 'deepseek-flash'])
  })

  it('R5 live 为空 → 返回 curated', () => {
    expect(resolveRecommended(deepseek, 'deepseek', [])).toEqual([
      'deepseek-v4-pro',
      'deepseek-flash',
    ])
  })

  it('R6 Moonshot 全存活 → 保序默认仍 kimi-latest（不退化）', () => {
    expect(
      resolveRecommended(
        {
          id: 'moonshot',
          models: ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
        },
        'moonshot',
        ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
      ),
    ).toEqual(['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'])
  })

  it('R7 live 全非对话类 → 安全阀后重算 valid，不抛不返回空', () => {
    expect(
      resolveRecommended(deepseek, 'deepseek', ['tts-1', 'whisper-1']),
    ).toEqual(['tts-1', 'whisper-1'])
  })

  it('R8 valid==1 且 reorderForRoles(live) 空 → [valid[0]]，不补 undefined', () => {
    expect(
      resolveRecommended(
        { id: 'deepseek', models: ['xxx-vision-exp'] },
        'deepseek',
        ['xxx-vision-exp'],
      ),
    ).toEqual(['xxx-vision-exp'])
  })
})

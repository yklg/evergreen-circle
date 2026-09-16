// 依赖无关验证：用 `node --experimental-strip-types` 直接跑（无需 vitest）。
// 仅验证 modelResolution.ts 的纯函数逻辑（对应 T1–T3 + N1–N5 + C1–C4 + R1–R8）。
import {
  reorderForRoles,
  presetModels,
  dedupe,
  chatOnly,
  normalizeLive,
  candidatesFor,
  resolveRecommended,
} from '../src/lib/modelResolution.ts'

let pass = 0
let fail = 0
function eq(actual: unknown, expected: unknown, name: string) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  if (a === e) {
    pass++
    console.log(`  ✓ ${name}`)
  } else {
    fail++
    console.error(`  ✗ ${name}\n      expected ${e}\n      actual   ${a}`)
  }
}

const deepseek = { id: 'deepseek', models: ['deepseek-v4-pro', 'deepseek-flash'] }

console.log('reorderForRoles (T1)')
eq(
  reorderForRoles(['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp']),
  ['deepseek-v4-pro', 'deepseek-v4-flash'],
  'T1.1 DeepSeek live → 剔 vision + pro 前置',
)
eq(reorderForRoles(['deepseek-v4-pro', 'deepseek-flash']), ['deepseek-v4-pro', 'deepseek-flash'], 'T1.2 已有序稳定')
eq(reorderForRoles(['xxx-vision-exp']), [], 'T1.3 全多模态 → 空')
eq(
  reorderForRoles(['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k']),
  ['moonshot-v1-128k', 'moonshot-v1-32k', 'kimi-latest', 'moonshot-v1-8k'],
  'T1.4 Moonshot 命名 → strong 前置',
)
eq(reorderForRoles([]), [], 'T1.5 空 → 空')

console.log('presetModels (T2)')
eq(
  presetModels({ models: [] }),
  { llm_model: '', llm_model_core: '', llm_model_aux: '', llm_model_fast: '' },
  'T2.1 0 模型 → 全空',
)
eq(
  presetModels({ models: ['m1'] }),
  { llm_model: 'm1', llm_model_core: 'm1', llm_model_aux: 'm1', llm_model_fast: 'm1' },
  'T2.2 1 模型 → 全同',
)
eq(
  presetModels({ models: ['a', 'b', 'c', 'd', 'e'] }),
  { llm_model: 'a', llm_model_core: 'a', llm_model_aux: 'b', llm_model_fast: 'e' },
  'T2.3 ≥2 → core=M[0]/aux=M[1]/fast=M[末]',
)

console.log('dedupe')
eq(dedupe(['a', 'b', 'a', 'c', 'b']), ['a', 'b', 'c'], '保序去重')

console.log('chatOnly / normalizeLive (N1–N5)')
eq(chatOnly(['Whisper-1', 'TTS-1', 'DALL-E-3']), [], 'N1 NONCHAT 大小写不敏感 → 全剔除')
eq(
  chatOnly(['gpt-4o', 'claude-3.5-sonnet', 'qwen-long', 'kimi-latest']),
  ['gpt-4o', 'claude-3.5-sonnet', 'qwen-long', 'kimi-latest'],
  'N2 chat 保留',
)
eq(normalizeLive([]), [], 'N3 空 → 空')
eq(normalizeLive(['gpt-4o', 'tts-1', 'gpt-4o']), ['gpt-4o'], 'N4 去重+过滤叠加')
eq(normalizeLive(['tts-1', 'whisper-1']), ['tts-1', 'whisper-1'], 'N5 安全阀 → 未过滤去重')

console.log('candidatesFor (C1–C4)')
eq(candidatesFor({ models: ['a', 'b'] }, ['gpt-4o', 'tts-1']), ['gpt-4o'], 'C1 live → normalizeLive 接管')
eq(candidatesFor({ models: ['a', 'b'] }, []), ['a', 'b'], 'C2 live 空 → curated')
eq(
  candidatesFor({ models: ['deepseek-v4-pro', 'deepseek-v4-flash'] }, ['deepseek-v4-pro', 'deepseek-flash']),
  ['deepseek-v4-pro', 'deepseek-flash'],
  'C3 不并集 → 无毒值',
)
eq(candidatesFor({ models: ['a'] }, ['tts-1', 'whisper-1']), ['tts-1', 'whisper-1'], 'C4 live 全非对话 → 安全阀')

console.log('resolveRecommended (R1–R8)')
eq(
  resolveRecommended(deepseek, 'deepseek', ['deepseek-v4-pro', 'deepseek-flash', 'deepseek-v4-flash-vision-exp']),
  ['deepseek-v4-pro', 'deepseek-flash'],
  'R1 curated 全存活 → 保序',
)
eq(
  resolveRecommended(
    { id: 'deepseek', models: ['deepseek-v4-pro', 'deepseek-v4-flash'] },
    'deepseek',
    ['deepseek-v4-pro', 'deepseek-flash'],
  ),
  ['deepseek-v4-pro', 'deepseek-flash'],
  'R2 部分存活 → 补位无毒',
)
eq(
  resolveRecommended(
    { id: 'deepseek', models: ['deepseek-chat', 'deepseek-reasoner'] },
    'deepseek',
    ['deepseek-v4-pro', 'deepseek-flash'],
  ),
  ['deepseek-v4-pro', 'deepseek-flash'],
  'R3 全毒 → reorderForRoles',
)
eq(
  resolveRecommended(deepseek, 'moonshot', ['deepseek-v4-pro', 'deepseek-flash']),
  ['deepseek-v4-pro', 'deepseek-flash'],
  'R4 草稿≠已保存 → curated',
)
eq(resolveRecommended(deepseek, 'deepseek', []), ['deepseek-v4-pro', 'deepseek-flash'], 'R5 live 空 → curated')
eq(
  resolveRecommended(
    { id: 'moonshot', models: ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'] },
    'moonshot',
    ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
  ),
  ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
  'R6 Moonshot 保序（kimi-latest 不退化）',
)
eq(
  resolveRecommended(deepseek, 'deepseek', ['tts-1', 'whisper-1']),
  ['tts-1', 'whisper-1'],
  'R7 live 全非对话 → 安全阀重算',
)
eq(
  resolveRecommended({ id: 'deepseek', models: ['xxx-vision-exp'] }, 'deepseek', ['xxx-vision-exp']),
  ['xxx-vision-exp'],
  'R8 valid==1 且补位空 → [valid[0]]',
)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

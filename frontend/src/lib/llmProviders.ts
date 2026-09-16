/* LLM 服务商预设库（纯前端 UX 辅助，非配置真相源）。

  为什么存在：用户通常只知道 API Key，不知道 Base URL 填什么。
  本预设把「填传输层参数」变成「选服务商」——选中即自动带出官方
  OpenAI 兼容端点，并附官网申请 Key 入口；同时把推荐模型**自动同步**
  到模型矩阵 4 字段（映射规则见 SettingsPage.tsx 的 presetModels()）。

  边界与取舍（协议/header 限制，勿收录为误导项）：
  - Anthropic：原生 API 非 OpenAI 兼容，本项目 OpenAI SDK 无法直连，
    需走 OpenAI 兼容网关 → 归入「自定义 URL」场景。
  - OpenRouter：OpenAI 兼容但要求自定义 header（HTTP-Referer/X-Title），
    本项目单连接 SDK 不支持 → 同上。
  - 各厂商 models 是「切厂商时的自动同步值 + VCombobox 候选」（厂商会更新），
    输入框始终可手输任意 ID 覆盖，「连接测试」按钮做即时验证，双保险。

  注：配置键已泛化为厂商无关的 llm_*（llm_api_key/llm_base_url/llm_model*），
  选择器把选中的预设 baseUrl 写入 llm_base_url，键名与厂商解耦
  （见「模型配置键名泛化实施计划.md」）。 */

export interface LLMProviderPreset {
  id: string
  name: string
  /** 官方 OpenAI 兼容 Base URL（无尾斜杠规范形） */
  baseUrl: string
  /** 官网申请 API Key 页 */
  keyUrl: string
  /** 推荐模型候选（可空 = 不提供建议，见火山方舟 ep-xxx 场景） */
  models: string[]
  /** 选填：连接/填写的补充提示 */
  note?: string
  /** 选填：是否支持运行时从 `${baseUrl}/models` 拉取实时模型列表（enrichment layer）。
      默认 true；已知不支持 OpenAI 兼容 /models 的厂商（如火山方舟走接入点）设 false。 */
  liveModels?: boolean
}

export const CUSTOM_PROVIDER_ID = 'custom'

export const LLM_PROVIDER_PRESETS: LLMProviderPreset[] = [
  {
    id: 'bigmodel',
    name: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    keyUrl: 'https://open.bigmodel.cn/usercenter/apikeys',
    models: [
      'glm-5.2',
      'glm-5.1',
      'glm-4.6',
      'glm-z1-air',
      'glm-z1-flash',
      'glm-4.5-air',
    ],
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    keyUrl: 'https://platform.deepseek.com/api_keys',
    models: ['deepseek-v4-pro', 'deepseek-flash'],
  },
  {
    id: 'moonshot',
    name: 'Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    keyUrl: 'https://platform.moonshot.cn/console/api-keys',
    models: ['kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
  },
  {
    id: 'qwen',
    name: '通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    keyUrl: 'https://bailian.console.aliyun.com/?apiKey=1',
    models: ['qwen-max', 'qwen-plus', 'qwen-turbo', 'qwen-long'],
  },
  {
    id: 'volces',
    name: '豆包 / 火山方舟',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    keyUrl: 'https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey',
    models: [],
    liveModels: false,
    note: '火山方舟按「推理接入点」调用：模型 ID 请填你在控制台创建的接入点（形如 ep-xxxxxxxxxxxx）',
  },
  {
    id: 'siliconflow',
    name: '硅基流动',
    baseUrl: 'https://api.siliconflow.cn/v1',
    keyUrl: 'https://cloud.siliconflow.cn/account/ak',
    models: [
      'deepseek-ai/DeepSeek-V3',
      'deepseek-ai/DeepSeek-R1',
      'Qwen/Qwen3-235B-A22B',
      'THUDM/GLM-4-9B-0414',
    ],
  },
  {
    id: 'minimax',
    name: 'MiniMax',
    baseUrl: 'https://api.minimax.io/v1',
    keyUrl: 'https://platform.minimaxi.com/user-center/basic-information/interface-key',
    models: ['MiniMax-Text-01', 'abab6.5s-chat'],
    note: '国内版平台域名见 MiniMax 官网；此处为国际版 OpenAI 兼容端点',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    keyUrl: 'https://platform.openai.com/api-keys',
    models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1'],
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    keyUrl: 'https://aistudio.google.com/apikey',
    models: [
      'gemini-3.1-pro-preview',
      'gemini-2.5-flash',
      'gemini-2.0-flash',
    ],
  },
]

/** 归一化 Base URL：去首尾空白 + 去尾部斜杠。比较是否命中预设前必须归一化。 */
export function normalizeProviderUrl(u?: string | null): string {
  return (u ?? '').trim().replace(/\/+$/, '')
}

/** 按归一化 Base URL 查找命中的预设；未命中返回 null（即「自定义」场景）。 */
export function findProviderByBaseUrl(baseUrl?: string | null): LLMProviderPreset | null {
  const n = normalizeProviderUrl(baseUrl)
  if (!n) return null
  return LLM_PROVIDER_PRESETS.find((p) => p.baseUrl === n) ?? null
}

export function findProviderById(id: string): LLMProviderPreset | null {
  return LLM_PROVIDER_PRESETS.find((p) => p.id === id) ?? null
}

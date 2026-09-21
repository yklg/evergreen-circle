import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  Cookie,
  ExternalLink,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  Server,
  SlidersHorizontal,
  TriangleAlert,
} from 'lucide-react'
import { VButton, VCard, VCombobox, VModal } from '../components/ui'
import { fetchSettings, pingLLM, saveSettings } from '../lib/api'
import { useSettingsStore } from '../store/settingsStore'
import {
  LLM_PROVIDER_PRESETS,
  findProviderByBaseUrl,
  type LLMProviderPreset,
} from '../lib/llmProviders'
import {
  presetModels,
  resolveRecommended,
  candidatesFor,
  normalizeLive,
} from '../lib/modelResolution'
import type { SettingsResp, SettingsValues } from '../types'

/* 分组渲染顺序与文案（编辑弹窗左导航按此序渲染）。 */
const GROUP_ORDER = [
  'provider',
  'model_matrix',
  'params',
  'search',
  'platform',
] as const

const GROUP_META: Record<
  string,
  { title: string; desc: string; icon: typeof Server }
> = {
  provider: {
    title: '提供方连接',
    desc: 'LLM 服务的接口地址与身份凭据',
    icon: Server,
  },
  model_matrix: {
    title: '模型矩阵',
    desc: '按报告章节角色分配模型：重活用好模型、杂务用快模型',
    icon: Layers,
  },
  params: {
    title: '推理参数',
    desc: '调用超时与重试策略（temperature/max_tokens 由各调用点按任务精细控制，不提供全局配置）',
    icon: SlidersHorizontal,
  },
  search: {
    title: '搜索提供方',
    desc: '联网检索能力，用于采集目的地证据',
    icon: Search,
  },
  platform: {
    title: '平台采集',
    desc: '各平台 Cookie，用于舆情抓取',
    icon: Cookie,
  },
}

const FIELD_LABEL: Record<string, string> = {
  llm_base_url: 'Base URL',
  llm_api_key: 'API Key',
  llm_model: '默认模型',
  llm_model_core: '核心章',
  llm_model_aux: '辅助章',
  llm_model_fast: '杂务快速',
  llm_timeout: '超时（秒）',
  llm_max_retries: '重试次数',
  bocha_api_key: '博查 API Key',
  bocha_base_url: '博查 Base URL',
  search_timeout: '搜索超时（秒）',
  douyin_cookie: '抖音 Cookie',
  xhs_cookie: '小红书 Cookie',
  bilibili_cookie: 'B站 Cookie',
}

/** 平台采集 Cookie 获取教程：各平台登录页与关键字段清单（httpOnly 字段需扩展导出，手动复制也可能拿到）。 */
const COOKIE_GUIDE: { name: string; url: string; fields: string[] }[] = [
  {
    name: '抖音',
    url: 'www.douyin.com',
    fields: ['sessionid', 'sid_tt', 'sid_ucp_v1', 'passport_csrf_token', 'odin_tt', 's_v_web_id'],
  },
  {
    name: '小红书',
    url: 'www.xiaohongshu.com',
    fields: ['a1', 'web_session', 'webId', 'gid'],
  },
  {
    name: 'B站',
    url: 'www.bilibili.com',
    fields: ['SESSDATA', 'bili_jct', 'buvid3', 'DedeUserID'],
  },
]

/** 模型矩阵字段用「可输入的下拉」，便于填任意模型 ID */
const MODEL_FIELDS = new Set([
  'llm_model',
  'llm_model_core',
  'llm_model_aux',
  'llm_model_fast',
])

/** 模型矩阵解析纯函数从 './lib/modelResolution' 导入（见文件头注释）。 */

/** 把表单字符串还原成后端期望的类型（依据原始值类型推断） */
function toTyped(raw: string, original: unknown): string | number | boolean {
  if (typeof original === 'boolean') {
    return raw === 'true' || raw === '1' || raw === 'on'
  }
  if (typeof original === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : raw
  }
  return raw
}

export default function SettingsPage() {
  const [resp, setResp] = useState<SettingsResp | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err' | 'warn'; text: string } | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<(typeof GROUP_ORDER)[number]>('provider')
  // 平台采集「如何获取 Cookie」教程折叠态（默认收起，避免遮挡表单）
  const [cookieHelpOpen, setCookieHelpOpen] = useState(false)
  // 实时模型列表（enrichment layer）：仅对「已保存且命中的厂商」从后端拉取，避免草稿态跨厂商污染
  const [liveModels, setLiveModels] = useState<string[]>([])
  const liveCache = useRef<Record<string, string[]>>({})
  // 连接测试探测到的「模型不可用 + 建议迁移目标」（后端解析 404 返回），驱动自愈提示条
  const [suggestedModel, setSuggestedModel] = useState<string | null>(null)

  /** resp → form 的唯一转换点（评审 P1-①）：密钥不回显、其余 String(v)。
      load 初次填充与弹窗 onClose「丢弃草稿」共用，防两份逻辑漂移。 */
  const resetFormFromResp = useCallback((r: SettingsResp) => {
    const f: Record<string, string> = {}
    for (const [k, v] of Object.entries(r.values)) {
      // 密钥不回显到输入框（后端返回的是脱敏值，回显会让用户误存脱敏串）
      f[k] = r.secrets.includes(k) ? '' : String(v)
    }
    setForm(f)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    const r = await fetchSettings()
    setResp(r)
    if (r) resetFormFromResp(r)
    setLoading(false)
  }, [resetFormFromResp])

  useEffect(() => {
    void load()
  }, [load])

  const setField = (key: string, val: string) => {
    setForm((prev) => ({ ...prev, [key]: val }))
    setMsg(null)
  }

  /** 切厂商（弹窗内 chip）：写 base_url + 按映射规则覆盖模型矩阵 4 字段（草稿态）。
      不经 setField（避免清掉提示），完成后落一条可读提示告知已同步、可手改。 */
  const applyProviderPreset = (p: LLMProviderPreset) => {
    setForm((prev) => ({ ...prev, llm_base_url: p.baseUrl, ...presetModels({ models: recommendedModels(p) }) }))
    setMsg({
      kind: 'ok',
      text: `已切换到 ${p.name} 并同步模型矩阵${
        recommendedModels(p).length > 0 ? `（默认 ${recommendedModels(p)[0]}）` : '（该厂商需手填模型 ID，如火山方舟填 ep-xxx 接入点）'
      }，仍可继续手改任意模型`,
    })
  }

  /** 核心保存：全量 PUT（密钥留空 = 不修改）；成功刷新 resp、清空密钥框、自动关弹窗。 */
  const persist = async (vals: Record<string, string>): Promise<boolean> => {
    if (!resp) return false
    setSaving(true)
    setMsg(null)
    try {
      const patch: SettingsValues = {}
      for (const [k, v] of Object.entries(vals)) {
        const isSecret = resp.secrets.includes(k)
        // 密钥留空 = 不修改
        if (isSecret && v.trim() === '') continue
        patch[k] = toTyped(v, resp.values[k])
      }
      const saved = await saveSettings(patch)
      setResp((prev) =>
        prev
          ? { ...prev, values: saved.values, configured: saved.configured }
          : prev,
      )
      // 保存后清空密钥输入框，避免重复提交
      setForm((prev) => {
        const next = { ...prev }
        for (const k of resp.secrets) next[k] = ''
        return next
      })
      setMsg({ kind: 'ok', text: '已保存，下一次调用即生效（无需重启）' })
      setModalOpen(false)
      // 厂商可能已切换 → 清掉实时模型缓存，待 resp 更新后重新拉取
      liveCache.current = {}
      // 通知订阅 settings 的页面（HomePage 等）刷新模型选项
      void useSettingsStore.getState().load()
      return true
    } catch (e) {
      setMsg({ kind: 'err', text: e instanceof Error ? e.message : String(e) })
      return false
    } finally {
      setSaving(false)
    }
  }

  const onSave = () => persist(form)

  /** 弹窗关闭（× / Esc / 遮罩 / 取消）：丢弃未保存修改——form 重载回最近一次已保存值 */
  const closeModal = () => {
    setModalOpen(false)
    if (resp) resetFormFromResp(resp)
  }

  /** 置顶提示条「一键同步」：把映射结果写进草稿后立即持久化。
      P1-② 派生：概览 chips 读「已保存态」resp，必须落库 chips 才会更新、条才会消失；
      保存失败则还原草稿（条保留 + msg 报错）。 */
  const syncAndSave = async (p: LLMProviderPreset) => {
    if (!resp) return
    const target = { ...form, llm_base_url: p.baseUrl, ...presetModels({ models: recommendedModels(p) }) }
    setForm(target)
    setMsg(null)
    const ok2 = await persist(target)
    if (!ok2) resetFormFromResp(resp)
  }

  const onTest = async () => {
    setTesting(true)
    setMsg(null)
    const r = await pingLLM()
    if (r.ok) {
      setSuggestedModel(null)
      setMsg({ kind: 'ok', text: `连接正常 · 当前模型 ${r.model ?? '-'}` })
    } else if (r.reason === 'model_unavailable' && r.suggested_model) {
      // 后端已解析 404 并给出建议模型 → 点亮自愈提示条
      setSuggestedModel(r.suggested_model)
      setMsg({ kind: 'err', text: r.message ?? '当前模型不可用' })
    } else if (r.reason === 'temporarily_unavailable') {
      // 评审 P1-a：Google 临时高负载（503）→ 友好中文提示，不显示原始英文栈
      setSuggestedModel(null)
      setMsg({ kind: 'warn', text: r.message ?? '当前模型服务负载较高，请稍后重试' })
    } else {
      setSuggestedModel(null)
      setMsg({ kind: 'err', text: r.message ?? '连接失败' })
    }
    setTesting(false)
  }

  /** 一键迁移：把模型矩阵中等于「当前不可用模型」的字段替换为建议模型，保存后立即重测。
      保存走 persist() → saveSettings → 后端 apply_settings → invalidate_client()，
      确保 LLM 客户端缓存失效（评审 P0：自愈必须清客户端缓存）。 */
  const migrateToSuggested = async () => {
    if (!resp || !suggestedModel) return
    const oldModel = (resp.values.llm_model ?? form.llm_model ?? '').toString()
    const modelFields = ['llm_model', 'llm_model_core', 'llm_model_aux', 'llm_model_fast']
    const target: Record<string, string> = { ...form }
    let changed = false
    for (const k of modelFields) {
      if (target[k] === oldModel) {
        target[k] = suggestedModel
        changed = true
      }
    }
    // 兜底：若默认模型本就不是 oldModel（例如 core/aux/fast 才是），至少把默认模型更新为建议模型
    if (!changed) target.llm_model = suggestedModel
    setForm(target)
    setMsg(null)
    const ok2 = await persist(target)
    if (ok2) {
      setSuggestedModel(null)
      void onTest() // 保存后（已失效客户端）自动重测，验证迁移成功
    } else {
      resetFormFromResp(resp)
    }
  }

  const groups = useMemo(() => {
    if (!resp) return []
    return GROUP_ORDER.filter((g) => (resp.groups[g] ?? []).length > 0).map(
      (g) => ({ key: g, fields: resp.groups[g] }),
    )
  }, [resp])

  /* 当前命中的厂商预设（草稿态）：由 form.llm_base_url 归一化后反查。
     供弹窗 chips 高亮 / 候选集 / 模型联动 / 置顶提示条使用。 */
  const activePreset = useMemo(() => {
    const url = form.llm_base_url ?? ''
    return url ? findProviderByBaseUrl(url) : null
  }, [form.llm_base_url])

  /* 概览卡厂商徽章读「已保存态」（评审 P1-②）：按 resp.values.llm_base_url 反查。
     与草稿态 activePreset 分离——页面展示的是已落库事实，弹窗内草稿不污染概览。 */
  const savedPreset = useMemo(() => {
    const raw = resp?.values.llm_base_url
    return raw ? findProviderByBaseUrl(String(raw)) : null
  }, [resp])

  /* 匹配用的「厂商有效模型集」：live 优先 + curated 兜底（去重合并）。
     仅当草稿厂商 == 已保存厂商时才并入 live（与 VCombobox 候选同口径，防草稿态跨厂商污染）。
     即使 curated 再次忘了更新，只要 live 含该模型就不误报——结构性消除本类 bug。 */
  const candidateModels = useMemo(() => {
    if (!activePreset) return []
    const liveUsable = activePreset.id === savedPreset?.id ? liveModels : []
    return candidatesFor(activePreset, liveUsable)
  }, [activePreset, savedPreset, liveModels])

  /* 模型与端点错配检测（草稿态）：命中厂商且厂商有推荐模型，但当前默认模型不在其推荐内
     → 顶部显示「一键同步」提示（防 400）。 */
  const modelMismatch = useMemo(() => {
    if (!activePreset || candidateModels.length === 0) return false
    return !candidateModels.includes(form.llm_model ?? '')
  }, [activePreset, candidateModels, form.llm_model])

  /* 同步目标推荐集：live 优先、curated 兜底（详见 resolveRecommended 纯函数）。 */
  const recommendedModels = (p: LLMProviderPreset): string[] =>
    resolveRecommended(p, savedPreset?.id, liveModels)

  /* 运行时从厂商拉取实时模型列表（enrichment layer）：
     仅对「已保存且命中的厂商」生效——服务端读已存 key+baseUrl 拉 /models，
     成功则与 curated 合并去重 enrich 候选集；失败/无 key/厂商不支持 → 静默回退 preset，不阻断。
     按 saved baseUrl 会话缓存，避免重复请求。 */
  const fetchLiveModels = useCallback(async () => {
    const base = String(resp?.values.llm_base_url ?? '')
    const p = savedPreset
    if (!p || p.liveModels === false || p.models.length === 0 || !base) {
      setLiveModels([])
      return
    }
    if (liveCache.current[base]) {
      setLiveModels(liveCache.current[base])
      return
    }
    try {
      const r = await fetch('/api/llm/models')
      const data = await r.json()
      const models = data?.ok && Array.isArray(data.models) ? data.models : []
      liveCache.current[base] = models
      setLiveModels(models)
    } catch {
      setLiveModels([])
    }
  }, [resp, savedPreset])

  useEffect(() => {
    void fetchLiveModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resp, savedPreset])

  /* C4：刷新实时模型列表 —— 清 liveCache 会话缓存后复用 fetchLiveModels 重拉（只绕缓存，不加请求路径）。
     仅当草稿厂商 == 已保存厂商且厂商支持 live（/models）时展示：
     否则 live 候选本来就不并入候选集，刷新无意义（火山方舟 ep-xxx 场景自然排除）。 */
  const [refreshingLive, setRefreshingLive] = useState(false)
  const refreshLive = useCallback(async () => {
    const base = String(resp?.values.llm_base_url ?? '')
    if (base) delete liveCache.current[base]
    setRefreshingLive(true)
    try {
      await fetchLiveModels()
    } finally {
      setRefreshingLive(false)
    }
  }, [resp, fetchLiveModels])
  const canRefreshLive = !!(
    savedPreset &&
    savedPreset.liveModels !== false &&
    savedPreset.models.length > 0 &&
    activePreset?.id === savedPreset?.id
  )

  /* 字段行渲染：bool checkbox / 模型 VCombobox / password+text 三分支，弹窗各 tab 复用 */
  const renderFields = (fields: string[]) =>
    fields.map((f) => {
      if (!resp) return null
      const isSecret = resp.secrets.includes(f)
      const original = resp.values[f]
      const label = FIELD_LABEL[f] ?? f
      const value = form[f] ?? ''
      return (
        <div
          key={f}
          className="flex items-center gap-4 border-b border-line/50 py-2.5 last:border-b-0"
        >
          <label className="w-44 shrink-0 text-aux text-ink-2">{label}</label>
          <div className="flex-1">
            {typeof original === 'boolean' ? (
              <label className="inline-flex cursor-pointer items-center gap-2 text-aux text-ink">
                <input
                  type="checkbox"
                  checked={value === 'true'}
                  onChange={(e) => setField(f, e.target.checked ? 'true' : 'false')}
                  className="h-4 w-4 accent-primary"
                />
                {value === 'true' ? '开启' : '关闭'}
              </label>
            ) : MODEL_FIELDS.has(f) ? (
              <VCombobox
                value={value}
                onChange={(v) => setField(f, v)}
                candidates={candidateModels}
                liveCandidates={
                  activePreset?.id === savedPreset?.id ? normalizeLive(liveModels) : []
                }
                placeholder="选择或直接输入模型 ID"
                onRefresh={canRefreshLive ? refreshLive : undefined}
                refreshing={refreshingLive}
              />
            ) : (
              <input
                type={isSecret ? 'password' : 'text'}
                value={value}
                onChange={(e) => setField(f, e.target.value)}
                placeholder={
                  isSecret
                    ? `已保存（${original || '未设置'}），留空则不修改`
                    : ''
                }
                className={`h-10 w-full rounded-btn border border-line bg-card px-3.5 text-aux text-ink outline-none transition-all placeholder:text-ink-3 focus:border-primary focus:ring-2 focus:ring-primary/15 ${
                  isSecret ? 'font-mono text-tag' : ''
                }`}
              />
            )}
          </div>
        </div>
      )
    })

  if (loading) {
    return (
      <div className="mx-auto max-w-content px-8 py-8">
        <div className="flex items-center gap-2 text-ink-3">
          <Loader2 size={16} className="animate-spin" />
          正在加载配置…
        </div>
      </div>
    )
  }

  if (!resp) {
    return (
      <div className="mx-auto max-w-content px-8 py-8">
        <h1 className="font-serif text-h1 text-ink">模型配置</h1>
        <VCard className="mt-6">
          <p className="text-ink-2">
            无法连接到后端（
            <code className="rounded bg-primary-tint px-1.5 py-0.5 text-primary-deep">
              /api/settings
            </code>
            ）。请确认后端已启动：
          </p>
          <pre className="mt-3 overflow-x-auto rounded-btn bg-primary-tint p-3 text-tag text-primary-deep">
            ./restart.sh
          </pre>
          <div className="mt-4">
            <VButton variant="soft" onClick={() => void load()}>
              <RefreshCw size={15} /> 重试
            </VButton>
          </div>
        </VCard>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-h1 text-ink">模型配置</h1>
        <p className="text-aux text-ink-2">
          在界面上配置 LLM 提供方与推理参数，保存后立即生效，无需重启、无需手改 .env
        </p>
      </header>

      {/* 置顶提示条：模型被厂商下架/不再可用，后端解析 404 给出建议模型 → 自愈迁移入口（优先级高于 modelMismatch） */}
      {suggestedModel && (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-card border border-warn/40 bg-warn/10 px-4 py-3">
          <TriangleAlert size={16} className="shrink-0 text-warn" />
          <span className="min-w-0 flex-1 text-tag leading-relaxed text-ink-2">
            当前默认模型{' '}
            <code className="rounded bg-card px-1.5 py-0.5 font-mono text-warn">
              {resp?.values.llm_model || form.llm_model || '（空）'}
            </code>{' '}
            已被 {savedPreset?.name ?? '该厂商'} 下架或不再对新用户开放。
          </span>
          <button
            type="button"
            onClick={() => void migrateToSuggested()}
            disabled={saving}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-chip bg-primary px-3 text-tag font-medium text-white transition-all hover:bg-primary-deep active:scale-95 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} strokeWidth={2.2} />
            )}
            一键迁移到 {suggestedModel}
          </button>
        </div>
      )}

      {/* 置顶提示条：模型与端点错配（从 model_matrix 卡内上移至页面顶部，全宽可见）；自愈态时让位 */}
      {modelMismatch && activePreset && !suggestedModel && (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-card border border-warn/40 bg-warn/10 px-4 py-3">
          <TriangleAlert size={16} className="shrink-0 text-warn" />
          <span className="min-w-0 flex-1 text-tag leading-relaxed text-ink-2">
            当前默认模型{' '}
            <code className="rounded bg-card px-1.5 py-0.5 font-mono text-warn">
              {form.llm_model || '（空）'}
            </code>{' '}
            与 {activePreset.name} 端点不匹配，「连接测试」会报 400。
          </span>
          <button
            type="button"
            onClick={() => void syncAndSave(activePreset)}
            disabled={saving}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-chip bg-primary px-3 text-tag font-medium text-white transition-all hover:bg-primary-deep active:scale-95 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} strokeWidth={2.2} />
            )}
            一键同步为 {recommendedModels(activePreset)[0]}
          </button>
        </div>
      )}

      {/* 概览卡：B3 栅格迷你卡（提供方/模型矩阵/搜索 三块）+ 底部动作区；编辑一律进弹窗 */}
      <div className="mt-5 flex flex-col gap-4 rounded-card border border-line/60 bg-card p-5 shadow-card">
        {/* 3 个迷你卡：sm 以上 3 列等宽，移动端 1 列 stack */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {/* 提供方 */}
          <div className="rounded-btn bg-primary-tint/60 p-4">
            <div className="text-tag text-ink-3">提供方</div>
            <div className="mt-2">
              <span
                className={`inline-flex h-7 items-center gap-1.5 rounded-chip px-3 text-tag font-medium ${
                  resp.configured.llm ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'
                }`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {savedPreset?.name ?? (resp.values.llm_base_url ? '自定义' : '未设置')}
                <span className="ml-1 text-ink-3/70">
                  · {resp.configured.llm ? '已配置' : '未配置'}
                </span>
              </span>
            </div>
          </div>
          {/* 模型矩阵 */}
          <div className="rounded-btn bg-primary-tint/60 p-4">
            <div className="text-tag text-ink-3">模型矩阵</div>
            <div className="mt-2 flex flex-col gap-1.5">
              {(
                [
                  ['默认', resp.values.llm_model ?? ''],
                  ['核心', resp.values.llm_model_core ?? ''],
                  ['辅助', resp.values.llm_model_aux ?? ''],
                  ['杂务', resp.values.llm_model_fast ?? ''],
                ] as const
              ).map(([role, m]) => (
                <div
                  key={role}
                  className="flex items-center justify-between gap-2 text-tag"
                >
                  <span className="shrink-0 text-ink-3">{role}</span>
                  <span className="truncate font-mono text-ink">{m || '-'}</span>
                </div>
              ))}
            </div>
          </div>
          {/* 搜索 */}
          <div className="rounded-btn bg-primary-tint/60 p-4">
            <div className="text-tag text-ink-3">搜索</div>
            <div className="mt-2">
              <span
                className={`inline-flex h-7 items-center gap-1.5 rounded-chip px-3 text-tag font-medium ${
                  resp.configured.bocha ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'
                }`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {resp.configured.bocha ? '博查已配置' : '未配置'}
              </span>
            </div>
          </div>
        </div>
        {/* 底部动作区 */}
        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line/50 pt-4">
          <VButton variant="soft" onClick={() => void onTest()} disabled={testing}>
            {testing ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <RefreshCw size={15} />
            )}
            连接测试
          </VButton>
          <VButton onClick={() => setModalOpen(true)}>
            <SlidersHorizontal size={16} /> 编辑配置
          </VButton>
        </div>
      </div>

      <p className="mt-3 text-tag text-ink-3">
        配置优先级：界面设置 &gt; .env 默认值 · 密钥仅存服务端，不会明文回传 · 分组表单已收纳到「编辑配置」弹窗
      </p>

      {/* C3：原单例 datalist 候选块已删除 —— 候选统一由 VCombobox 的 candidates 注入，无双轨 */}

      {/* 编辑配置弹窗 */}
      <VModal
        open={modalOpen}
        onClose={closeModal}
        title="编辑配置"
        width={860}
      >
        <div className="flex min-h-0 w-full">
          {/* 左导航 */}
          <nav className="w-40 shrink-0 overflow-y-auto border-r border-line/50 py-3">
            {groups.map(({ key }) => {
              const meta = GROUP_META[key]
              const Icon = meta?.icon ?? Server
              const active = key === activeTab
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveTab(key)}
                  className={`flex w-full items-center gap-2.5 border-l-2 px-4 py-2 text-left text-aux transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 ${
                    active
                      ? 'border-primary bg-primary-tint/60 font-medium text-primary-deep'
                      : 'border-transparent text-ink-2 hover:bg-primary-tint/40 hover:text-primary-deep'
                  }`}
                >
                  <Icon size={16} strokeWidth={1.8} className="shrink-0" />
                  {meta?.title ?? key}
                </button>
              )
            })}
          </nav>

          {/* 右内容：当前 tab 的表单 + 底部固定操作 */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              {groups
                .filter((g) => g.key === activeTab)
                .map(({ key, fields }) => {
                  const meta = GROUP_META[key]
                  const Icon = meta?.icon ?? Server
                  return (
                    <div key={key}>
                      <div className="flex items-start gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-btn bg-primary-tint text-primary-deep">
                          <Icon size={18} strokeWidth={1.8} />
                        </span>
                        <div>
                          <div className="text-[17px] font-semibold text-ink">
                            {meta?.title ?? key}
                          </div>
                          {meta?.desc && (
                            <div className="text-tag text-ink-3">{meta.desc}</div>
                          )}
                        </div>
                      </div>

                      {key === 'provider' && (
                        <div className="mt-5 rounded-card border border-primary/15 bg-primary-tint/50 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-aux font-medium text-ink">选择服务商</div>
                            <div className="text-tag text-ink-3">
                              选中即自动填入官方端点并同步模型矩阵，只需粘贴 API Key
                            </div>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {LLM_PROVIDER_PRESETS.map((p) => {
                              const active = p.id === activePreset?.id
                              return (
                                <button
                                  key={p.id}
                                  type="button"
                                  onClick={() => applyProviderPreset(p)}
                                  title={p.baseUrl}
                                  className={`inline-flex h-8 items-center gap-1.5 rounded-chip px-3 text-tag font-medium transition-all ${
                                    active
                                      ? 'bg-primary text-white shadow-sm'
                                      : 'border border-line/70 bg-card/80 text-ink-2 hover:border-primary/60 hover:text-primary-deep'
                                  }`}
                                >
                                  {active && <Check size={13} strokeWidth={2.5} />}
                                  {p.name}
                                </button>
                              )
                            })}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-tag">
                            {activePreset ? (
                              <>
                                <span className="font-medium text-ok">
                                  已匹配 {activePreset.name} 官方端点，模型矩阵已自动同步（仍可手改任意 ID）
                                </span>
                                {activePreset.note && (
                                  <>
                                    <span className="text-ink-3">·</span>
                                    <span className="text-ink-2">{activePreset.note}</span>
                                  </>
                                )}
                                <span className="text-ink-3">·</span>
                                <a
                                  href={activePreset.keyUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-primary-deep underline-offset-2 hover:underline"
                                >
                                  申请 API Key
                                  <ExternalLink size={12} />
                                </a>
                              </>
                            ) : (
                              <>
                                <span className="font-medium text-warn">
                                  {form.llm_base_url ? '自定义 Base URL' : '尚未填写 Base URL'}
                                </span>
                                <span className="text-ink-3">·</span>
                                <span className="text-ink-2">
                                  可手动填写任意 OpenAI 兼容网关地址（Anthropic / OpenRouter
                                  等需经兼容网关中转）
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      )}

                      {key === 'platform' && (
                        <div className="mt-5 rounded-card border border-primary/15 bg-primary-tint/50 p-4">
                          <button
                            type="button"
                            onClick={() => setCookieHelpOpen((o) => !o)}
                            className="flex w-full items-center justify-between text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                          >
                            <span className="text-aux font-medium text-ink">
                              如何获取平台 Cookie？
                            </span>
                            <ChevronDown
                              size={16}
                              strokeWidth={1.8}
                              className={`shrink-0 text-ink-3 transition-transform duration-200 ${
                                cookieHelpOpen ? 'rotate-180' : ''
                              }`}
                            />
                          </button>
                          {cookieHelpOpen && (
                            <div className="mt-3 space-y-3 text-tag text-ink-2">
                              <ol className="list-decimal space-y-1 pl-5 leading-relaxed">
                                <li>
                                  用电脑浏览器（Chrome / Edge / 火狐）打开并
                                  <strong className="text-ink">登录</strong>
                                  对应平台网页版。
                                </li>
                                <li>
                                  按 <code className="rounded bg-card px-1.5 py-0.5 font-mono text-ink">F12</code>{' '}
                                  打开开发者工具 → <strong className="text-ink">Network（网络）</strong> →
                                  刷新页面 → 左侧点任意该域名请求。
                                </li>
                                <li>
                                  右侧 <strong className="text-ink">Headers → Request Headers → Cookie</strong>
                                  ，整行复制（形如{' '}
                                  <code className="rounded bg-card px-1.5 py-0.5 font-mono text-ink">
                                    name1=v1; name2=v2; …
                                  </code>
                                  ），粘进对应框保存。
                                </li>
                              </ol>
                              <div className="grid gap-2 sm:grid-cols-3">
                                {COOKIE_GUIDE.map((p) => (
                                  <div key={p.name} className="rounded-btn bg-card/70 p-3">
                                    <div className="font-medium text-ink">
                                      {p.name}{' '}
                                      <span className="text-tag text-ink-3">({p.url})</span>
                                    </div>
                                    <div className="mt-1 break-all font-mono text-tag text-ink-3">
                                      {p.fields.join(' / ')}
                                    </div>
                                  </div>
                                ))}
                              </div>
                              <p className="text-ink-3">
                                嫌手动复制麻烦？用本项目附带的「Cookie 导出扩展」（
                                <span className="font-mono text-ink-2">cookie-export-helper/</span>
                                ），在已登录页面点一下即复制全部 Cookie（含 httpOnly）。
                              </p>
                              <p className="text-warn">
                                ⚠️ Cookie 含登录态，勿泄露、勿提交到公开仓库；部分平台会过期，失效后重新复制一次即可。
                              </p>
                            </div>
                          )}
                        </div>
                      )}

                      <div className="mt-5">{renderFields(fields)}</div>
                    </div>
                  )
                })}
            </div>

            {/* 弹窗内操作反馈条（保存失败时不用关窗就能看到错误） */}
            {msg && (
              <div
                className={`border-t border-line/50 px-6 py-2.5 text-tag ${
                  msg.kind === 'ok'
                    ? 'text-ok'
                    : msg.kind === 'warn'
                      ? 'text-warn'
                      : 'text-risk'
                }`}
              >
                {msg.text}
              </div>
            )}

            {/* 底部固定操作 */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line/50 px-6 py-4">
              <span className="text-tag text-ink-3">
                未保存的修改将在关闭时丢弃
              </span>
              <div className="flex items-center gap-3">
                <VButton variant="soft" onClick={closeModal} disabled={saving}>
                  取消
                </VButton>
                <VButton onClick={() => void onSave()} disabled={saving}>
                  {saving ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Search size={16} />
                  )}
                  保存配置
                </VButton>
              </div>
            </div>
          </div>
        </div>
      </VModal>

      {/* 页面级反馈（弹窗打开时其内部已有反馈条，避免遮罩下重影） */}
      {!modalOpen && msg && (
        <div
          className={`mt-4 whitespace-pre-wrap rounded-card border px-4 py-3 text-aux ${
            msg.kind === 'ok'
              ? 'border-ok/30 bg-ok/10 text-ok'
              : 'border-risk/30 bg-risk/10 text-risk'
          }`}
        >
          {msg.text}
        </div>
      )}
    </div>
  )
}

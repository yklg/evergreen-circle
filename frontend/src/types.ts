/* Verda 全局类型定义 —— 前后端契约 */

export type ExpertLevel = 'L1' | 'L2' | 'L3'
export type ExpertGroup = 'decision' | 'strategy' | 'facility' | 'method' | 'industry' | 'function'
export type ExpertStatus = 'idle' | 'working' | 'done' | 'rework'

export interface Expert {
  id: string
  level: ExpertLevel
  group: ExpertGroup
  name: string
  nickname: string
  role_title: string
  one_liner: string
  skills: string[]
  knowledge_base: string
  knowledge_tags: string[]
  avatar: string
  badge_color: string
  domain_icon: string
  gender: 'male' | 'female'
  status: ExpertStatus
  stats: { missions: number; avg_evidence: number }
}

/* 任务创建返回 */
export interface ClarifyQuestion {
  id: string
  question: string
  hint?: string
  type: 'single' | 'multi' | 'text' | 'slider'
  options?: string[]
}
export interface CreateTaskResp {
  taskId: string
}

/* SSE 事件 */
export type SSEEventType =
  | 'node_update'
  | 'thought'
  | 'message'
  | 'evidence'
  | 'chart'
  | 'image'
  | 'progress'
  | 'trace'
  | 'report_ready'
  | 'done'
  | 'error'

/* 澄清问卷 SSE 事件（CreateTaskResp 不再携带问卷，改为 ClarifyPage 内 SSE 懒加载） */
export type ClarifySSEEventType = 'clarify_stage' | 'clarify_ready' | 'clarify_update' | 'error'

export interface ClarifySSEHandlers {
  onEvent: (type: ClarifySSEEventType, data: unknown) => void
  onError?: (e: unknown) => void
  onOpen?: () => void
}

/* 可观测性 Trace Span */
export interface TraceSpan {
  span_id: string
  seq: number
  agent_id: string
  stage: string
  purpose: string
  model: string
  prompt: string
  response: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  latency_ms: number
  decision?: string
  evidence_ids?: string[]
  ts: string
}

export interface DAGNode {
  id: string
  label: string
  status: ExpertStatus
  expert?: string // expert id
}

export type ThoughtKind = 'plan' | 'dispatch' | 'action' | 'finding' | 'reflect'

export interface ThoughtItem {
  id: string
  kind: ThoughtKind
  expert?: string
  text: string
  ts: number
}

export interface Evidence {
  evidence_id: string
  source_url: string
  source_type: string
  title: string
  excerpt: string
  screenshot_path?: string
  image_urls?: string[]
  captured_at: string
  credibility: number
  collected_by: string
  brand?: string
  domain?: string
  freshness_days?: number | null
  /* v2.1 客观性加固元数据（信源组 / 舆论过热，均可选兼容旧数据） */
  content_hash?: string
  source_group?: string
  republished_from?: string[]
  viral?: boolean
  viral_reason?: string
}

export interface Claim {
  claim_id: string
  text: string
  field: string
  evidence_ids: string[]
  confidence: 'high' | 'medium' | 'low' | 'unverified'
  cross_validated: boolean
  author: string
  claim_type?: 'fact' | 'opinion' | 'mixed'
}

export interface ChartSpec {
  chart_id: string
  type: string
  title?: string
  option: Record<string, unknown>
  png?: string
  evidence_ids?: string[]
}

export interface ProgressInfo {
  percent: number
  evidence_count: number
  token_used: number
  stage: string
}

/* 数据空间（CSV 表格） */
export interface DataGrid {
  columns: string[]
  rows: {
    name: string
    value: string | number
    metric: string
    source: string
    source_url: string
    evidence_id?: string
  }[]
}

/* 结构化竞品知识 */
export interface StructuredBlock {
  type: 'feature_tree' | 'pricing_model' | 'user_persona'
  data: Record<string, unknown>[]
}

/* 报告 */
export interface ReportSection {
  id: string
  title: string
  level: number
  key_takeaway?: string
  highlights?: string[]
  paragraphs?: string[]
  claims?: Claim[]
  charts?: ChartSpec[]
  source_evidence_ids?: string[]
  structured?: StructuredBlock | null
  data_grid?: DataGrid | null
  refined?: boolean
}

/* 量化指标 */
export interface ReportMetrics {
  efficiency?: Record<string, unknown>
  coverage?: Record<string, unknown>
  consistency?: Record<string, unknown>
  business?: Record<string, unknown>
}

export interface SentimentResult {
  overall: { pos: number; neu: number; neg: number }
  overall_count?: { pos: number; neu: number; neg: number }
  by_platform: Record<string, { pos: number; neu: number; neg: number }>
  timeline: { date: string; pos: number; neu: number; neg: number }[]
  camps: { title: string; ratio: number; summary: string; quotes: { text: string; url: string; platform?: string }[] }[]
  voices?: { platform: string; platform_label: string; text: string; sentiment: string; url: string; title?: string }[]
  highlights?: { phrase: string; platform: string; platform_label: string; sentiment: string; url: string }[]
  sample_size: number
}

export interface Report {
  id: string
  title: string
  subtitle: string
  /** A1 弱关联：research=竞争调研报告；living_circle=生活圈体检报告（渲染适配器据此前再分发） */
  report_type?: 'research' | 'living_circle'
  query?: string
  brands?: string[]
  mode?: string
  created_at: string
  experts: string[]
  dispatch?: { id: string; reason: string }[]
  cover_image?: string
  toc: { id: string; title: string; level: number }[]
  sections: ReportSection[]
  charts: ChartSpec[]
  evidence: Evidence[]
  claims: Claim[]
  sentiment?: SentimentResult
  glossary: { term: string; definition: string; source?: string }[]
  figures?: ReportFigure[]
  structured?: Record<string, Record<string, unknown>[]>
  metrics?: ReportMetrics
  quality_before?: Record<string, unknown>
  quality_after?: Record<string, unknown>
  audit_review?: AuditReview
  trace?: TraceSpan[]
  /* v2.1 客观性：方法论与局限 + 矛盾陈述（正式契约字段，均可选） */
  methodology?: ReportMethodology
  contradictions?: ReportContradiction[]
  /** 一页纸精炼（派生数据，懒生成落库；报告内容变更后失效） */
  brief?: ReportBrief
  /** LLM 生成失败时间戳（ISO）；距今 <30s 时前端冷却防止重复触发 */
  brief_failed_at?: string
  /** 常青圈·生活圈体检数据（F0 契约，地图等时圈/POI/盲区/评分） */
  living_circle?: LivingCircleReport
}

/** v2.1 方法论与局限披露 */
export interface ReportMethodology {
  window?: string
  evidence_count?: number
  unique_groups?: number
  dup_skipped?: number
  viral_evidence?: number
  viral_checked_ratio?: number
  sentiment_samples?: number
  note?: string
}

/** v2.1 来源间存在分歧/矛盾的陈述 */
export interface ReportContradiction {
  claim_text: string
  evidence_ids: string[]
  note?: string
}

/** 一页纸精炼简报：把整份报告压缩为汇报要点 */
export interface ReportBrief {
  summary: string
  judgments: string[]
  key_data: string[]
  actions: string[]
}

export interface AuditOpinion {
  verdict?: string
  scores?: Record<string, number>
  review?: string
  issues?: string[]
  suggestions?: string[]
}

export interface AuditReview {
  before?: AuditOpinion
  after?: AuditOpinion
  rework_rounds?: number
  issues_resolved?: number
}

export interface ReportFigure {
  src: string
  alt?: string
  title?: string
  source_url: string
  domain?: string
  source_type?: string
  brand?: string
  evidence_id?: string
}

/* 报告卡片（历史列表，不含全文） */
export interface ReportCard {
  id: string
  report_id: string
  title: string
  subtitle: string
  query: string
  brands: string[]
  experts: string[]
  cover_image?: string
  evidence_count: number
  claim_count: number
  high_conf_count: number
  created_at: string
}

/* 仪表盘真实统计 */
export interface ResearchCard {
  id: string
  title: string
  query: string
  brands: string[]
  evidence_count: number
  claim_count: number
  high_conf_count: number
  created_at: string
  efficiency_multiple?: number | null
  coverage_multiple?: number | null
  elapsed_minutes?: number | null
  minutes_saved?: number | null
  tokens_used?: number | null
}

export interface DashboardStats {
  reports: number
  evidence_total: number
  claim_total: number
  high_conf_total: number
  avg_evidence_per_report: number
  fact_accuracy: number
  platform_distribution: Record<string, number>
  brand_distribution: Record<string, number>
  // 业务闭环聚合（真实，来自各报告 metrics）
  minutes_saved?: number
  avg_efficiency?: number
  avg_coverage?: number
  total_tokens?: number
  research_cards?: ResearchCard[]
}

/* 全局证据溯源库 */
export interface EvidenceRecord {
  evidence_id: string
  report_id: string
  source_url: string
  source_type: string
  domain: string
  title: string
  excerpt: string
  credibility: number
  collected_by: string
  brand: string
  captured_at: string
}
export interface EvidenceFacets {
  total: number
  by_type: Record<string, number>
  by_brand: Record<string, number>
}
export interface EvidenceQueryResp {
  items: EvidenceRecord[]
  facets: EvidenceFacets
}

/* 竞品监控订阅 */
export interface Subscription {
  sub_id: string
  query: string
  brands: string[]
  created_at: string
  last_run_at: string
  last_report_id: string
  run_count: number
}

/* 专家工作量 */
export interface ExpertWorkload {
  id: string
  name: string
  title: string
  layer: string
  avatar: string
  missions: number
  claims_authored: number
  evidence_collected: number
  last_active: string
}

/* ── 模型配置（运行时可覆盖配置）─────────────────────────
   优先级：界面设置 > .env 默认值。密钥字段 GET 时一律为脱敏值。 */
export type SettingsGroupKey =
  | 'provider'
  | 'model_matrix'
  | 'params'
  | 'search'
  | 'platform'

export type SettingsValues = Record<string, string | number | boolean>

export interface SettingsConfigured {
  llm: boolean
  bocha: boolean
}

export interface SettingsResp {
  ok: boolean
  /** 脱敏后的有效配置（密钥为 sk-****xxxx 形式） */
  values: SettingsValues
  /** 哪些键属于密钥（前端据此渲染密码框 + 留空不改） */
  secrets: string[]
  /** 分组 → 字段列表，供前端按组渲染表单 */
  groups: Record<string, string[]>
  configured: SettingsConfigured
}

export type SaveSettingsResp = Omit<SettingsResp, 'secrets' | 'groups'>

/* ── 用户级偏好（prefs：昵称 / 公司 / 界面选择）─────────────
   与 SettingsResp 的边界：settings 是系统级运行时配置（密钥 GET 脱敏）；
   prefs 是用户级偏好，明文、无密钥、原样返回，且**只回库中实际存在的键**
   （前端靠 stored 判定"是否首次"，见 src/lib/persist.ts）。 */
export type PrefValue = string | number | boolean
export type PrefsValues = Record<string, PrefValue>

export interface PrefsResp {
  ok: boolean
  /** 库中实际存在的偏好（不合成默认值 —— 缺失即代表"服务端还没有这一项"） */
  values: PrefsValues
  /** 库中存在的键列表；空数组 = 远端为空（首次） */
  stored: string[]
  /** 分组 → 键列表 */
  groups: Record<string, string[]>
}

/** 连接测试（/api/llm/ping）响应。reason=model_unavailable 时携带建议迁移模型。 */
export interface PingLLMResp {
  ok: boolean
  model?: string
  message?: string
  /** 失败原因枚举：not_configured / model_unavailable / error */
  reason?: string
  /** 厂商在 404 错误中给出的建议模型（如 gemini-3.1-pro-preview） */
  suggested_model?: string
}

/* ── 常青圈 · 15 分钟生活圈体检（F0 冻结契约）────────────────────────────────
   后端与前端共同遵守；F 阶段由 fixture 驱动，M 阶段后端按此结构实现。 */

/** BD-09 经纬度 [lng, lat] */
export type LngLat = [number, number]

/** 简易 GeoJSON 多边形（等时圈 / 盲区灰区共用） */
export interface GeojsonPolygon {
  type: 'Polygon'
  /** 环数组：外环 = [LngLat, ...]，坐标闭合 */
  coordinates: LngLat[][]
}

/** 体检场景（一次体检的输入定格） */
export interface LifeCircleScene {
  name: string
  city: string
  address: string
  /** 中心点（BD-09） */
  center: LngLat
  /** 研究范围半径(m)，步行 20min 裕量，默认 2500 */
  study_radius_m: number
}

/** 分级等时圈（5/10/15/20 分钟） */
export interface IsochroneZone {
  minutes: number
  geojson: GeojsonPolygon
  area_km2: number
}

/** 采样点（渔网/网格测时结果；fixture 阶段为圆形近似合成点） */
export interface SamplingPoint {
  idx: number
  lng: number
  lat: number
  /** 距中心点步行耗时(分钟)，不可达时为空 */
  minutes: number | null
  reachable: boolean
}

/** POI 类别统计（覆盖/可达/最近设施） */
export interface FacilityCategoryStat {
  /** 类别键：medical / education / shopping / market / elderly / finance / recreation / service */
  category: string
  label: string
  /** 研究范围内总数 */
  total: number
  /** 15 分钟圈内数量 */
  in_circle: number
  /** 覆盖度 0-1（圈内数/该类别在圈内的理想阈值） */
  coverage: number
  /** 最近设施步行耗时(分钟)，无则 null */
  min_minutes: number | null
  /** 最近设施名 */
  nearest_name: string | null
}

/** 单条服务盲区（1km 内无菜市场/药店/小学） */
export interface BlindSpot {
  id: string
  /** 盲区点位（网格中心） */
  center: LngLat
  /** 判定半径(m)，赛题标准 1000 */
  radius_m: number
  /** 缺失的必备设施（菜市场/药店/小学） */
  missing_facilities: string[]
  /** 最近各类设施（距离与方位，供整改建议） */
  nearest: {
    facility: string
    name: string
    distance_m: number
    direction: string
  }[]
  /** 灰色区域多边形 */
  polygon: GeojsonPolygon
}

/** 盲区三要素覆盖结论 */
export interface TriadFacility {
  facility: '菜市场' | '药店' | '小学'
  /** 15 分钟圈内是否可达 */
  covered: boolean
  nearest_name: string | null
  nearest_minutes: number | null
}

/** 体检评分（0-100 + 雷达 + 分项柱） */
export interface LifeCircleScores {
  total: number
  radar: { dimension: string; score: number }[]
  bars: { category: string; label: string; value: number }[]
  triads: TriadFacility[]
  /** 评测说明/算法版本 */
  note: string
}

/** 生活圈体检报告主体（挂载到 Report.living_circle） */
export interface LivingCircleReport {
  scene: LifeCircleScene
  generated_at: string
  /** live=真实百度 API 计算；fixture_sample=内置演示数据(圆形近似) */
  data_origin: 'live' | 'fixture_sample'
  isochrones: IsochroneZone[]
  sampling: {
    points: SamplingPoint[]
    /** 等时圈生成方式：idw=采样点反距离加权插值；circular_approx=圆形近似 */
    interpolation: 'idw' | 'circular_approx'
    /** 是否通过了散点扇形/双阶段采样（30% 评分点叙事） */
    is_scattered: boolean
  }
  poi: {
    categories: FacilityCategoryStat[]
    total: number
    in_circle: number
  }
  blindspots: BlindSpot[]
  scores: LifeCircleScores
}

/** 双样例对比（ComparePage 数据） */
export interface LifeCircleCompare {
  reports: LivingCircleReport[]
  diff: {
    metric: string
    a_value: number | string
    b_value: number | string
    desc: string
  }[]
}

/** 前端体检模式（快/标准/精细，映射后端采样档位） */
export type LifeCircleMode = 'quick' | 'standard' | 'precise'

/** 历史体检记录（历史页 / 报告中心列表项；M 阶段由 living_circle_reports 列表接口返回） */
export interface LifeCircleRecord {
  id: string
  title: string
  scene_name: string
  city: string
  checked_at: string
  total_score: number
  blindspot_count: number
  data_origin: 'live' | 'fixture_sample'
  interpolation: 'idw' | 'circular_approx'
}

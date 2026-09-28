/* 常青圈全局类型定义 —— 前后端契约 */

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
  /** 条件题显隐元数据（rough-cliff-vole）：仅当被引题答案恰等于 equals 时展示；旧后端无此字段=恒展示 */
  show_if?: { qid: string; equals: string }
  /** 目的地题的工作量事实量（后端按所选档位下发）；旧后端无此字段时不渲染提示 */
  workload?: {
    mode?: string
    mode_label?: string
    max_angles?: number
    fetch_per_destination?: number
  }
}
export interface CreateTaskResp {
  taskId: string
  /** 任务路由 kind（research / travel_guide / travel_assess / living_circle）；真实态由后端按 type 落库。 */
  kind?: string
  /** 仅演示回放桥使用（guide/assess 历史方言）；新代码建任务以权威 type 为准。 */
  purpose?: string
  /** 归一化后的调研类型 key（后端 type_key() 回落 guide）；演示/LC 兜底路径可不带，读侧按 guide 容错 */
  researchType?: string
}

/* 调研类型（GET /api/research-types —— 注册表为唯一真相源，前端不复制文案） */
export interface ResearchTypeOption {
  key: string
  label: string
  subtitle: string
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
  destination?: string
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

/** 词云分层：`opinion` 评价词（大字、按极性着色）/ `topic` 话题词（地名等，小灰字垫背景）。 */
export type WordKind = 'opinion' | 'topic'

/** 情感极性（与后端 sentiment 三键、charts.SENTIMENT 同域）。 */
export type Polarity = 'pos' | 'neg' | 'neu'

export interface WordcloudWord {
  word: string
  weight: number
  /** 缺席 = 本次之前的存量报告载荷 → 词云走单层渲染（与今天逐像素一致），不得前端补默认值。 */
  kind?: WordKind
  polarity?: Polarity
}

export interface ChartSpec {
  chart_id: string
  type: string
  title?: string
  /** echarts 类图表的 option；wordcloud 新契约（words 载荷）无此键，故可选。 */
  option?: Record<string, unknown>
  /** wordcloud 语义载荷（E1 契约）：后端归一的 [{word,weight}]；旧报告无此键，走 option 双形状兼容。 */
  words?: WordcloudWord[]
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

/* 结构化调研知识（键集由后端 research_types 注册表按类型下发；竞品块已随旅游 pivot 清弃） */
export type StructuredBlockType =
  | 'spot_ranking' | 'spot_routes' | 'food_ranking' | 'shop_list'
  | 'route_plan' | 'stay_options' | 'cost_breakdown'
  | 'access_matrix' | 'amenity_checklist' | 'risk_profile'
  | 'persp_checklist' | 'persp_rules' | 'persp_packing'

export interface StructuredBlock {
  type: StructuredBlockType
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
  structured?: StructuredBlock[] | StructuredBlock | null
  data_grid?: DataGrid | null
  /** 后端写稿的结构状态：by_design=本章本无结构化材料，lost=写稿失败丢了结构（老报告无此字段） */
  structure_status?: 'ok' | 'repaired' | 'lost' | 'by_design'
  /**
   * 算分输入缺口（与 structure_status 正交的轴，老报告/无缺口章节为 null 或缺字段）：
   * kind=insufficient_input 表示「有材料但缺可核验数值」→ 本章算分图整体缺位，如实标注。
   */
  score_gap?: { kind?: string; reason: string } | null
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
  by_destination?: { destination: string; sample: number; pos: number; neu: number; neg: number }[]
  /** (spot × platform) 双维聚合（M2c）：逐景点口碑小表/舆情卡数据源，spot_id 直引冻结实体。
   *  `review_sample` = 该景点的可核验口碑条数（逐景点词云的出图门读它，不读 `sample`）。 */
  by_spot?: { spot_id: string; spot_name: string; sample: number; review_sample?: number; pos: number; neu: number; neg: number; by_platform: Record<string, number> }[]
  timeline: { date: string; pos: number; neu: number; neg: number }[]
  camps: { title: string; ratio: number; summary: string; quotes: { text: string; url: string; platform?: string }[] }[]
  voices?: { platform: string; platform_label: string; text: string; sentiment: string; url: string; title?: string }[]
  highlights?: { phrase: string; platform: string; platform_label: string; sentiment: string; url: string }[]
  /** 可核验用户口碑条数（本次之前生成的报告里它是「检索条数」，口径已收窄，故须与 corpus_size 并读）。 */
  sample_size: number
  /** 检索到的相关语料条数；缺席 = 存量报告无此口径。 */
  corpus_size?: number
  /** 语料按文档类型的分布（review/guide/ticket_faq/flight/seo/news/chrome）。 */
  doc_kind_counts?: Record<string, number>
  /** true ⇒ 口碑样本偏小，情感占比一律降级为计数呈现（伪精度不上图）。 */
  low_sample?: boolean
}

/* 目的地调研（guide/assess/research）扁平的确定性舆情聚合（research 流水线产出）：
 * 命中数为口碑证据条数，非平台样本量；仅含主题词频 + 代表原声，无竞品/平台语义。 */
export interface SentimentFlatResult {
  topic?: string
  positive?: number
  neutral?: number
  negative?: number
  themes?: string[]
  quotes?: { evidence_id?: string; text?: string }[]
  platform?: Record<string, unknown> | null
}

export interface Report {
  id: string
  title: string
  subtitle: string
  /** 渲染适配器依据：research=目的地综合调研报告；living_circle=生活圈体检报告 */
  report_type?: 'research' | 'living_circle'
  query?: string
  /** 目的地调研产出的 brands 恒为空（不产出竞品对比）；兼容旧报告保留 */
  brands?: string[]
  destinations?: string[]
  /** 调研类型（guide 游玩攻略 / assessment 调研评估；旧报告缺省视为 guide） */
  research_type?: string
  /** 报告头部答题摘要行（后端 CLARIFY_CONSUMERS digest 白名单派生；旧报告缺省不渲染） */
  answers_digest?: { label: string; value: string }[]
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
  /** 舆情口径三件套（词云口碑化修复步骤 8）：缺席 = 本次之前的存量报告，只有旧口径 `sentiment_samples`。 */
  sentiment_corpus?: number
  sentiment_doc_kind_counts?: Record<string, number>
  sentiment_low_sample?: boolean
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
  destination?: string
  evidence_id?: string
}

/* 报告卡片（历史列表，不含全文） */
export interface ReportCard {
  id: string
  report_id: string
  title: string
  subtitle: string
  query: string
  destinations: string[]
  research_type?: string
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
  destinations: string[]
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

/** 侧栏仪表盘：真分家后只剩这两个计数（其余口径全部搬进 `IntelOverview`）。
 *  多一个键就意味着侧栏轮询要付一次全量报告反序列化，判据见后端 `test_dashboard_stats.py`。 */
export interface DashboardStats {
  reports: number
  evidence_total: number
}

/** 目的地情报图谱节点（后端 `db.destination_graph()`，全库口径、非样本）。 */
export interface DestinationGraphNode {
  destination: string
  /** 换源形状：生活圈 POI 若进 evidences，只换输入源，节点与消费方不动 */
  domain: string
  source: string
  count: number
  source_types: string[]
  /** 0–100 直读，任何一层都不得再乘 100 */
  avg_credibility: number
  last_at: string | null
}

export interface DestinationGraph {
  nodes: DestinationGraphNode[]
  /** 没有目的地归属的证据行数：显式报数，不再被两层 continue 隐式抹掉 */
  unattributed: number
  scanned: number
}

/** 报告中心「目的地调研」tab 的整屏数据源（`GET /api/intel`）。 */
export interface IntelOverview {
  report_total: number
  evidence_total: number
  claim_total: number
  high_conf_total: number
  avg_evidence_per_report: number
  fact_accuracy: number
  platform_distribution: Record<string, number>
  destination_graph: DestinationGraph
  // 业务闭环聚合（后端 _agg_compute 恒发，故为必填：可选化只会让消费方各自兜底）
  minutes_saved: number
  avg_efficiency: number
  avg_coverage: number
  total_tokens: number
  cards: ResearchCard[]
  /** 概览卡受后端 LIMIT 约束时，卡上必须写明"仅列最近 N 份（库内共 M 份）" */
  cards_truncated: boolean
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
  destination: string
  captured_at: string
}
export interface EvidenceFacets {
  total: number
  by_type: Record<string, number>
  by_destination: Record<string, number>
}
export interface EvidenceQueryResp {
  items: EvidenceRecord[]
  facets: EvidenceFacets
}

/* 目的地监控订阅 */
export interface Subscription {
  sub_id: string
  query: string
  destinations: string[]
  type: string
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
  /** 距中心点步行耗时(分钟)，测时未返回时为空 */
  minutes: number | null
  /**
   * 测时返回了分钟值（⇒ 可参与插值）。**这不等于「可达」**。
   *
   * 旧字段名 `reachable` 的语义其实就是本字段，被 UI 读成「可达」后
   * 产出「采样点 1049 个（可达 1049）」——而 ≤reach_full_min 的只有一小部分。
   *
   * ⚠️ 阶段 −1 之前落库的历史报告**没有本字段**（只有旧名 `reachable`）。
   * 因此**不要直接读 `p.timed`**，一律走 `isTimedPoint(p)`（内含旧快照回退）——
   * 直接读会让历史报告的热力层被静默清空（老点全为 `undefined` ⇒ filter 全 false）。
   */
  timed?: boolean
  /**
   * 在可达区内：`timed && minutes <= caliber.reach_full_min`。**这才是「可达」**。
   * 同样**不要直接读**，走 `isInReachPoint(p, reachFullMin)`（缺省按 minutes 回算）。
   */
  in_reach?: boolean
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

/** POI 截断披露（阶段 1.3）：`poi.truncated`。无截断时 `dropped=0 / categories=[]`，字段恒存在。 */
export interface PoiTruncation {
  /** 本次装配所用的每类展示上限（`POI_CAP_PER_CAT`） */
  cap_per_cat: number
  /** 被截掉的点位总数（0 = 无截断） */
  dropped: number
  /** 逐类明细，只含真的发生截断的类别 */
  categories: { category: string; kept: number; dropped: number }[]
}

/**
 * 设施实体归并披露：`poi.merged`。
 *
 * 同一实体设施的功能子点（24 小时自助银行 / 个贷中心 / 门诊 / 停车场 / 大门）被百度作为
 * 独立 POI 返回，归并后每处设施只出一个点。`absorbed` 按**被吸收记录的身份**去重计数，
 * 因此它是「报告里少掉了几个设施」，不是「判据命中了几次」。
 *
 * 字段恒存在于新报告；**归并上线前冻结的快照缺此键** ⇒ 消费方走 `poiDedupeRuleLabel()`
 * 安全取值，不得无条件解构。守恒不变量对本字段完全免疫（老数字自洽地虚高着），
 * 所以这条披露是「合掉了几处」的唯一可见凭据。
 */
export interface PoiFacilityMerge {
  /** 判据版本（`facility_rule.FACILITY_RULE_VERSION`） */
  rule_version: string
  /** 本次报告是否在归并口径下产出 */
  enabled: boolean
  /** 因归并被吸收的设施总数（0 = 无归并） */
  absorbed: number
  /** 逐类明细，只含真的发生归并的类别 */
  categories: { category: string; absorbed: number }[]
}

/**
 * POI 点数守恒自检结论（阶段 1.4）：`poi.conservation`。
 *
 * 不变量 `sum(categories[].in_circle) === points.length`。后端在装配出口自检：
 * 测试/CI 违规即硬失败；生产/演示照出报告但把 `ok=false` 落在这里（**不静默**）。
 * 消费方请走 `poiConservation()`，不要自己求和下结论。
 */
export interface PoiConservationMeta {
  ok: boolean
  declared_in_circle: number
  actual_points: number
  /** 仅 `ok=false` 时存在：可读的违规描述（含逐类差额） */
  detail?: string
}

/** 单个 POI 点位（真实坐标，供 BMapGL 地图渲染；契约增量字段） */
export interface PoiPoint {
  id: string
  name: string
  /** 与 FacilityCategoryStat.category 同键 */
  category: string
  /** [lng, lat]（BD-09） */
  lnglat: LngLat
  /** 距中心点步行耗时(分钟)，插值回填；无则 null */
  minutes: number | null
  /** 是否落在 15min 等时圈内 */
  in_circle: boolean
}

/** 盲区补点处方（策略 + 优先级，供整改参考） */
export interface BlindFix {
  /** 缺失设施名（菜市场/药店/小学） */
  facility: string
  /** 建议补点位置 */
  point: LngLat
  /** 补建策略：mobile_service / reroute / build */
  strategy: 'mobile_service' | 'reroute' | 'build'
  /** 最近替代距离(m)，无任何该型设施时为 null */
  nearest_alt_m: number | null
  /** 覆盖的判盲格数 */
  served: number
  /** 全局整改优先级（连续唯一，越小越优先） */
  priority: number
}

/** 盲区到达最近替代设施的可达性（R3：优先等时圈实测） */
export interface BlindReach {
  real_walk_min: number | null
  /** 是否来自真实等时圈(IDW)实测；离线降级为 false */
  isochrone_based: boolean
}

/** 受影响人群（诚实代理：采样点实测 + 密度估算；离线为 null） */
export interface BlindAffected {
  /** 落在盲区多边形内的采样点数量（实测） */
  sampling_sites: number
  estimated_households: number
  estimated_residents: number
  /** 固定 'proxy'（估算非实测） */
  provenance: 'proxy'
  note: string
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
  /** 精确锯齿原始多边形（双边界解耦的 raw 档，供严格点内判断；smoothed 用于显示。老数据缺失时回退 polygon） */
  polygon_raw?: GeojsonPolygon
  /** 严重度分级：heavy / medium / light（v2 新字段，老数据可能缺失） */
  severity?: 'heavy' | 'medium' | 'light'
  /** 连续缺口指数 ∈ [0,1] */
  gap_score?: number
  /** 补点处方（按优先级排序） */
  fixes?: BlindFix[]
  /** 真实可达性 */
  reach?: BlindReach
  /** 受影响人群（估算代理；离线/无采样为 null） */
  affected?: BlindAffected | null
  /** 盲区边界几何元数据（v3 起 marching-squares 平滑边界；老数据可能缺失） */
  footprint_meta?: BlindFootprintMeta
}

/**
 * 盲区边界几何元数据（v3：连续场+ marching-squares 抽取平滑边界的自描述信息，
 * 可供前端判断边界分辨率、是否欠采样，并在「细化/原始」视图间做取舍）。
 */
export interface BlindFootprintMeta {
  /** 判定簇覆盖的网格格数 */
  cells: number
  /** 判定网格距(m) */
  grid_m: number
  /** 细分后边界采样分辨率(m) */
  resolution_m: number
  /** marching-squares 采样细化倍率（每判定格细分 refine² 个点） */
  refine: number
  /** 多边形面积(m²) */
  area_m2?: number
  /** 欠采样：格数过少，边界为包围盒近似 */
  undersampled: boolean
  /** 判定网格形态（当前 square，阶段2 切换 H3 后可为 hex） */
  grid: string
  /** 本几何 schema 版本 */
  schema_version: number
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
  /* ── rev2 · D-3「证据不足必须影响结论」──
     可选同理（旧快照与离线骨架没有）；读法一律走 `confidenceOf()` 安全取值。 */
  /** 置信度：判定面不完整或证据不完整 ⇒ `limited`（盲区数偏乐观、扣分已按覆盖率外推） */
  confidence?: 'full' | 'limited'
  /** 扣分口径的证据链：`penalty_applied` 必须能由 (盲区数, judged_share) 复算 */
  evidence?: {
    judged_share: number | null
    expected_blindspots: number
    penalty_applied: number
  }
}

/** 生活圈体检报告主体（挂载到 Report.living_circle） */
/**
 * 降级标记（后端 `degrade_policy.degraded_block()` 唯一产出；R-7）
 *
 * - **存在即降级**：`data_origin='offline'` 且本节点存在 ⇒ 是「想实时采集但被熔断」；
 *   不存在 ⇒ 只是「未联网 / 无 AK」那一类离线估算。两者对用户的意义完全不同。
 * - `reason` 是**机器用的闭集**（当前仅 `baidu_quota_exhausted`），**不要拿它做文案**；
 *   用户可见归因一律走 `detail`（前端 `degradeDetailLabel()` 与后端 `detail_label()` 同一张表）。
 */
export interface LifeCircleDegraded {
  reason: string
  detail?: string
  note?: string
}

export interface LivingCircleReport {
  scene: LifeCircleScene
  generated_at: string
  /**
   * 数据来源（v2 扩展）：
   * - live=真实百度 API 计算；offline=离线估算（距离模型，未联网 POI，评分不可比）；
   * - fixture_sample=内置演示数据；cache 命中时保持原值 + served_from='cache'
   */
  data_origin: 'live' | 'offline' | 'fixture_sample'
  /**
   * 缓存命中标识（无 AK 时返回历史实时结果）：
   * - cache=精确命中（同中心 30 天）；nearby_cache=邻近命中（原中心距此 ≤500m，v5 O1/D9）
   */
  served_from?: 'cache' | 'nearby_cache'
  /** 缓存命中时间（ISO） */
  cached_at?: string
  /** R-7：降级标记（存在即降级）。文案请走 `degradeDetailLabel()`，不要在消费点自己 switch。 */
  degraded?: LifeCircleDegraded
  /** R2/R6：测算口径举证对象（出行方式、速度、绕行系数等） */
  caliber?: {
    travel_mode: string
    speed_m_per_min: number
    detour_k: number
    study_radius_m: number
    iso_minutes: number[]
    basis: string
    measured: boolean
    sample_profile: string
    note?: string // 离线估算时附加说明
    /* ── 空间口径三概念（可达区 / 采集区 / 研究区）的显式举证 ──
       修复「四个名字三个概念零个表示」后新增：没有这几个数，前端就无法诚实回答
       「盲区为什么这么少」——`cells_unknown` 占比高时必须说明「判不了」而不是「没问题」。 */
    /** 可达区口径分钟数（= reach_full_min，通常 20） */
    reach_full_min?: number
    /** 可达区半径**理论下界** = 分钟 × 速度 ÷ 绕行系数（量级校验用） */
    reach_radius_bound_m?: number
    /** 可达区外接圆半径（**实测**最大顶点距中心距离） */
    reach_circumradius_m?: number
    /** 实际 POI 采集半径（= 外接圆 + collect_margin_m） */
    collect_radius_m?: number
    /** 采集半径相对外接圆的余量（D2=0 严格不外扩；D1=1000 判定覆盖 100%） */
    collect_margin_m?: number
    /** 可达区内的网格格数 */
    cells_inside?: number
    /** 其中**可判定**的格数（1km 邻域被采集区完整覆盖） */
    cells_judged?: number
    /** 其中**不可判定**的格数（数据不足，既不算有盲区也不算没盲区） */
    cells_unknown?: number
    /* ── rev2 · 证据相（「实际查到哪儿」与「请求了多大」并列可查）──
       全部可选：判盲口径升级**前**冻结的快照与离线骨架不带这些键。前端一律经
       `lib/livingCircle.ts` 的安全取值读，**不得**无条件解构 —— 否则演示链（内嵌夹具
       走的就是旧快照）会当场崩。缺键本身是信息：`staleCaliberNotice()` 据此给陈旧提示。 */
    /** 判盲空间口径版本号（当前 `ev-1`）；缺 ⇒ 升级前的旧报告 */
    scope_policy_version?: string
    /** 采集证据余量 = 判定半径（由「判盲需要 1km 完整证据」导出，不是可填的名义值） */
    evidence_margin_m?: number
    /** **实测**证据边界（登记类逐类边界的最小值）；null ⇒ 本次没绑定实测证据 */
    evidence_radius_m?: number | null
    /** 逐类实测证据边界（菜市场 / 药店 / 小学各自查到哪儿） */
    evidence_frontier_m?: Record<string, number>
    /** 证据是否完整（false = 有词被单页截断 / 预算饿死 / 熔断） */
    evidence_complete?: boolean
    /** 证据边界的来源：`measured` 实测 / `unbound_geometric_fallback` 退回几何口径 */
    evidence_bound_source?: string
    /** 可判定半径 = 证据边界 − 判定半径（超出它的格只能标未判定） */
    judge_radius_m?: number
    /** 被单页上限截断的检索词（发了请求但没查全） */
    evidence_truncated_terms?: string[]
    /** 被预算拒绝、一次都没发的检索词（连边界都没有）—— 与截断**不是同一种缺陷** */
    evidence_starved_terms?: string[]
  }
  isochrones: IsochroneZone[]
  sampling: {
    points: SamplingPoint[]
    /** 等时圈生成方式：idw=采样点反距离加权插值；circular_approx=距离模型/圆形近似 */
    interpolation: 'idw' | 'circular_approx'
    /** 是否通过了散点扇形/双阶段采样（30% 评分点叙事） */
    is_scattered: boolean
    /**
     * 已测时点数（= `points` 中 `timed` 为真的个数）。**不等于可达数**。
     * 由后端随点集一起下发；旧快照可能缺，缺失时请用 `samplingReach()` 回算，不要自行 filter。
     */
    timed_count?: number
    /** 可达点数（`minutes <= caliber.reach_full_min`）。「可达率」的分子只能是它 */
    in_reach_count?: number
  }
  poi: {
    categories: FacilityCategoryStat[]
    /** **采集口径**（含圈外）：研究范围内检索到的总数 */
    total: number
    /** **可达口径**：`sum(categories[].in_circle)`，恒等于 `points.length`（守恒不变量） */
    in_circle: number
    /** 逐 POI 点位（真实坐标，BMapGL 渲染）；旧快照/降级可能为空数组 */
    points: PoiPoint[]
    /** 截断披露（阶段 1.3）；**历史快照缺此字段** ⇒ 消费方需容忍 */
    truncated?: PoiTruncation
    /** 设施实体归并披露；**归并上线前冻结的快照缺此字段** ⇒ 走 `poiDedupeRuleLabel()` */
    merged?: PoiFacilityMerge
    /** 守恒自检结论（阶段 1.4）；**历史快照缺此字段** ⇒ 走 `poiConservation()` 回算 */
    conservation?: PoiConservationMeta
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
  /** offline 报告为 null（不伪造 0 分），前端显示「离线估算」 */
  total_score: number | null
  blindspot_count: number
  data_origin: 'live' | 'offline' | 'fixture_sample'
  interpolation: 'idw' | 'circular_approx'
  /** R-7(q-3)：历史列表同样要能区分「未联网离线」与「配额熔断降级」 */
  degraded?: LifeCircleDegraded | null
}

/** 全国省市区三级区划（D1 联动选择器；后端 regions 端点仅返回名称树） */
export interface RegionProvince {
  province: string
  cities: {
    name: string
    districts: string[]
  }[]
}

/** 报告分享直达信息（E1） */
export interface LifeCircleShare {
  ok: boolean
  url: string
  title: string
  scene_name: string
}

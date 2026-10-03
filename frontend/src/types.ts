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
  /** 仅当请求带了 source_urls 时返回：入口卫生后的清单（计划 v3 §二 B1）。 */
  sourceUrls?: UserSourceEcho
}

/** 用户指定信源的入口回执：accepted 是**归一化后**的网址，界面要显示这一份而不是用户原样输入。 */
export interface UserSourceEcho {
  accepted: string[]
  /** 超过条数上限被砍掉的条数（不静默丢弃） */
  truncated: number
  /** 被拒条目与其可读原因（非法协议、超长…） */
  rejected: { url: string; reason: string }[]
}

/**
 * 报告级用户指定信源举证块（计划 v3 §二 B5；真相源 `report["user_sources"]`）。
 * summary 的桶名与后端 `audit.USER_SOURCE_COVERAGE_BUCKETS` 逐字一致 —— 前端不另造一套词。
 */
export interface UserSourceSummary {
  total: number
  cited: number
  uncited: number
  unread: number
  blocked: number
  gated_off_query: number
  merged: number
  pending: number
  denominator: number
  /** 分母为 0 时后端发 null（不是 0%，0% 会被读成"一条都没引用"） */
  rate: number | null
}

export interface UserSourceItem {
  uid: string
  url: string
  url_canonical: string
  /** 存储态（collect 写）：只描述"读没读到" */
  state: 'pending' | 'fetched' | 'unread' | 'blocked' | 'gated_off_query' | 'merged'
  /** 派生覆盖桶（audit 算）：与 state 是两套词表，别混用 */
  coverage: 'pending' | 'unread' | 'blocked' | 'cited' | 'uncited'
  reason: string
  evidence_id: string
  group_id: string
  bytes: number | null
  ms: number | null
  cited_by: string[]
}

export interface UserSourceBlock {
  /** 中文标签来自后端注册表下发，前端不再抄一份映射 */
  label: string
  summary: UserSourceSummary
  items: UserSourceItem[]
  note: string
}

/** `GET /api/source-kinds` 下发视图（真相源 backend/app/core/source_type.py）。 */
export interface SourceKindView {
  id: string
  label: string
  in_stats: boolean
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
  | 'user_source'
  | 'progress'
  | 'trace'
  | 'round'
  | 'report_ready'
  | 'done'
  | 'error'

/** 一趟取证判定的逐条账目 —— 后端 `ForensicRoundRecord.to_row()` 的**唯一**前端镜像。
 *  为什么只留这一份：同一个行对象既从 `round` 事件发出、又落进
 *  `caliber.forensic.rounds_detail[]`（两处由同一个函数产），若前端也声明两份，
 *  上屏与落库就会各自漂移 —— 正是本片要消灭的那类分家。 */
export interface ForensicRoundRow {
  pass_no: number
  dispatched: boolean
  calls: number
  pool_remaining: number
  anchors_planned: number
  anchors_sent: number
  anchors_used: number
  anchors_merged: number
  anchors_not_run: number
  anchors_dropped: number
  starved_terms: number
  points_added: number
  cells_undecided_before: number
  cells_blind_before: number
  cells_undecided_after: number | null
  cells_blind_after: number | null
  asking: string[]
  stopped_by: string | null
  per_category: Record<string, {
    reason: string
    stride: number
    cells_uncovered: number | null
    anchors_total: number
    anchors_dropped: number
    exhausted_min_m: number | null
  }>
}

/** `round` 事件载荷（生活圈取证回合，计划 v7.0 片 4）：一个扩容回合花了多少额度、买回几格结论。
 *  刻意**不**复用 `trace`：那个名字在 research 侧有一个已定的 `TraceSpan` 形状（prompt/tokens…），
 *  在同一事件名下挂第二种载荷 = 让两个链路各自演进时互相撞坏。
 *  ⚠️ 上屏文案取事件自带的 `text`（后端 `pipeline/living_circle.py` 的 STEP_ROUND 分支是唯一
 *  措辞出处），前端**不重排句子** —— 否则同一件事两处各说一遍。 */
export interface ForensicRoundEvent {
  stage?: string
  text?: string
  round: ForensicRoundRow
}

/** `user_source` 事件载荷：用户指定网址的逐条读取进度与终态（计划 v3 §二 F1/B2）。
 *  后端先发自 `state:'reading'`，同一条 uid 随后发终态；前端按 uid upsert（不是追加），
 *  否则列表会随返工轮越滚越长。 */
export interface UserSourceEvent {
  id: string
  url: string
  index: number
  total: number
  state: 'reading' | UserSourceItem['state']
  reason?: string
  evidence_id?: string
  bytes?: number
  ms?: number
  ts?: string
}

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
  /** 用户指定信源举证块（计划 v3 §二 B5）：仅带清单的任务有；与 audit_review 同级 */
  user_sources?: UserSourceBlock
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
  /** 库内「用户指定」类证据条数（后端 _agg_compute 恒发，无则 0） */
  user_source_evidence: number
  /** 口径变动说明行：仅当分布里真含用户指定信源时非空（degradeDisclosure 同源纪律） */
  distribution_note: string
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
  /** 这条订阅的**用户指定信源清单**（计划 v3 §二 B8）：复跑必须带同一份，
   *  否则第二次跑出的报告不含用户钉的文档，两次口径不可比而界面看不出差别。
   *  后端恒发数组（旧库该列为 NULL 也回落成 []），故为必填。 */
  source_urls: string[]
  /** 仅 POST 那次返回：入口卫生回执（accepted/truncated/rejected），与建任务响应同形状 */
  sourceUrls?: UserSourceEcho
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
export type PrefValue = string | number | boolean | string[]
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
  /** 覆盖度 0-1 = `min(1, 分子 / 该类理想阈值)`。分子**看口径**（`cov-1`）：
   *  建了子类表的类别取 `required_in_circle`（门槛项数），没建表或旧快照取 `in_circle`（点数）。
   *  ⚠️ 旧注释"圈内数/理想阈值"只描述了后一种，别让下一个读它的人按点数推风险面。 */
  coverage: number
  /** `cov-1`：覆盖度的**分子**（门槛项数），由后端随 coverage 一起算好。
   *  `null` = 这一类没建子类表 ⇒ 没有门槛项口径可言，**展示侧不得印成 0**；
   *  键整个缺席 = 本字段上线前冻结的历史快照 ⇒ 按点数口径解释 coverage。
   *  ⚠️ 前端**不许**拿点位名自己重判子类来凑这个数 —— 判类只有一份实现，在后端。 */
  required_in_circle?: number | null
  /** `cov-1` 甲档（片 1c-β C1）：门槛项**名单**（计入覆盖度分子的那一组子类名），由后端
   *  `category_rule.sub_kind_rule_labels` 现取。⚠️ 它是**规则名单**，不是"这批圈内采到了哪些"：
   *  凯里圈内 25 处医疗点里 `pharmacy` 实测 0 颗，按 present-only 出名单会让"药店"从披露里消失
   *  （而药店正是盲区三要素之一）。
   *  `null` = 这一类没建子类表；键整个缺席 = 名单上线前冻结的快照 ⇒ 那句说明**不出现**。 */
  scored_as?: string[] | null
  /** 不计入分子的那一组子类名（三档语义同 `scored_as`；`诊所、医院不计入分子` 那句的来源） */
  unscored_as?: string[] | null
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
  /** `cov-1`：这颗点**自己**的子类键（如 `primary` / `pharmacy` / `clinic`），由后端
   *  `poi.to_points` 落盘，且判的是 `annotate_name` **之前**的原始名（否则被吸收子点会替父点决定子类）。
   *  `null` = 该类别没建子类表；键整个缺席 = 本字段上线前冻结的旧快照 ⇒ 该类按点数口径解释覆盖度。
   *  ⚠️ 展示侧只许念，不许据 `name` 重判 —— 判类实现全仓只有一份，在后端。 */
  sub_kind?: string | null
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

/**
 * **部分完成**标记（后端 `degrade_policy.partial_block()` 唯一产出；计划 v7.0 片 4）。
 *
 * - 与 `degraded` 不是一回事：`degraded` 说「这份换成了离线骨架」，`partial` 说
 *   「这份仍是实时口径，只是有些格/类没查到」。D1① 定的是取证阶段被切断**不降级**，
 *   所以前端绝不能把两者并进同一个横幅（那会把"按计划只打了这么多"说成事故）。
 * - `detail` 与 `degraded.detail` 共用同一张归因表（`degradeDetailLabel()`），
 *   但**成因族不同**：这里可能是 `forensic_pool_short`（额度不足），也可能是熔断族
 *   （取证那一格被闸掐住）。文案分支见 `lib/livingCircle.partialBanner()`。
 */
export interface LifeCirclePartial {
  stage: string
  detail: string
  note: string
}

/** 一个证据圆盘（后端 `EvidenceDisc`，由 `TermEvidence.as_disc()` 这一处转换）。
 *  `exhausted_radius_m` 才是"实际查到哪儿"：查全时=请求半径，被截断时=最远实测点。 */
export interface EvidenceDisc {
  category: string
  anchor: [number, number]
  request_radius_m: number
  exhausted_radius_m: number
  complete: boolean
  cap_hit: boolean
  /** 完整性/封顶的**出处**；`null` = 合成盘（从标量边界反推，按定义不自称查全） */
  stop_reason: string | null
}

/** 取证回合总账（`caliber.forensic`，后端 `data_source.forensic_block()` 唯一构造点）。
 *  **缺席即"这次没走取证阶段"**（离线估算与夹具）⇒ 前端不得回落成 `rounds: 0` 去举证。 */
export interface ForensicAccount {
  rounds: number
  judging_passes: number
  max_rounds: number
  stop_reason: string | null
  pool_total: number
  pool_used: number
  pool_remaining: number
  anchors_planned: number
  anchors_sent: number
  anchors_used: number
  anchors_merged: number
  anchors_not_run: number
  anchors_dropped: number
  calls: number
  /** 补算回来的点位只进判盲、不进评分与展示计数（两面性的显式声明） */
  points_added_judging_only: number
  points_policy: string
  /** 「现在为什么停」的逐类读数（取最后一趟）；历史流水在 `rounds_detail` */
  per_category: ForensicRoundRow['per_category']
  rounds_detail: ForensicRoundRow[]
}

/** 逐格判定台账（`caliber.cells_ledger`，契约 B13）。形状与后端
 *  `blindspot.render_cells_ledger` 逐字对齐，两侧由 `cellsLedgerContract.json` 同钉：
 *
 *  - 十张 `n×n` 矩阵是**行字符串**（行沿 y、列沿 x），字母表只有 `1` / `0` / `.`；
 *  - 三张 `nearest.{类}` 是空格分隔的 `n` 个记号，`-` = 无从知道，其余是整米数。
 *
 *  ⚠️ `.` 不是 `0`：它表示「这一类的 1km 判定圆没被证明查全」，即**没查过**。把两者合并
 *  就等于让报告重犯「判不了冒充不盲」—— 那正是 `ev-1` 整套改造要消灭的形状。
 *  缺整个键 ⇒ 这份报告出自逐格台账上线之前（`ev-2` 前）或离线骨架 ⇒ 格级图层不出现，
 *  一律经 `cellsLedgerOf()` 取值（它返回 `null`，不猜、不抛）。 */
export interface CellsLedgerRaw {
  grid: string
  schema_version: number
  n: number
  step_m: number
  scan_m: number
  /** 本次判定实际吃的那把尺（米）。**不许**在前端写回 1000 —— 多模式分档后它不是常量。 */
  radius_m: number
  center: [number, number]
  inside: string[]
  capped: string[]
  blind: string[]
  verdict: string[]
  'judge.market': string[]
  'judge.pharmacy': string[]
  'judge.primary': string[]
  'present.market': string[]
  'present.pharmacy': string[]
  'present.primary': string[]
  'nearest.market': string[]
  'nearest.pharmacy': string[]
  'nearest.primary': string[]
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
  /** 片 4/5：部分完成标记（存在即"有格/类没查到"，**不是**降级）。文案走 `partialBanner()`。 */
  partial?: LifeCirclePartial
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
    /** 其中因**接口自有上限**（服务端自称还欠一整页却断了货）而判不动的格数。
     *  与 `cells_unknown` 分名分职：那一位是「我们没查到」，这一位是「再多的额度也拿不到」。
     *  分账恒等式 `cells_inside = cells_judged + cells_unknown + 这一位`。
     *  ⚠️ 可选：第三态落地前冻结的快照与离线骨架不带 ⇒ 读侧必须 `?? 0`，不得无条件解构。 */
    cells_unjudgeable_by_cap?: number
    /* ── rev2 · 证据相（「实际查到哪儿」与「请求了多大」并列可查）──
       全部可选：判盲口径升级**前**冻结的快照与离线骨架不带这些键。前端一律经
       `lib/livingCircle.ts` 的安全取值读，**不得**无条件解构 —— 否则演示链（内嵌夹具
       走的就是旧快照）会当场崩。缺键本身是信息：`staleCaliberNotice()` 据此给陈旧提示。 */
    /** 判盲空间口径版本号（当前 `ev-2` = 追加逐格台账）；缺 ⇒ 升级前的旧报告 */
    scope_policy_version?: string
    /** **第二根轴**：评分口径版本号（当前 `cov-1` = 覆盖度分子由点数改成门槛项数）。
     *  它与上面那把管的是两件事（"证据怎么查" vs "同样的点位算什么分"），所以独立命名、
     *  独立取值 —— 拿 `ev-*` 表达评分变化等于在版本记录上撒谎。
     *  缺 ⇒ 这份产物的分数是**点数口径**算的；读侧只能按旧定义解释覆盖度，
     *  不得挂"门槛项"那句新文案（后端 `reuse_policy` 的「评分口径」那一拦用的就是这把键）。 */
    coverage_caliber_version?: string
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
    /** 被单页上限截断 / 收益止损收页的检索词（发了请求、**我们没接着翻完**）。
     *  ⚠️ R23-D 起这一位**不再混装**接口断页与请求没成 —— 那两种各归下面两位。 */
    evidence_truncated_terms?: string[]
    /** 被预算拒绝、一次都没发的检索词（连边界都没有）—— 与截断**不是同一种缺陷** */
    evidence_starved_terms?: string[]
    /** **接口自称还有货却断了页**的检索词（R23-D）。与 truncated 的分界是"再加预算有没有用"：
     *  截断是我们没接着翻，本位是百度不给 ⇒ 归责不同，不许并成一句。
     *  ⚠️ 缺键 = 这份报告出自 R23-D 之前，读作"不知道"，**不得**当成"没有词被接口断页"
     *  （那时它们混在 `evidence_truncated_terms` 里，事后无法重算 —— 两份演示件都没有逐词明细）。 */
    evidence_capped_terms?: string[]
    /** **请求没成**（没发出去或返回失败）的检索词（R23-D）。与 truncated 的分界是"知道多少"：
     *  截断是知道一部分、边界外还有货，本位是一无所知 ⇒ 说成"发了但没查全"就是假话。
     *  ⚠️ 缺键同上，读作"不知道"。 */
    evidence_failed_terms?: string[]
    /** **整轮没跑过扩词**的类别（R23-B1）。与上面两条分职：starved 指得出一个被拒的**词**，
     *  这里连词都没被推导出来（额度在别的类上花完了）⇒ 只能报到**类**这一级。
     *  ⚠️ 缺键 = 这份报告出自 R23-B1 之前，读作"不知道"，**不得**当成"没有类别被落下"。 */
    evidence_expansion_unfunded_categories?: string[]
    /** **扩过词、却在本类额度见底时仍未达标**的类别（R23-B3）。与上一条的分界是"跑没跑过"：
     *  unfunded 是排程没摊到，本条是摊到了但额度太薄 ⇒ 读者的判断不同，前端也不合并。
     *  ⚠️ 缺键 = 这份报告出自 R23-B3 之前，读作"不知道"，**不得**当成"没有类别扩到一半停了"。 */
    evidence_expansion_out_of_budget_categories?: string[]
    /** 上面四种成因（不含 `capped`）的**类别并集** = "这一类的覆盖度分子没查够"。
     *  后端一处算出（`CollectionEvidence.coverage_numerator_incomplete`），给机器读；
     *  人读的那句「另需交代…」仍按成因各说各的 ⇒ 两者必须同步，由关系判据钉住。
     *  ⚠️ 缺键 = 这份报告出自本位之前，读作"不知道"，**不得**当成"每类都查够了"。 */
    coverage_numerator_incomplete_categories?: string[]
    /* ── 片 4/5 · 逐锚点举证与取证账目 ──
       两把尺并存这件事要说清：上面那批 `evidence_*` **标量**仍是旧口径（批次二才收敛），
       而下面这两块是逐盘/逐趟的明细 —— 由 `scope.payload(judged_region=/forensic=)` 跟着
       **判定真正吃的那块区域**发射。读侧任何一处拿标量去否证明细，都会得出反向结论。 */
    /** 判定吃的那块证据域的逐盘明细；缺 ⇒ 旧快照没发过（不是"没有盘"） */
    evidence_anchors?: EvidenceDisc[]
    /** 取证回合账目；**缺 ⇒ 这次根本没走取证**（离线/夹具），不得回落成 `rounds: 0` */
    forensic?: ForensicAccount
    /** 逐格判定台账（契约 B13）；**缺 ⇒ 这份报告早于 `ev-2`** 或来自离线骨架
     *  ⇒ 格级图层与逐格卡都不出现，经 `cellsLedgerOf()` 取，取不到就是 `null`（不猜、不抛） */
    cells_ledger?: CellsLedgerRaw
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

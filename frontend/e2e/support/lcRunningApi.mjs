/**
 * 体检进行中（真实模式）那屏所需的最小后端 —— 只给 e2e 用。
 *
 * ## 为什么必须是个真服务器，而不是 `page.route`
 *
 * 那块横幅的条件是 `!isFixture && runActive`，而 `runActive` 读的是 `taskRegistry` 里
 * `status === 'running'`（`LifeCirclePage.tsx:157`）。注册表其实**不需要**任何注入：
 * `subscribeLifeCircleTask` 第一件事就是 `seedRegistry(taskId)` 写 running
 * （`src/lib/lifeCircleFlow.ts:138`）。
 *
 * 真正卡住的是传输层：Playwright 的 `route.fulfill` 只能一次性给完 body，
 * 连接随即关闭 ⇒ 客户端 `onError` 触发 `markFailed` ⇒ 横幅刚挂上就被卸载。
 * 所以"任务停在 running"这件事**没法靠 mock 一个响应体伪造**，只能有一个真会
 * 保持打开的 SSE。这里就是那个 SSE —— 它不替代任何业务逻辑，
 * 页面走的仍是生产那条 `createLivingCircleTask → subscribeLifeCircleTask → registry` 链。
 *
 * ## 它只回答四件事
 *
 *  - `POST /api/tasks` → `{taskId}`（**camelCase**；写成 `task_id` 会得到「创建体检任务失败（HTTP 200）」）
 *  - `GET  /api/tasks/:id/stream` → progress / message / 5 个 round，然后**挂着不断**（心跳）
 *  - `GET  /api/life-circle` → 一条历史体检记录（横幅住在报告分支里，见下方 RECORD 注释）
 *  - `GET  /api/life-circle/{id}` → 那份 fixture 报告本体
 *  - `GET  /api/tasks/{id}/status` → running 快照（浮动条会轮询它）
 *  - `GET  /api/life-circle/map-config` → 空 AK ⇒ 地图走降级画布，几何照样量，且不依赖外网
 *
 * 其余一律 404：页面这些请求失败时本来就有降级（fixture 那批用例就是这么跑的）。
 */
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'

/**
 * 历史报告直接复用仓里那份 fixture（`src/mocks/fixtures/livingCircle/kaili-ev2.json`）——
 * 单一来源，不再抄一份会漂移的副本。
 *
 * 为什么必须有一份：那块横幅住在**报告分支**里（`LifeCirclePage.tsx:627`），
 * 而真实模式下若 `GET /api/life-circle` 返回空列表，页面只渲染「还没有体检记录」那一屏，
 * **两栏舞台根本不存在**（实测：`main [class*="lg:grid-rows-"]` 计数 0），
 * 那"横幅压不压塌舞台"就无从测起。所以这里给一条"上次体检已有记录"的历史态。
 */
const LIVING_CIRCLE = JSON.parse(
  readFileSync(new URL('../../src/mocks/fixtures/livingCircle/kaili-ev2.json', import.meta.url), 'utf8'),
)
const REPORT_ID = 'lc-e2e-kaili'
const RECORD = {
  id: REPORT_ID,
  title: `${LIVING_CIRCLE.scene.name} · 15 分钟生活圈体检`,
  scene_name: LIVING_CIRCLE.scene.name,
  city: LIVING_CIRCLE.scene.city,
  checked_at: LIVING_CIRCLE.generated_at ?? '2026-10-04T00:00:00Z',
  total_score: LIVING_CIRCLE.scores?.total ?? null,
  blindspot_count: (LIVING_CIRCLE.blindspots ?? []).length,
  data_origin: 'live',
  interpolation: 'idw',
}

const PORT = Number(process.env.LC_E2E_API_PORT ?? 8799)
const TASK_ID = process.env.LC_E2E_TASK_ID ?? 'lc-e2e-1'
const ROUNDS = Number(process.env.LC_E2E_ROUNDS ?? 5)

/**
 * 回合数可由测试临时改：`GET /api/e2e/rounds?n=12`。
 * 为什么要能改 —— 横幅的限高是 `lg:max-h-[22vh]`，5 行在 720 档约 150px，**还没顶到上限**，
 * 那"有界"这条主张就没被真的压到。加到 12 行才能逼出内部滚动：那时若有人摘掉 `max-h`，
 * 横幅会把地图格与右栏一起压塌，本 mock 的第二条用例立刻红。
 */
let rounds = ROUNDS
/** 由 `/api/e2e/records?on=0` 置真 ⇒ 历史列表返回空数组，让页面停在「无记录」CTA 行。
 *  两个 CTA 挂载点（有记录态头部行 / 无记录态首屏行）都得被真浏览器量到，否则只测一半。 */
let noRecords = false

const sse = (type, data) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`

/** 一轮取证回应的载荷：字段就是页面会读的那几个（后端是唯一措辞出处，text 原样上屏） */
function roundRow(i) {
  return {
    round: {
      pass_no: i + 1,
      dispatched: i % 2 === 0,
      pool_remaining: 32 - i * 4,
      anchors_dropped: i === 2 ? 1 : 0,
      calls: 1,
      anchors_sent: 1,
      anchors_used: 1,
    },
    text: `取证扩容 · 第 ${i + 1} 轮：药店在 6 格未覆盖，派 1 个锚点补采`,
  }
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

/** 事件序列：一条一条发，让页面真的经历"横幅逐行长高"的过程
 *
 *  `expert` 这一位是 **C2 之后后端实发的形状**（`app/living_circle/seat_registry.STAGE_SEAT`
 *  按 stage 决议，`_progress()` 统一注入）：每条 progress 都带自己那一步的负责席位。
 *  刻意用**真阶段名**（collect / diagnose）—— 上一版这里写的是 `analyze`，它根本不在
 *  `living_circle.STAGES` 里，前端 `stageLabel()` 拿不到中文名只能原样印，
 *  于是"横幅席位随阶段换人"这条主张在 e2e 里没法被真实地断言。
 *  值只在本 mock 内部当"已知输入"用；用例断言的是"行出现且含这一位"，不写死人名
 *  （CI 的 mock 未桩 `/api/experts`，页面会回落到静态册 `/assets/experts/living_circle.json`，
 *  与生产取数不同路径 —— 写死人名会让静态册漂移误伤这条用例）。 */
function streamSteps(n) {
  return [
    // 后端 plan 阶段现在会发一条 `kind:'team'` 的 message（携带成员与降级码）。
    // 这里给一帧**降级态**，让"横幅要把这件事留在屏上"这条真实链路进 e2e：
    // 走的是生产 `lifeCircleFlow.onFlowEvent` → `onTeam` → `LifeCirclePage` 那一行。
    [0, sse('message', {
      stage: 'plan',
      kind: 'team',
      members: ['L3-001', 'L3-002', 'L2-001', 'L2-002', 'L2-004', 'L1-025', 'L1-030', 'L1-027', 'L1-032'],
      degraded: 'llm_error',
      text: '本次专家队由保底名单编排（llm_error），未经模型按场景挑选',
    })],
    [0, sse('progress', { stage: 'collect', percent: 24, expert: 'L1-030' })],
    [120, sse('message', { text: '采集圈内 POI 与采样点' })],
    ...Array.from({ length: n }, (_, i) => [240 + i * 160, sse('round', roundRow(i))]),
    [240 + n * 160, sse('progress', { stage: 'diagnose', percent: 82, expert: 'L1-032' })],
  ]
}

function openStream(req, res) {
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
    'x-accel-buffering': 'no',
  })
  res.write(': e2e running mock\n\n')
  const timers = streamSteps(rounds).map(([delay, chunk]) => setTimeout(() => res.write(chunk), delay))
  // 关键就这一句：发完不收尾。任务必须停在 running，横幅才会在测量期间一直挂着。
  const beat = setInterval(() => res.write(': ping\n\n'), 1000)
  const stop = () => {
    timers.forEach(clearTimeout)
    clearInterval(beat)
  }
  req.on('close', stop)
  res.on('error', stop)
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', `http://127.0.0.1:${PORT}`)
  const path = url.pathname

  if (req.method === 'GET' && path === '/api/e2e/rounds') {
    const n = Number(url.searchParams.get('n'))
    if (!Number.isInteger(n) || n < 1 || n > 40) return json(res, 400, { detail: 'n 要是 1..40 的整数' })
    rounds = n
    return json(res, 200, { rounds: n })
  }
  if (req.method === 'GET' && path === '/api/e2e/records') {
    const on = url.searchParams.get('on')
    if (on !== '0' && on !== '1') return json(res, 400, { detail: 'on 只接 0/1' })
    noRecords = on === '0'
    return json(res, 200, { noRecords })
  }
  // 只读回显当前全局态：给用例做**开头前置断言**用（Playwright 的 context 隔离管不到
  // 服务端进程级变量，上一批"整批读数全同"就是这么来的）。
  if (req.method === 'GET' && path === '/api/e2e/state') return json(res, 200, { noRecords, rounds })
  if (req.method === 'POST' && path === '/api/tasks') return json(res, 200, { taskId: TASK_ID, kind: 'life_circle' })
  if (req.method === 'GET' && path === `/api/tasks/${TASK_ID}/stream`) return openStream(req, res)
  // 浮动条会轮询任务状态；不给它会拿到 404（虽然前端有兜底，但那是另一条链路，别混进这条用例）
  if (req.method === 'GET' && path === `/api/tasks/${TASK_ID}/status`) {
    // 与上面最后一帧**同一个阶段**：悬浮条每 3s 轮这个端点并把 stage/percent 写回 registry
    // （`TaskFloatBar.tsx:43-49` 是脱离 SSE 的兜底），两边不一致时屏上会看见阶段倒回去。
    return json(res, 200, {
      status: 'running', percent: 82, stage: 'diagnose', evidence_count: 0,
      report_id: null, started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    })
  }
  if (req.method === 'GET' && path === '/api/life-circle') return json(res, 200, noRecords ? [] : [RECORD])
  if (req.method === 'GET' && path === `/api/life-circle/${REPORT_ID}`) {
    return json(res, 200, { id: REPORT_ID, report_type: 'living_circle', living_circle: LIVING_CIRCLE })
  }
  if (req.method === 'GET' && path === '/api/life-circle/regions') return json(res, 200, [])
  if (req.method === 'GET' && path === '/api/life-circle/map-config') {
    return json(res, 200, { browser_ak: '', map_style_id: '' })
  }
  return json(res, 404, { detail: `lc-e2e-mock: 未桩的路径 ${req.method} ${path}` })
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[lc-e2e-mock] http://127.0.0.1:${PORT} （taskId=${TASK_ID}, rounds=${ROUNDS}）`)
})

/**
 * 常青圈 · 信源类别注册表快照生成器（计划 v3 §二 G0 的展示面）。
 *
 * 唯一数据源：后端 GET http://127.0.0.1:8010/api/source-kinds
 * （其本身即 `app/core/source_type.py` 的 `kind_view()`，由后端
 *  test_user_source_stats_and_labels.py 钉住逐字段一致）。
 *
 * 产物：src/mocks/sourceKinds.json —— 演示态/离线时信源标签的回落数据。
 * **不要手抄、不要手改**；改注册表后：
 *   1) 启动后端（./start.sh 或 backend/.venv/bin/python -m uvicorn ... :8010）
 *   2) node scripts/gen-source-kinds-fixture.mjs
 * 形状由 src/__tests__/sourceKindsClient.test.ts 自测；类别集合变化时本脚本会拒绝覆写
 * （需 --force），避免把"注册表少了/多了一类"当成一次无感的快照刷新。
 */
import { writeFileSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../src/mocks/sourceKinds.json')
const BACKEND_PORT = process.env.BACKEND_PORT ?? '8010'
const ENDPOINT = process.env.SOURCE_KINDS_URL ?? `http://127.0.0.1:${BACKEND_PORT}/api/source-kinds`

async function main() {
  let items
  try {
    const r = await fetch(ENDPOINT)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json()
    items = data?.kinds
  } catch (e) {
    console.error(
      `[gen-source-kinds-fixture] 拉取失败：${ENDPOINT}\n` +
      `  ${e?.message ?? e}\n` +
      '  请先启动后端（端口 8010）后重试。本脚本不接受手工编造的快照。',
    )
    process.exit(1)
  }

  if (!Array.isArray(items) || items.some((x) => !x.id || !x.label || typeof x.in_stats !== 'boolean')) {
    console.error('[gen-source-kinds-fixture] 端点载荷形状非法（需 {kinds:[{id,label,in_stats}]}），终止。')
    process.exit(1)
  }

  let prev = null
  try {
    prev = JSON.parse(readFileSync(OUT, 'utf-8'))
  } catch {
    /* 首次生成无旧文件 */
  }
  if (prev && !process.argv.includes('--force')) {
    const prevIds = new Set((prev.kinds ?? []).map((x) => x.id))
    const nextIds = new Set(items.map((x) => x.id))
    const removed = [...prevIds].filter((k) => !nextIds.has(k))
    const added = [...nextIds].filter((k) => !prevIds.has(k))
    if (removed.length || added.length) {
      console.error(
        `[gen-source-kinds-fixture] 类别集合发生变化（+${added.join(',') || '无'} / -${removed.join(',') || '无'}）。\n` +
        '  若为注册表有意变更，确认后带 --force 重新生成；否则勿动。',
      )
      process.exit(2)
    }
  }

  const payload = {
    _generated_by: 'scripts/gen-source-kinds-fixture.mjs',
    _source: 'GET /api/source-kinds（真相源 backend/app/core/source_type.py；勿手改）',
    _generated_at: new Date().toISOString(),
    kinds: items,
  }
  writeFileSync(OUT, JSON.stringify(payload, null, 2) + '\n', 'utf-8')
  console.log(`[gen-source-kinds-fixture] 已写入 ${OUT}（${items.length} 个类别）`)
}

main()

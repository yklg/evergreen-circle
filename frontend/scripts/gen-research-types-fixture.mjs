/**
 * 常青圈 · 调研类型注册表快照生成器。
 *
 * 唯一数据源：后端 GET http://127.0.0.1:8010/api/research-types
 * （其本身又与 app/core/research_types.py 注册表逐字段一致，由后端
 *  test_research_types_api.py 钉住）。
 *
 * 产物：src/mocks/researchTypes.json —— 演示态/离线时首页类型卡（C1/C2）的
 * 回落数据。**不要手抄、不要手改**；改注册表后：
 *   1) 启动后端（./start.sh 或 backend/.venv/bin/python -m uvicorn ... :8010）
 *   2) node scripts/gen-research-types-fixture.mjs
 * 契约一致性由 src/__tests__/researchTypesClient.test.ts 的形状自测 +
 * 后端在线时的逐字段对比测试守卫。
 */
import { writeFileSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../src/mocks/researchTypes.json')
const ENDPOINT = process.env.RESEARCH_TYPES_URL ?? 'http://127.0.0.1:8010/api/research-types'

async function main() {
  let items
  try {
    const r = await fetch(ENDPOINT)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    items = await r.json()
  } catch (e) {
    console.error(
      `[gen-research-types-fixture] 拉取失败：${ENDPOINT}\n` +
      `  ${e?.message ?? e}\n` +
      '  请先启动后端（端口 8010）后重试。本脚本不接受手工编造的快照。',
    )
    process.exit(1)
  }

  if (!Array.isArray(items) || items.some((x) => !x.key || !x.label || !x.subtitle)) {
    console.error('[gen-research-types-fixture] 端点载荷形状非法（需 [{key,label,subtitle}]），终止。')
    process.exit(1)
  }

  // 防覆写：旧快照若带有与本注册表无关的手改痕迹（额外字段/未知 key），先人工确认。
  let prev = null
  try {
    prev = JSON.parse(readFileSync(OUT, 'utf-8'))
  } catch {
    /* 首次生成无旧文件 */
  }
  if (prev && !process.argv.includes('--force')) {
    const prevKeys = new Set((prev.types ?? []).map((x) => x.key))
    const nextKeys = new Set(items.map((x) => x.key))
    const removed = [...prevKeys].filter((k) => !nextKeys.has(k))
    const added = [...nextKeys].filter((k) => !prevKeys.has(k))
    if (removed.length || added.length) {
      console.error(
        `[gen-research-types-fixture] 类型集合发生变化（+${added.join(',') || '无'} / -${removed.join(',') || '无'}）。\n` +
        '  若为注册表有意变更，确认后带 --force 重新生成；否则勿动。',
      )
      process.exit(2)
    }
  }

  const payload = {
    _generated_by: 'scripts/gen-research-types-fixture.mjs',
    _source: 'GET /api/research-types（真相源 backend/app/core/research_types.py；勿手改）',
    _generated_at: new Date().toISOString(),
    types: items,
  }
  writeFileSync(OUT, JSON.stringify(payload, null, 2) + '\n', 'utf-8')
  console.log(`[gen-research-types-fixture] 已写入 ${OUT}（${items.length} 个类型）`)
}

main()

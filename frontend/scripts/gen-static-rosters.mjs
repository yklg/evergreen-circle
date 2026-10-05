/**
 * 生成前端静态专家名册（离线/演示态回落用），唯一真相源 = 后端两本名册 JSON。
 *
 * 为什么必须有这个脚本：`public/assets/experts.json` 此前是手工抄进去的，实测已经**整本
 * 漂移** —— 它装的是生活圈人设（48/48 姓名与后端 travel 名册不同，L3-001 静态=温叙白、
 * 后端=沈砚），于是后端不可达时旅游侧专家墙会拿到生活圈那本人设。加上生活圈那条回落路径
 * 指向的 `assets/experts/living_circle.json` 压根不存在（`lib/api.ts:69`），离线态等于
 * 一个域拿错册、另一个域没册可拿。
 *
 * 用法：node scripts/gen-static-rosters.mjs [--check]
 *   无参数 = 写文件；`--check` = 只比对，不一致退出码 1（CI/自检用）。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BACKEND = join(ROOT, '..', 'backend', 'app', 'data')

/** 域名 → [后端源, 前端静态目标]。两两配对，避免"改了一本忘了另一本"。 */
const PAIRS = [
  ['travel', 'experts.json', 'assets/experts.json'],
  ['living_circle', 'experts_living_circle.json', 'assets/experts/living_circle.json'],
]

const check = process.argv.includes('--check')
let drifted = []

for (const [domain, src, dst] of PAIRS) {
  const body = readFileSync(join(BACKEND, src), 'utf8')
  const roster = JSON.parse(body)
  const ids = new Set(roster.map((e) => e.id))
  if (roster.length !== 48 || ids.size !== 48) {
    console.error(`[${domain}] 名册条数/唯一 id 异常：${roster.length} 条 / ${ids.size} 个 id`)
    process.exit(2)
  }
  const target = join(ROOT, 'public', dst)
  const current = existsSync(target) ? readFileSync(target, 'utf8') : null
  const same = current !== null && JSON.stringify(JSON.parse(current)) === JSON.stringify(roster)
  if (check) {
    if (!same) drifted.push(`${domain} → ${dst}`)
    console.log(`${same ? 'ok  ' : 'DIFF'} ${domain.padEnd(13)} ${dst} (${roster.length} 人)`)
    continue
  }
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, JSON.stringify(roster, null, 2) + '\n', 'utf8')
  console.log(`写入 ${dst}：${roster.length} 人（源 backend/app/data/${src}）`)
}

if (check && drifted.length) {
  console.error(`\n静态名册与后端名册不一致：${drifted.join('、')} ⇒ 跑 node scripts/gen-static-rosters.mjs 重新生成`)
  process.exit(1)
}

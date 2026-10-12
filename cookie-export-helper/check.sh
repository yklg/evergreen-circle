#!/usr/bin/env bash
# 常青圈 Cookie 助手 · 静态守卫（提交前自检；可挂 CI）
# 把两类真实事故机器化拦截：
#   ① MV3 扩展页禁止内联脚本（只能外链，CSP script-src 'self'，不可放宽）；
#   ② 单入口约束：本目录只允许 manifest.json / popup.html / popup.js / README.md / check.sh。
# 用法：bash check.sh   （需要本机有 node；仓库开发机与 CI 均有）
# 注：JS 载荷经 heredoc 直喂 `node -`（stdin），**不要**改回 `$(cat <<'JS' …)` 形式——
#     macOS 自带 bash 3.2 对「heredoc 嵌命令替换」有解析缺陷（zsh 不炸，故历史上没暴露）。
set -u
cd "$(dirname "$0")"

exec node - <<'JS'
const { readFileSync, existsSync, readdirSync } = require('node:fs')
const { execFileSync } = require('node:child_process')

let fail = 0
const bad = (m) => { console.log('[FAIL] ' + m); fail = 1 }
const ok = (m) => console.log('[ OK ] ' + m)
const files = readdirSync('.').filter((f) => !f.startsWith('.'))

// ① 单入口白名单
const ALLOW = new Set(['manifest.json', 'popup.html', 'popup.js', 'README.md', 'check.sh'])
for (const f of files) {
  if (!ALLOW.has(f)) bad(`目录出现白名单外文件：${f}（先想清楚"它是不是入口"，再决定去留）`)
}
if (!fail) ok(`单入口白名单（${files.length} 个文件）`)

// ② manifest 合法且 default_popup 指向存在的文件
let manifest = null
try { manifest = JSON.parse(readFileSync('manifest.json', 'utf8')) } catch (e) { bad('manifest.json 非法 JSON：' + e.message) }
if (manifest) {
  if (manifest.manifest_version !== 3) bad('manifest_version 必须为 3')
  const pop = manifest.action && manifest.action.default_popup
  if (pop && existsSync(pop)) ok(`manifest default_popup → ${pop}（v${manifest.version}）`)
  else bad(`default_popup 指向不存在的文件：${pop}`)
}

// ③ 全部 HTML：禁内联 <script> + 本地资源引用存在
for (const f of files.filter((x) => x.endsWith('.html'))) {
  const html = readFileSync(f, 'utf8')
  const tags = [...html.matchAll(/<script\b([^>]*)>/gi)]
  const inline = tags.filter((m) => !/\bsrc\s*=/i.test(m[1]))
  if (inline.length) bad(`${f} 含 ${inline.length} 个内联 <script>（MV3 扩展页禁止内联，只能外链）`)
  else ok(`${f} 无内联脚本（${tags.length} 个外链 script）`)
  for (const m of html.matchAll(/\b(?:src|href)\s*=\s*"([^"]*)"/gi)) {
    const u = m[1]
    if (!u || u.startsWith('#') || /^(https?:|data:|mailto:)/i.test(u)) continue
    if (!existsSync(u)) bad(`${f} 引用了不存在的本地文件：${u}`)
  }
}

// ④ 全部 JS 语法
for (const f of files.filter((x) => x.endsWith('.js'))) {
  try { execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' }); ok(`语法 ${f}`) }
  catch { bad(`语法错误：${f}`) }
}

console.log(fail ? '\n静态守卫未通过 ✗（修正后重跑；提交前必须全绿）' : '\n静态守卫通过 ✓')
process.exit(fail)
JS

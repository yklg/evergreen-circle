// 常青圈 Cookie 助手 · popup 逻辑（v3.0.0 整体重写，2026-10-12）
// 职责：读取当前站点全部 Cookie（含 httpOnly）→ 清洗 → 复制到剪贴板，粘贴到常青圈「平台采集」。
// MV3 纪律：本文件只能由 popup.html 以 <script src="popup.js"> 外链引入——
//   内联 <script> / onclick= / eval 一律被浏览器拒绝且不可放宽（2026-10-12 事故根因）。
'use strict'

// ── 平台名录：core＝登录态核心字段（缺失即疑似未登录）；whitelist＝「仅保留关键字段」清单 ──
const PLATFORMS = [
  { key: 'douyin', label: '抖音', core: 'sessionid',
    whitelist: ['sessionid', 'sid_tt', 'sid_ucp_v1', 'passport_csrf_token', 'odin_tt', 's_v_web_id', 'ttwid'] },
  { key: 'xiaohongshu', label: '小红书', core: 'web_session',
    whitelist: ['web_session', 'a1', 'webId', 'gid'] },
  { key: 'bilibili', label: 'B站', core: 'SESSDATA',
    whitelist: ['SESSDATA', 'bili_jct', 'buvid3', 'DedeUserID'] },
]

const BAD_NAME = /[\s\x00-\x1F\x7F";,=]/
const BAD_VALUE = /[\s\x00-\x1F\x7F";,]/

const $ = (id) => document.getElementById(id)
const siteBox = $('site')
const siteText = $('siteText')
const copyBtn = $('copy')
const forceBtn = $('force')
const onlyKey = $('onlyKey')
const statusBox = $('status')
const verLine = $('ver')

let pending = [] // 「仍要复制」兜底用

const platformOf = (host) => PLATFORMS.find((p) => host.includes(p.key)) || null

// ── Cookie 清洗（保证下游 http.cookiejar / SimpleCookie 能直接消费；规则见 README）──
function sanitize(cookies) {
  const now = Date.now() / 1000
  const byName = new Map()
  let dropped = 0
  for (const c of cookies) {
    const name = c.name == null ? '' : String(c.name).trim()
    const value = c.value == null ? '' : String(c.value)
    if (!name || BAD_NAME.test(name) || (value && BAD_VALUE.test(value))) { dropped++; continue }
    if (c.expirationDate && c.expirationDate < now) { dropped++; continue }
    const prev = byName.get(name)
    if (!prev) { byName.set(name, c); continue }
    const expNew = c.expirationDate || 0
    const expPrev = prev.expirationDate || 0
    if ((!prev.value && value) || expNew > expPrev || expNew === expPrev) byName.set(name, c)
    dropped++
  }
  return { list: Array.from(byName.values()), dropped }
}

function expiryHint(list) {
  const dated = list.filter((c) => c.expirationDate).map((c) => c.expirationDate)
  if (!dated.length) return '会话 Cookie，关闭浏览器即失效'
  const hours = (Math.min(...dated) - Date.now() / 1000) / 3600
  if (hours <= 0) return '存在已过期项，建议重新登录后导出'
  if (hours < 24) return `最早 ${Math.max(1, Math.round(hours))} 小时后过期`
  return `最早 ${Math.round(hours / 24)} 天后过期`
}

const toCookieStr = (list) => list.map((c) => `${c.name}=${c.value}`).join('; ')

// ── UI 小工具 ───────────────────────────────────────────
function setStatus(text, kind, meta) {
  statusBox.textContent = text
  if (meta) {
    const span = document.createElement('span')
    span.className = 'meta'
    span.textContent = meta
    statusBox.appendChild(span)
  }
  statusBox.className = kind // 'info' | 'ok' | 'warn' | 'risk'
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 失焦 / 权限异常时降级 execCommand（原因记在 README「维护与排查」）
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

// ── 当前站点（打开弹窗即显示：「为什么没反应 / 没数据」的第一判据）──
async function readCurrentSite() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    const url = tab && tab.url ? new URL(tab.url) : null
    if (!url || !/^https?:$/.test(url.protocol)) {
      siteText.textContent = '当前标签页不是网页 —— 请切到已登录的抖音 / 小红书 / B站页面再试'
      siteBox.className = 'warn'
      return null
    }
    const plat = platformOf(url.hostname)
    if (plat) {
      siteText.textContent = `当前站点：${url.hostname}（${plat.label} ✓）`
      siteBox.className = 'ok'
    } else {
      siteText.textContent = `当前站点：${url.hostname}（不在支持列表）`
      siteBox.className = 'warn'
    }
    return { url, plat }
  } catch {
    siteText.textContent = '无法读取当前标签页'
    siteBox.className = 'warn'
    return null
  }
}

// ── 复制主流程 ──────────────────────────────────────────
copyBtn.addEventListener('click', async () => {
  forceBtn.hidden = true
  pending = []
  setStatus('正在读取…', 'info')
  try {
    const ctx = await readCurrentSite()
    if (!ctx || !ctx.plat) {
      setStatus('当前页面不在支持列表：请切到已登录的抖音 / 小红书 / B站页面再点。', 'warn')
      return
    }
    const tRead = performance.now()
    const cookies = await chrome.cookies.getAll({ url: ctx.url.origin })
    const tCookies = performance.now()
    if (!cookies.length) {
      setStatus(`该站点（${ctx.url.origin}）没有可用 Cookie —— 通常是还没登录。`, 'warn')
      return
    }
    const { list, dropped } = sanitize(cookies)
    const final = onlyKey.checked ? list.filter((c) => ctx.plat.whitelist.includes(c.name)) : list
    if (!final.some((c) => c.name === ctx.plat.core && c.value)) {
      // 诊断（只列 Cookie 名字，绝不列值）：权限自检 + url/domain 两种读法对照
      const rootDomain = ctx.url.hostname.split('.').slice(-2).join('.')
      let permOk = null
      try {
        permOk = await chrome.permissions.contains({ origins: [`*://*.${rootDomain}/*`] })
      } catch {
        permOk = null
      }
      let domainNames
      try {
        domainNames = (await chrome.cookies.getAll({ domain: rootDomain })).map((c) => c.name)
      } catch (e) {
        domainNames = ['读取失败：' + (e && e.message ? e.message : String(e))]
      }
      const urlNames = cookies.map((c) => c.name)
      const fmt = (a) => (a.length ? a.slice(0, 12).join('、') + (a.length > 12 ? '…' : '') : '无')
      setStatus(`未检测到 ${ctx.plat.core}，可能未登录${ctx.plat.label}。`, 'risk',
        `权限自检 ${permOk === true ? '✓' : permOk === false ? '✗（去扩展详情把站点访问权限设为「在所有网站上」）' : '?'}；` +
        `url 读法 ${urlNames.length} 个：${fmt(urlNames)}；domain 读法 ${domainNames.length} 个：${fmt(domainNames)}`)
      pending = final
      forceBtn.hidden = false
      return
    }
    setStatus('正在写入剪贴板…', 'info')
    await writeClipboard(toCookieStr(final))
    const tClip = performance.now()
    const httpOnly = final.filter((c) => c.httpOnly).length
    console.log(`[Cookie Helper] 耗时 ms：读 Cookie ${Math.round(tCookies - tRead)} · 剪贴板写入 ${Math.round(tClip - tCookies)}（共 ${final.length} 个）`)
    setStatus(`已复制 ${final.length} 个 Cookie（含 ${httpOnly} 个 httpOnly）✓`, 'ok',
      (dropped ? `已清洗 ${dropped} 个异常项 · ` : '') + expiryHint(final))
  } catch (e) {
    setStatus('复制失败：' + (e && e.message ? e.message : String(e)), 'risk')
  }
})

forceBtn.addEventListener('click', async () => {
  try {
    await writeClipboard(toCookieStr(pending))
    setStatus(`已复制 ${pending.length} 个 Cookie（未校验登录态）✓`, 'ok', expiryHint(pending))
    forceBtn.hidden = true
    pending = []
  } catch (e) {
    setStatus('复制失败：' + (e && e.message ? e.message : String(e)), 'risk')
  }
})

// ── 启动自检：活性标记（静态文案是「脚本未加载」，本行替换成功＝脚本已执行）──
readCurrentSite()
verLine.textContent = `已加载 v${chrome.runtime.getManifest().version} · popup.js`
verLine.className = 'ok'

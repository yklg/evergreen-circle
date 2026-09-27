// 常青圈 Cookie 助手 —— popup 逻辑
// 职责：读取当前站点全部 Cookie（含 httpOnly）→ 清洗 → 复制到剪贴板。
// 关键：用 chrome.cookies.getAll 读取 httpOnly Cookie（document.cookie 读不到）。

// ── 各平台关键字段（复制 Cookie 用）─────────────────────────
const KEY_FIELDS = {
  douyin: {
    label: '抖音',
    core: 'sessionid',
    whitelist: ['sessionid', 'sid_tt', 'sid_ucp_v1', 'passport_csrf_token', 'odin_tt', 's_v_web_id', 'ttwid'],
  },
  xiaohongshu: {
    label: '小红书',
    core: 'web_session',
    whitelist: ['web_session', 'a1', 'webId', 'gid'],
  },
  bilibili: {
    label: 'B站',
    core: 'SESSDATA',
    whitelist: ['SESSDATA', 'bili_jct', 'buvid3', 'DedeUserID'],
  },
}

const BAD_NAME = /[\s\x00-\x1F\x7F";,=]/
const BAD_VALUE = /[\s\x00-\x1F\x7F";,]/

function platformOf(host) {
  for (const key of Object.keys(KEY_FIELDS)) {
    if (host.includes(key)) return KEY_FIELDS[key]
  }
  return null
}

function sanitize(cookies) {
  const now = Date.now() / 1000
  const byName = new Map()
  let dropped = 0
  for (const c of cookies) {
    const name = c.name == null ? '' : String(c.name).trim()
    const value = c.value == null ? '' : String(c.value)
    if (!name || BAD_NAME.test(name) || (value && BAD_VALUE.test(value))) {
      dropped++
      continue
    }
    if (c.expirationDate && c.expirationDate < now) {
      dropped++
      continue
    }
    const prev = byName.get(name)
    if (!prev) {
      byName.set(name, c)
      continue
    }
    const expNew = c.expirationDate || 0
    const expPrev = prev.expirationDate || 0
    if ((!prev.value && value) || expNew > expPrev || expNew === expPrev) {
      byName.set(name, c)
    }
    dropped++
  }
  return { list: Array.from(byName.values()), dropped }
}

function expiryHint(list) {
  const dated = list.filter((c) => c.expirationDate).map((c) => c.expirationDate)
  if (!dated.length) return '会话 Cookie，关闭浏览器即失效'
  const hours = (Math.min.apply(null, dated) - Date.now() / 1000) / 3600
  if (hours <= 0) return '存在已过期项，建议重新登录后导出'
  if (hours < 24) return '最早 ' + Math.max(1, Math.round(hours)) + ' 小时后过期'
  return '最早 ' + Math.round(hours / 24) + ' 天后过期'
}

function toCookieStr(list) {
  return list.map((c) => c.name + '=' + c.value).join('; ')
}

// ── 界面交互 ────────────────────────────────────────────
const btn = document.getElementById('copy')
const onlyKey = document.getElementById('onlyKey')
const status = document.getElementById('status')
const forceBtn = document.getElementById('force')
let pending = []

function setStatus(text, kind, meta) {
  status.textContent = text
  if (meta) {
    const span = document.createElement('span')
    span.className = 'meta'
    span.textContent = meta
    status.appendChild(span)
  }
  status.className = kind // 'ok' | 'err' | 'risk'
}

function hideForce() {
  forceBtn.hidden = true
  pending = []
}

async function doCopy(list) {
  await navigator.clipboard.writeText(toCookieStr(list))
  const httpOnlyCount = list.filter((c) => c.httpOnly).length
  setStatus('已复制 ' + list.length + ' 个 Cookie（含 ' + httpOnlyCount + ' 个 httpOnly）✓', 'ok', expiryHint(list))
  hideForce()
}

// ── 复制 Cookie ─────────────────────────────────────────
btn.addEventListener('click', async () => {
  hideForce()
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab || !tab.url) {
      setStatus('无法读取当前标签页，请保持在目标页面。', 'err')
      return
    }
    const url = new URL(tab.url)
    const cookies = await chrome.cookies.getAll({ url: url.origin })
    if (!cookies.length) {
      setStatus('该站点（' + url.origin + '）无 Cookie，请先登录对应平台。', 'err')
      return
    }
    const { list } = sanitize(cookies)
    const plat = platformOf(url.hostname)
    const final = plat && onlyKey && onlyKey.checked ? list.filter((c) => plat.whitelist.indexOf(c.name) !== -1) : list
    if (plat && !final.some((c) => c.name === plat.core && c.value)) {
      setStatus('未检测到 ' + plat.core + '，可能未登录' + plat.label + '。', 'risk')
      pending = final
      forceBtn.hidden = false
      return
    }
    await doCopy(final)
  } catch (e) {
    setStatus('复制失败：' + (e && e.message ? e.message : String(e)), 'err')
  }
})

forceBtn.addEventListener('click', async () => {
  try {
    await doCopy(pending)
  } catch (e) {
    setStatus('复制失败：' + (e && e.message ? e.message : String(e)), 'err')
  }
})
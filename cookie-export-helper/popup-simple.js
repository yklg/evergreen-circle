// 常青圈 Cookie 助手 —— 极简版
console.log('Script loaded!')

const btn = document.getElementById('copy')
const status = document.getElementById('status')

console.log('Button element:', btn)
console.log('Status element:', status)

if (!btn) {
  console.error('Button not found!')
  alert('错误:找不到按钮元素')
}

btn.addEventListener('click', async function() {
  console.log('Button clicked!')

  try {
    // 获取当前标签页
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    console.log('Current tab:', tab)

    if (!tab || !tab.url) {
      status.textContent = '无法读取当前标签页'
      status.className = 'err'
      return
    }

    // 获取 Cookie
    const cookies = await chrome.cookies.getAll({ url: new URL(tab.url).origin })
    console.log('Cookies count:', cookies.length)

    if (cookies.length === 0) {
      status.textContent = '未找到 Cookie,请先登录'
      status.className = 'err'
      return
    }

    // 转换为字符串
    const cookieStr = cookies.map(c => c.name + '=' + c.value).join('; ')

    // 复制到剪贴板
    await navigator.clipboard.writeText(cookieStr)

    status.textContent = '✓ 已复制 ' + cookies.length + ' 个 Cookie'
    status.className = 'ok'

  } catch (e) {
    console.error('Error:', e)
    status.textContent = '错误: ' + e.message
    status.className = 'err'
  }
})

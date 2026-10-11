// 测试版 - 立即执行
alert('脚本已加载!')
console.log('Script loaded at:', new Date().toISOString())

window.addEventListener('DOMContentLoaded', function() {
  alert('DOM 已就绪!')
  console.log('DOMContentLoaded event fired')

  const btn = document.getElementById('copy')
  console.log('Button found:', !!btn)

  if (btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault()
      e.stopPropagation()
      alert('按钮被点击了!')
      console.log('Click event triggered')

      // 简单测试
      navigator.clipboard.writeText('test').then(function() {
        alert('复制成功!')
      }).catch(function(err) {
        alert('复制失败: ' + err.message)
      })
    })

    console.log('Event listener attached')
  } else {
    alert('找不到按钮元素!')
    console.error('Button element not found')
  }
})

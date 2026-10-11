import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { BRAND } from './lib/brand'
import { migrateLegacyLsKeys } from './lib/lsKeys'

// 品牌标题从 lib/brand.ts 单一真相源注入。
// index.html 的静态 <title> 由 brand.test.ts 的漂移守卫保证与之一致
// （改一处忘另一处会直接测试红，不会静默漂移）。
document.title = BRAND.title

// 改名搬运：本仓从上游项目改名，本地存储键从 `verda.*` 换到 `evergreen.*`。
// 必须在**任何 store 首次读键之前**跑（store 的初始值在模块求值时就读 localStorage，
// 而 `App` 的 import 会连着把 store 一起拉起来）⇒ 只能放在这里、放在 render 之前。
// 幂等 + 失败不拦启动（见 lib/lsKeys.ts 的三条规则）。
migrateLegacyLsKeys()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

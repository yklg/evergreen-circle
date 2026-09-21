import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { BRAND } from './lib/brand'

// 品牌标题从 lib/brand.ts 单一真相源注入。
// index.html 的静态 <title> 由 brand.test.ts 的漂移守卫保证与之一致
// （改一处忘另一处会直接测试红，不会静默漂移）。
document.title = BRAND.title

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

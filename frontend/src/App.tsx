import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import AppLayout from './layout/AppLayout'
import HomePage from './pages/HomePage'
import ClarifyPage from './pages/ClarifyPage'
import WorkspacePage from './pages/WorkspacePage'
import ReportPage from './pages/ReportPage'
import GraphPage from './pages/GraphPage'
import TracePage from './pages/TracePage'
import ExpertsPage from './pages/ExpertsPage'
import ExpertDetailPage from './pages/ExpertDetailPage'
import SlidesPage from './pages/SlidesPage'
import ReportsPage from './pages/ReportsPage'
import KnowledgePage from './pages/KnowledgePage'
import SettingsPage from './pages/SettingsPage'
import LifeCirclePage from './pages/LifeCirclePage'
import ComparePage from './pages/ComparePage'
import TaskFloatBar from './components/TaskFloatBar'
import { useExpertStore } from './store/expertStore'
import { useSettingsStore } from './store/settingsStore'
import { hydrateAllPrefs } from './lib/persist'

export default function App() {
  const load = useExpertStore((s) => s.load)
  const loadSettings = useSettingsStore((s) => s.load)
  useEffect(() => {
    // 启动只预载 travel 名册：调研侧组件（工作台/trace/agent 流）挂载即取人名，
    // 缺册会把专家位显示成裸 id。生活圈名册由需要它的页面自己 load('living_circle')，
    // 不在这里"顺手都载"——那等于把两本人设同时灌进全局。
    load('travel')
  }, [load])
  useEffect(() => {
    loadSettings()
  }, [loadSettings])
  // 用户偏好（昵称/公司/模型选择）水合：localStorage 已在 store 初始化时同步喂给首屏，
  // 这里异步拉服务端真相（远端为准；远端空则把本地存量资料上推迁移）。
  useEffect(() => {
    void hydrateAllPrefs()
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        {/* 带侧边栏框架的页面 */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/life-circle" element={<Navigate to="/life-circle/kaili" replace />} />
          <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/experts" element={<ExpertsPage />} />
          <Route path="/experts/:id" element={<ExpertDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />

          {/* 旧页路由保留（移出主导航，不回归既有测试） */}
          <Route path="/knowledge" element={<KnowledgePage />} />
        </Route>

        {/* 全屏沉浸页：澄清 / 工作台 / 报告 / 图谱
            目的地调研统一经首页向导发起，工作台仅承载带 taskId 的流水线
            （/workspace/:taskId），无参 /workspace 不再注册；未知路径由 * 兜底回首页。 */}
        <Route path="/clarify/:taskId" element={<ClarifyPage />} />
        <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        <Route path="/report/:reportId" element={<ReportPage />} />
        <Route path="/report/:reportId/slides" element={<SlidesPage />} />
        <Route path="/graph/:reportId" element={<GraphPage />} />
        <Route path="/trace/:reportId" element={<TracePage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/* 全局悬浮任务条：任何页面常驻，返回后仍可找回进行中的调研 */}
      <TaskFloatBar />
    </BrowserRouter>
  )
}

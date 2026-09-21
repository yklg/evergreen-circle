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
import LibraryPage from './pages/LibraryPage'
import SlidesPage from './pages/SlidesPage'
import DashboardPage from './pages/DashboardPage'
import KnowledgePage from './pages/KnowledgePage'
import SettingsPage from './pages/SettingsPage'
import TaskFloatBar from './components/TaskFloatBar'
import { useExpertStore } from './store/expertStore'
import { useSettingsStore } from './store/settingsStore'
import { hydrateAllPrefs } from './lib/persist'

export default function App() {
  const load = useExpertStore((s) => s.load)
  const loadSettings = useSettingsStore((s) => s.load)
  useEffect(() => {
    load()
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
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/experts" element={<ExpertsPage />} />
          <Route path="/experts/:id" element={<ExpertDetailPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        {/* 全屏沉浸页：澄清 / 工作台 / 报告 / 图谱 */}
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

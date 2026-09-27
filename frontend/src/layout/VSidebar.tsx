import { useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Home,
  Map,
  GitCompare,
  Users,
  History,
  FileText,
  Sprout,
  ChevronDown,
  Settings,
  Activity,
  Database,
  MonitorPlay,
} from 'lucide-react'
import { fetchDashboard } from '../lib/api'
import { useTaskRegistry, selectRunning } from '../store/taskRegistry'
import { useProfileStore } from '../store/profileStore'
import { useDataModeStore } from '../store/dataModeStore'
import { resolveTaskLanding } from '../lib/viewRegistry'
import { BRAND } from '../lib/brand'
import { VModal, VButton } from '../components/ui'
import { useShallow } from 'zustand/react/shallow'

const navItems = [
  { to: '/', label: '工作台', icon: Home, end: true },
  { to: '/life-circle/kaili', label: '生活圈地图', icon: Map },
  { to: '/reports', label: '报告', icon: FileText },
  { to: '/compare', label: '双样例对比', icon: GitCompare },
  { to: '/experts', label: '专家团', icon: Users },
  { to: '/dashboard', label: '历史', icon: History },
]

export default function VSidebar() {
  const navigate = useNavigate()
  const [reports, setReports] = useState(0)
  const [evidence, setEvidence] = useState(0)
  // 数据模式（C1/C2）：运行时开关，真实联调（live）为常态；演示（fixture）走内置快照
  const dataMode = useDataModeStore((s) => s.mode)
  const setDataMode = useDataModeStore((s) => s.setMode)
  // selectRunning 每次调用返回新数组 → 用 useShallow 做浅比较，避免 Zustand v5 +
  // React 19 useSyncExternalStore 把「同值新引用」当成快照变更，引发无限重渲染（白屏）。
  const running = useTaskRegistry(useShallow(selectRunning))

  // 当前用户资料（单一数据源：store + localStorage）
  const profile = useProfileStore()
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [draftCompany, setDraftCompany] = useState('')

  // 头像缩写由昵称派生（改名后同步），回退「研」
  const avatarInitial = (profile.name || '研').trim().slice(0, 1) || '研'

  const openEdit = () => {
    setDraftName(profile.name)
    setDraftCompany(profile.company)
    setEditing(true)
  }
  const saveProfile = () => {
    const name = draftName.trim()
    const company = draftCompany.trim()
    profile.setProfile({
      name: name || profile.name,
      company: company || profile.company,
    })
    setEditing(false)
  }

  useEffect(() => {
    fetchDashboard().then((d) => {
      if (d) {
        setReports(d.reports)
        setEvidence(d.evidence_total)
      }
    })
  }, [])

  return (
    <aside className="relative flex h-full w-[220px] shrink-0 flex-col border-r border-line bg-card/70">
      {/* Logo */}
      <button
        onClick={() => navigate('/')}
        className="flex items-center gap-2.5 px-6 pt-6 pb-7"
      >
        <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
          <Sprout size={22} strokeWidth={1.8} />
        </span>
        <span className="text-[20px] font-semibold tracking-tight text-ink">
          {BRAND.en}
        </span>
      </button>

      {/* 导航菜单 */}
      <nav className="flex flex-1 flex-col gap-1 px-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                'flex h-11 items-center gap-3 rounded-btn px-3.5 text-[15px] transition-all ease-verda',
                isActive
                  ? 'bg-primary-tint font-medium text-primary-deep'
                  : 'text-ink-2 hover:bg-primary-tint/50',
              ].join(' ')
            }
          >
            <item.icon size={19} strokeWidth={1.8} />
            <span>{item.label}</span>
          </NavLink>
        ))}

        {/* 进行中的任务：有后台运行任务时显示，带脉冲点，点击回落对应任务落地页（research→工作台 / living_circle→生活圈页） */}
        {running.length > 0 && (
          <NavLink
            to={resolveTaskLanding(running[0].kind, running[0].taskId)}
            end={false}
            className={({ isActive }) =>
              [
                'relative flex h-11 items-center gap-3 rounded-btn px-3.5 text-[15px] transition-all ease-verda',
                isActive
                  ? 'bg-primary-tint font-medium text-primary-deep'
                  : 'text-primary hover:bg-primary-tint/50',
              ].join(' ')
            }
          >
            <span className="relative grid place-items-center">
              <Activity size={19} strokeWidth={1.8} />
              <span className="absolute -right-0.5 -top-0.5 h-2 w-2 animate-pulse rounded-full bg-ok ring-2 ring-card" />
            </span>
            <span className="flex-1 truncate">
              {running[0].kind === 'living_circle' ? '生活圈体检中' : '进行中的任务'}
            </span>
            <span className="text-tag font-medium text-primary-deep">{running[0].percent}%</span>
          </NavLink>
        )}

        {/* 分隔线 + 系统设置入口（与业务导航区分） */}
        <div className="mb-1 mt-3 h-px bg-line" />
        {/* C2 · 数据模式运行时开关：真实联调（live）/ 演示（fixture），点击即时全局生效 */}
        <div className="mx-2 mb-2 mt-1 rounded-btn border border-line/80 bg-bg/60 p-1.5">
          <div className="mb-1 flex items-center gap-1 px-1 text-tag text-ink-3">
            <Database size={11} /> 数据模式
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setDataMode('live')}
              title="连真实后端：区划选择 / 历史 / 报告 / 体检走 /api（无 AK 时自动离线估算）"
              className={`flex h-7 flex-1 items-center justify-center gap-1 rounded-btn text-tag font-medium transition-colors ${
                dataMode === 'live' ? 'bg-primary text-white shadow-card' : 'text-ink-2 hover:bg-primary-tint'
              }`}
            >
              <MonitorPlay size={12} /> 真实联调
            </button>
            <button
              type="button"
              onClick={() => setDataMode('fixture')}
              title="内置快照演示：凯里/劲松双样例，零后端"
              className={`flex h-7 flex-1 items-center justify-center gap-1 rounded-btn text-tag font-medium transition-colors ${
                dataMode === 'fixture' ? 'bg-warn text-white shadow-card' : 'text-ink-2 hover:bg-primary-tint'
              }`}
            >
              <MonitorPlay size={12} /> 演示
            </button>
          </div>
        </div>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            [
              'flex h-11 items-center gap-3 rounded-btn px-3.5 text-[15px] transition-all ease-verda',
              isActive
                ? 'bg-primary-tint font-medium text-primary-deep'
                : 'text-ink-2 hover:bg-primary-tint/50',
            ].join(' ')
          }
        >
          <Settings size={19} strokeWidth={1.8} />
          <span>模型配置</span>
        </NavLink>
      </nav>

      {/* 工作空间用量卡片 */}
      <div className="mx-3 mb-3 rounded-card border border-line/70 bg-primary-tint/40 p-4">
        <div className="flex items-center gap-2">
          <Sprout size={16} className="text-primary" strokeWidth={2} />
          <span className="text-aux font-semibold text-ink">我的工作空间</span>
        </div>
        <p className="mt-1 text-tag text-ink-3">
          累计完成 {reports} 次体检 · 已梳理 {evidence} 处设施点位
        </p>
      </div>

      {/* 底部用户：点击弹出编辑弹窗（C1） */}
      <div
        role="button"
        tabIndex={0}
        onClick={openEdit}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            openEdit()
          }
        }}
        title="点击修改昵称与公司"
        className="flex cursor-pointer items-center gap-3 border-t border-line px-4 py-3.5 transition-colors duration-200 ease-verda hover:bg-primary-tint/40"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-sun text-[13px] font-semibold text-ink">
          {avatarInitial}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">{profile.name}</div>
          <div className="truncate text-tag text-ink-3">{profile.company}</div>
        </div>
        <ChevronDown size={16} className="text-ink-3" />
      </div>

      <VModal
        open={editing}
        onClose={() => setEditing(false)}
        title="编辑个人资料"
        height="min(360px,80vh)"
      >
        <div className="flex h-full flex-col px-6 py-4">
          <div className="flex-1">
            <label className="mb-1.5 block text-tag font-medium text-ink-2">昵称</label>
            <input
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  saveProfile()
                }
              }}
              className="mb-4 w-full rounded-btn border border-line bg-card px-3 py-2 text-[14px] text-ink outline-none transition-colors duration-150 ease-verda focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="如：李工 / 王研究员"
            />
            <label className="mb-1.5 block text-tag font-medium text-ink-2">公司</label>
            <input
              value={draftCompany}
              onChange={(e) => setDraftCompany(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  saveProfile()
                }
              }}
              className="w-full rounded-btn border border-line bg-card px-3 py-2 text-[14px] text-ink outline-none transition-colors duration-150 ease-verda focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="如：常青圈"
            />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <VButton variant="ghost" onClick={() => setEditing(false)}>
              取消
            </VButton>
            <VButton onClick={saveProfile}>保存</VButton>
          </div>
        </div>
      </VModal>
    </aside>
  )
}

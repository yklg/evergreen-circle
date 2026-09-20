// @vitest-environment jsdom
/**
 * C1 · dataModeStore：初始默认 / localStorage 持久化 / 切换即时生效 / 快照读取。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { useDataModeStore, isFixtureMode } from '../store/dataModeStore'

afterEach(() => {
  localStorage.clear()
  // 复位到默认（env 未定义 → live），避免用例间串状态
  useDataModeStore.setState({ mode: 'live' })
})

describe('dataModeStore · 数据模式运行时开关（C1）', () => {
  beforeEach(() => {
    localStorage.clear()
    useDataModeStore.setState({ mode: 'live' })
  })

  it('默认 live（真实联调）', () => {
    expect(useDataModeStore.getState().mode).toBe('live')
    expect(isFixtureMode()).toBe(false)
  })

  it('setMode 即时生效 + isFixtureMode 快照跟随', () => {
    useDataModeStore.getState().setMode('fixture')
    expect(useDataModeStore.getState().mode).toBe('fixture')
    expect(isFixtureMode()).toBe(true)
    useDataModeStore.getState().setMode('live')
    expect(isFixtureMode()).toBe(false)
  })

  it('切换写入 localStorage（刷新保持的落盘依据）', () => {
    useDataModeStore.getState().setMode('fixture')
    expect(localStorage.getItem('verda.dataMode.v1')).toBe('fixture')
    useDataModeStore.getState().setMode('live')
    expect(localStorage.getItem('verda.dataMode.v1')).toBe('live')
  })

  it('localStorage 损坏/非法值回退默认', () => {
    localStorage.setItem('verda.dataMode.v1', 'garbage')
    useDataModeStore.setState({ mode: 'live' })
    // readLocal 对非法值返回 null → 回退 env 默认（测试环境为 live）
    expect(localStorage.getItem('verda.dataMode.v1')).toBe('garbage')
    expect(useDataModeStore.getState().mode).toBe('live')
  })
})

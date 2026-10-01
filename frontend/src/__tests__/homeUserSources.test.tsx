// @vitest-environment jsdom
/**
 * 首页「用户指定信源」入口契约（计划 v3 §二 F1 · §八 TC-30/TC-48/TC-49/TC-50/TC-52）。
 *
 * 判据一律落在**用户可观察结果**上：粘贴→看到几条 chip、看到哪句提示、请求体里到底
 * 带没带 `source_urls`、"存为下次默认"之后服务端 PUT 里到底写了什么。不预置 store、
 * 不直调内部函数取证（默认清单这一条走的是 GET /api/prefs 的真实水合链路）。
 *
 * 四条分工：
 * 1. 解析与上限：一次粘 12 条 ⇒ 收 10 条 + 明确说"未收录 2 条"（静默少一条是禁止的形状）；
 * 2. 请求体：createTask 的 `source_urls` 与界面 chips 逐字一致；
 * 3. 默认清单：勾选后 PUT /api/prefs 带 `intel.defaultSources`＝后端归一后的 accepted
 *    （不是用户原样串），未勾选则不发这一键；
 * 4. 演示态：输入禁用 + 说明可见 + 提交时不带清单。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

const mocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  fetchExperts: vi.fn(),
}))

vi.mock('../lib/api', async (orig) => ({
  ...((await orig()) as Record<string, unknown>),
  createTask: mocks.createTask,
  fetchExperts: mocks.fetchExperts,
}))

vi.mock('../lib/researchTypesClient', () => ({
  fetchResearchTypes: vi.fn(async () => [
    { key: 'guide', label: '游玩攻略', subtitle: '交通 · 住宿 · 路线' },
    { key: 'assessment', label: '调研评估', subtitle: '可达性 · 配套' },
  ]),
}))

function PathProbe() {
  const loc = useLocation()
  return <div data-testid="path" data-path={loc.pathname}>{JSON.stringify(loc.state ?? {})}</div>
}

/** 真实水合链路：GET /api/prefs 的返回就是默认清单的来源（不是写死的 store 初值）。 */
function stubNetwork(prefs: Record<string, unknown>) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    if (String(url).includes('/api/prefs')) {
      return new Response(JSON.stringify({ ok: true, values: prefs, stored: Object.keys(prefs) }), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }))
  return calls
}

async function renderHome(mode: 'live' | 'fixture') {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode })
  // 顺序即判据：persister 是在 store 模块加载时登记的，而真实 App 是
  // 「静态导入 store → useEffect 里 hydrateAllPrefs()」。先 hydrate 再 import store
  // 等于测一条生产里不存在的顺序，默认清单会永远预填不上。
  await import('../store/sourcePrefsStore')
  const { hydrateAllPrefs } = await import('../lib/persist')
  await hydrateAllPrefs()
  const { default: HomePage } = await import('../pages/HomePage')
  mocks.fetchExperts.mockResolvedValue([])
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/clarify/:taskId" element={<PathProbe />} />
        <Route path="/workspace/:taskId" element={<PathProbe />} />
        <Route path="/experts" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

const urlBox = () => screen.getByLabelText('用户指定信源网址')
const queryBox = () => screen.getByRole('textbox', { name: '调研需求' })
/**
 * 收起态判据。仓库约定不依赖 jest-dom 匹配器（见 methodologyNote.test.tsx 的断言风格
 * 说明，且 vitest.setup.ts 未注册），所以这里直接读 `<details>` 的 `open` —— 它既是
 * 真浏览器隐藏内容的唯一开关，也是同一条属性在一条用例里被读出 false→true 两次，
 * 判据自带活入口、不是恒真。
 * 它**不**证明 jsdom 把内容算成不可见（jsdom 不给关着的 details 子节点 display:none），
 * 它证明的是：展开态完全由这一个属性决定，而它默认是关的。
 */
const fieldRoot = () =>
  screen.getByText('用户指定信源（选填）').closest('details') as HTMLDetailsElement
const toggle = () => fieldRoot().querySelector('summary') as HTMLElement

/**
 * 展开信源块。**每个用网址框的用例都必须先走这一步**：
 * 折叠后 `getByLabelText` 在 jsdom 里照样命中，不展开就直接操作等于测一条生产里
 * 不存在的路径（真浏览器里那个框根本点不到）。
 */
function openField() {
  expect(fieldRoot().open).toBe(false)
  fireEvent.click(toggle())
  expect(fieldRoot().open).toBe(true)
}

beforeEach(() => {
  mocks.createTask.mockReset()
  mocks.createTask.mockResolvedValue({
    taskId: 't_1',
    kind: 'research',
    sourceUrls: { accepted: ['https://a.x/doc'], truncated: 0, rejected: [] },
  })
})

describe('FE-50 · 粘贴解析与上限可见', () => {
  it('一次粘 12 条 ⇒ chips 收 10 条并明说未收录 2 条', async () => {
    stubNetwork({})
    await renderHome('live')
    openField()
    const pasted = Array.from({ length: 12 }, (_, i) => `https://a.example/${i}`).join('\n')
    fireEvent.change(urlBox(), { target: { value: pasted } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))

    expect(screen.getAllByTitle(/^https:\/\/a\.example\//).length).toBe(10)
    expect(screen.getByRole('alert').textContent).toContain('2 条未收录')
  })

  it('重复粘贴不产生第二条 chip（去重口径与澄清页同源）', async () => {
    stubNetwork({})
    await renderHome('live')
    openField()
    fireEvent.change(urlBox(), { target: { value: 'https://a.x/doc' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    fireEvent.change(urlBox(), { target: { value: 'https://a.x/doc' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    expect(screen.getAllByTitle('https://a.x/doc').length).toBe(1)
  })

  it('删除一条后同样地址可再加回（截断计数不粘滞）', async () => {
    stubNetwork({})
    await renderHome('live')
    openField()
    fireEvent.change(urlBox(), { target: { value: 'https://a.x/1' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    fireEvent.click(screen.getByLabelText('移除 https://a.x/1'))
    fireEvent.change(urlBox(), { target: { value: 'https://a.x/1' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    expect(screen.getAllByTitle('https://a.x/1').length).toBe(1)
  })
})

describe('FE-51 · 建任务请求体', () => {
  it('chips 里的清单原样进 createTask 的 source_urls 参数', async () => {
    stubNetwork({})
    await renderHome('live')
    fireEvent.change(queryBox(), { target: { value: '大理亲子游' } })
    openField()
    fireEvent.change(urlBox(), { target: { value: 'https://a.x/doc https://b.x/doc' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    fireEvent.click(screen.getByRole('button', { name: /开始调研/ }))

    await waitFor(() => expect(mocks.createTask).toHaveBeenCalledTimes(1))
    const arg = mocks.createTask.mock.calls[0]
    expect(arg[4]).toEqual(['https://a.x/doc', 'https://b.x/doc'])
  })

  it('没填清单 ⇒ 不传（后端据此不回 sourceUrls 回执，响应形状与改前一致）', async () => {
    stubNetwork({})
    await renderHome('live')
    fireEvent.change(queryBox(), { target: { value: '大理亲子游' } })
    fireEvent.click(screen.getByRole('button', { name: /开始调研/ }))
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalledTimes(1))
    expect(mocks.createTask.mock.calls[0][4]).toEqual([])
  })
})

describe('FE-52 · 存为下次默认落服务端偏好', () => {
  it('勾选后 PUT /api/prefs 带的是后端归一的 accepted，不是用户原样串', async () => {
    const calls = stubNetwork({})
    mocks.createTask.mockResolvedValue({
      taskId: 't_2', kind: 'research',
      // 用户输入的是裸域名，后端归一成 https:// 形式并剥掉凭据
      sourceUrls: { accepted: ['https://gov.cn/doc'], truncated: 0, rejected: [] },
    })
    await renderHome('live')
    fireEvent.change(queryBox(), { target: { value: '大理亲子游' } })
    openField()
    fireEvent.change(urlBox(), { target: { value: 'gov.cn/doc' } })
    fireEvent.click(screen.getByRole('button', { name: '添加' }))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /开始调研/ }))

    await waitFor(() => {
      const puts = calls
        .filter((c) => c.url.includes('/api/prefs') && c.init?.method === 'PUT')
        .map((c) => JSON.parse(String(c.init!.body)) as { patch?: Record<string, unknown> })
        .filter((b) => 'intel.defaultSources' in (b.patch ?? {}))
      // 水合阶段也会 PUT（把本地存量上推），所以判据落在**最后写出去的那一份**：
      // 存的必须是后端归一后的 accepted，而不是用户输入的裸域名。
      expect(puts.length).toBeGreaterThan(0)
      expect(puts[puts.length - 1].patch?.['intel.defaultSources']).toEqual(['https://gov.cn/doc'])
    })
  })

  it('GET /api/prefs 里的默认清单会在首屏预填成 chips（换浏览器仍能拿回）', async () => {
    stubNetwork({ 'intel.defaultSources': ['https://saved.x/a', 'https://saved.x/b'] })
    await renderHome('live')
    // 收起态就得报得出条数：用户不点开也必须知道自己钉过东西
    await waitFor(() => expect(screen.getByText('已钉 2 条')).toBeTruthy())
    expect(fieldRoot().open).toBe(false)
    openField()
    await waitFor(() => expect(screen.getAllByTitle(/^https:\/\/saved\.x\//).length).toBe(2))
    expect(fieldRoot().open).toBe(true)
  })

  it('不勾选 ⇒ 默认清单不被改写', async () => {
    const calls = stubNetwork({ 'intel.defaultSources': ['https://old.x/a'] })
    mocks.createTask.mockResolvedValue({
      taskId: 't_3', kind: 'research',
      sourceUrls: { accepted: ['https://new.x/b'], truncated: 0, rejected: [] },
    })
    await renderHome('live')
    fireEvent.change(queryBox(), { target: { value: '大理亲子游' } })
    fireEvent.click(screen.getByRole('button', { name: /开始调研/ }))
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalled())
    // 水合阶段的 PUT（把存量本地值上推）允许存在，但绝不允许把清单换成 new.x
    const bodies = calls
      .filter((c) => c.init?.method === 'PUT')
      .map((c) => JSON.parse(String(c.init!.body)))
      .filter((b) => 'intel.defaultSources' in (b.patch ?? {}))
    for (const b of bodies) {
      expect(b.patch['intel.defaultSources']).not.toContain('https://new.x/b')
    }
  })
})

describe('FE-53 · 演示态禁用且说明可见', () => {
  it('fixture 模式：输入不可用、写明不会联网、提交不带清单', async () => {
    stubNetwork({})
    await renderHome('fixture')
    // 收起态就要念出"不会被读取"：这句必须落在 summary 里，而不是藏在要点开才看得见的地方
    const warn = screen.getByText(/下面这些网址不会被读取/)
    expect(warn.closest('summary')).not.toBeNull()
    openField()
    const box = urlBox() as HTMLInputElement
    expect(box.disabled).toBe(true)
    expect(screen.getByRole('status').textContent).toContain('不会联网')
    fireEvent.change(queryBox(), { target: { value: '大理亲子游' } })
    fireEvent.click(screen.getByRole('button', { name: /开始调研/ }))
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalled())
    // 演示态交出去的是"没有清单"（null / 空数组都算）：api.createTask 只在非空时才把
    // source_urls 拼进请求体 ⇒ 这个键不会出现在线上。判据是"没带上"，不是"等于某个具体值"。
    expect(mocks.createTask.mock.calls[0][4]).toBeFalsy()
  })
})

describe('FE-54 · 收起态是真防线（首屏适配：信源块不再挤掉示例）', () => {
  it('默认收起 ⇒ `<details>` 不带 open，标题行常驻可见', async () => {
    stubNetwork({})
    await renderHome('live')
    expect(fieldRoot().open).toBe(false)
    expect(screen.getByText('用户指定信源（选填）').closest('summary')).not.toBeNull()
  })

  it('有默认清单也**不**自动展开：展开只由点标题那一下驱动', async () => {
    // 自动展开等于对"已经存过清单"的用户永远收起 —— 而默认清单正是本功能的主用法。
    // 这条就是钉住那个决定的反向对照：谁改回"有 urls 就 open"，这里直接红。
    stubNetwork({ 'intel.defaultSources': ['https://saved.x/a', 'https://saved.x/b'] })
    await renderHome('live')
    await waitFor(() => expect(screen.getByText('已钉 2 条')).toBeTruthy())
    expect(fieldRoot().open).toBe(false)
    fireEvent.click(toggle())
    expect(fieldRoot().open).toBe(true)
  })
})

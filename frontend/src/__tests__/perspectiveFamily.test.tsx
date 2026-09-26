// @vitest-environment jsdom
/**
 * rough-cliff-vole 前端契约钉：
 *   VR-B1 条件题显隐 + 答案残留回退（改答亲子→情侣后题消失且旧答案被清）
 *   VR-F1 亲子核查表渲染（行=冻结榜不丢行、待核验 text-risk 占位、证据列）
 *   VR-F2 视角三块（核查表/铁律/清单）各有渲染分支
 *   VR-F5 兼容：旧报告单块 {type,data} 形状照渲；未知/缺失块零波及
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ClarifyPage from '../pages/ClarifyPage'
import { VStructuredBlock } from '../components/VStructured'
import * as api from '../lib/api'

const { navigateFn } = vi.hoisted(() => ({ navigateFn: vi.fn() }))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateFn }
})

vi.mock('../lib/api', () => ({
  createTask: vi.fn(),
  openClarifyStream: vi.fn(() => () => {}),
  submitClarify: vi.fn(),
}))

const mockedOpenClarifyStream = api.openClarifyStream as unknown as ReturnType<typeof vi.fn>
const mockedSubmitClarify = api.submitClarify as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  navigateFn.mockClear()
  mockedOpenClarifyStream.mockReset().mockImplementation(() => () => {})
  mockedSubmitClarify.mockReset().mockResolvedValue({ ok: true })
})
afterEach(() => cleanup())

function renderClarify(taskId: string) {
  return render(
    <MemoryRouter initialEntries={[`/clarify/${taskId}`]}>
      <Routes>
        <Route path="/clarify/:taskId" element={<ClarifyPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockReady(questions: unknown[]) {
  mockedOpenClarifyStream.mockImplementation((_tid: string, handlers: any) => {
    handlers.onEvent('clarify_ready', { questions })
    return () => {}
  })
}

const QUIZ = [
  { id: 'days', question: '这次计划玩几天？', type: 'single', options: ['1-2 天', '3-5 天'] },
  { id: 'party', question: '同行人群是？', type: 'single', options: ['亲子家庭', '情侣/夫妻'] },
  { id: 'child_age', question: '孩子多大？', type: 'single',
    options: ['3 岁以下', '3-6 岁'], show_if: { qid: 'party', equals: '亲子家庭' } },
  { id: 'budget_level', question: '预算档位？', type: 'single', options: ['经济实惠', '舒适均衡'] },
]

describe('VR-B1 条件题显隐与答案残留回退', () => {
  it('未答 party 时 child_age 不进问卷；答「亲子家庭」后出现且必答进提交', async () => {
    mockReady(QUIZ)
    renderClarify('t_show')
    await screen.findByText('这次计划玩几天？')
    expect(screen.queryByText('孩子多大？')).toBeNull()

    fireEvent.click(screen.getByText('1-2 天'))
    fireEvent.click(screen.getByText('下一步'))
    fireEvent.click(screen.getByText('亲子家庭'))
    fireEvent.click(screen.getByText('下一步'))
    // 下一题即条件题
    expect(await screen.findByText('孩子多大？')).toBeTruthy()
    fireEvent.click(screen.getByText('3-6 岁'))
    fireEvent.click(screen.getByText('下一步'))
    fireEvent.click(screen.getByText('经济实惠'))
    fireEvent.click(screen.getByText('下一步'))
    await screen.findByText('请核对，可直接修改')
    fireEvent.click(screen.getByText('启动调研'))
    await waitFor(() => expect(mockedSubmitClarify).toHaveBeenCalled())
    const payload = mockedSubmitClarify.mock.calls[0][1]
    expect(payload.child_age).toBe('3-6 岁')
  })

  it('改答「亲子→情侣」：题消失且旧答案被清（残留=脏数据，绝不进提交）', async () => {
    mockReady(QUIZ)
    renderClarify('t_hide')
    await screen.findByText('这次计划玩几天？')
    fireEvent.click(screen.getByText('1-2 天'))
    fireEvent.click(screen.getByText('下一步'))
    fireEvent.click(screen.getByText('亲子家庭'))
    fireEvent.click(screen.getByText('下一步'))
    await screen.findByText('孩子多大？')
    fireEvent.click(screen.getByText('3-6 岁'))
    fireEvent.click(screen.getByText('下一步'))
    fireEvent.click(screen.getByText('经济实惠'))
    fireEvent.click(screen.getByText('下一步'))
    await screen.findByText('请核对，可直接修改')
    // 核对屏改答 party → 条件题整行消失（可见题集 4→3，步号钳制回核对屏）
    fireEvent.click(screen.getByText('情侣/夫妻'))
    expect(await screen.findByText('请核对，可直接修改')).toBeTruthy()
    expect(screen.queryByText('孩子多大？')).toBeNull()
    fireEvent.click(screen.getByText('启动调研'))
    await waitFor(() => expect(mockedSubmitClarify).toHaveBeenCalled())
    const payload = mockedSubmitClarify.mock.calls[0][1]
    expect(payload.party).toBe('情侣/夫妻')
    // 答案残留回退（外部经验：条件题头号缺陷）
    expect('child_age' in payload).toBe(false)
  })
})

describe('VR-F1/F2/F5 视角结构化块渲染', () => {
  const checklistBlock = {
    type: 'persp_checklist' as const,
    data: [{
      destination: '大理',
      items: [
        { spot_id: 's1', spot_name: '洱海', cells: [
          { column: '儿童票规则', text: '生态廊道免费', evidence_ids: ['e_a1'], verified: true },
          { column: '推车可行/体力门槛', text: '平坦可推车', evidence_ids: ['e_a1'], verified: true },
          { column: '母婴室/家庭卫生间', text: '待核验（本次未采到）', evidence_ids: [], verified: false },
          { column: '带娃节奏建议', text: '清晨或傍晚', evidence_ids: ['e_a2'], verified: true },
        ] },
        { spot_id: 's2', spot_name: '大理古城', cells: [
          { column: '儿童票规则', text: '待核验（本次未采到）', evidence_ids: [], verified: false },
          { column: '推车可行/体力门槛', text: '待核验（本次未采到）', evidence_ids: [], verified: false },
          { column: '母婴室/家庭卫生间', text: '待核验（本次未采到）', evidence_ids: [], verified: false },
          { column: '带娃节奏建议', text: '待核验（本次未采到）', evidence_ids: [], verified: false },
        ] },
      ],
    }],
  }

  it('核查表：行全出不丢行、待核验格占位样式、证据列引用 id', () => {
    const { container } = render(<VStructuredBlock block={checklistBlock} />)
    expect(screen.getByTestId('spot-checklist')).toBeTruthy()
    expect(container.querySelectorAll('[data-checklist-row]')).toHaveLength(2)
    const missing = container.querySelectorAll('[data-cell-missing]')
    expect(missing.length).toBe(5) // s1 一格 + s2 四格
    expect(screen.getByText('洱海')).toBeTruthy()
    expect(screen.getByText(/e_a1/)).toBeTruthy()
  })

  it('复数挂块：核查表+铁律+清单同章全渲染', () => {
    render(
      <VStructuredBlock block={[
        checklistBlock,
        { type: 'persp_rules', data: [{ destination: '大理',
          items: [{ text: '每天只排 1 个主点', refs: ['days'], evidence_ids: ['e_a1'] }] }] },
        { type: 'persp_packing', data: [{ destination: '大理',
          items: [{ item: '户口本原件', reason: '免票核验', evidence_ids: ['e_a2'] }] }] },
      ] as any} />,
    )
    expect(screen.getByTestId('spot-checklist')).toBeTruthy()
    expect(screen.getByTestId('persp-rules')).toBeTruthy()
    expect(screen.getByTestId('persp-packing')).toBeTruthy()
    expect(screen.getByText('每天只排 1 个主点')).toBeTruthy()
    expect(screen.getByText('户口本原件')).toBeTruthy()
  })

  it('兼容：旧报告单块 {type,data} 形状照渲；空数组/未知类型零渲染不崩', () => {
    const legacy = { type: 'stay_options', data: [{ destination: '大理', areas: [
      { area: '古城', price_range: '150-300', for_whom: '首次客',
        pros: [], cons: [], evidence_ids: [] }] }] }
    const { container } = render(<VStructuredBlock block={legacy as any} />)
    expect(container.textContent).toContain('古城')
    expect(() => render(<VStructuredBlock block={[] as any} />)).not.toThrow()
    expect(() => render(
      <VStructuredBlock block={[{ type: 'no_such_block', data: [] }] as any} />)).not.toThrow()
  })
})

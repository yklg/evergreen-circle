// @vitest-environment jsdom
/**
 * 方法论与局限披露组件（MethodologyNote）渲染测试（accuracy-objectivity-hardening v2.1）。
 *
 * 覆盖：
 *  - 有 methodology → 渲染「方法论与局限」标题 + 关键键值（证据数/信源组/去重/过热/覆盖率/窗口）+ 免责 note
 *  - 无 methodology → 不渲染任何内容（空数据安全隐藏）
 *  - contradictions 条目 → 渲染矛盾陈述文本、存疑说明、证据引用
 *
 * 断言风格与仓库现有测试一致（toBeTruthy / toBeNull，不依赖 jest-dom 匹配器）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MethodologyNote from '../components/MethodologyNote'

describe('MethodologyNote', () => {
  it('有 methodology 时渲染指标键值与免责说明', () => {
    render(
      <MethodologyNote
        methodology={{
          window: 'oneYear',
          evidence_count: 12,
          unique_groups: 6,
          dup_skipped: 3,
          viral_evidence: 1,
          viral_checked_ratio: 0.25,
          sentiment_samples: 40,
          note: '仅供参考，不作事实认证。',
        }}
        contradictions={[]}
      />,
    )
    expect(screen.getByText('方法论与局限')).toBeTruthy()
    // 键值
    expect(screen.getByText('证据总数')).toBeTruthy()
    expect(screen.getByText('12')).toBeTruthy()
    expect(screen.getByText('独立信源组')).toBeTruthy()
    expect(screen.getByText('6')).toBeTruthy()
    expect(screen.getByText('同质转载去重')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('舆论过热标注')).toBeTruthy()
    expect(screen.getByText('过热判定覆盖率')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getByText('搜索时效窗口')).toBeTruthy()
    expect(screen.getByText('oneYear')).toBeTruthy()
    // 免责说明
    expect(screen.getByText('仅供参考，不作事实认证。')).toBeTruthy()
  })

  it('无 methodology 时不渲染任何内容', () => {
    const { container } = render(<MethodologyNote />)
    expect(container.firstChild).toBeNull()
  })

  it('methodology 空对象且无 note 时不渲染（hasData 守卫）', () => {
    const { container } = render(<MethodologyNote methodology={{}} contradictions={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('contradictions 条目渲染矛盾陈述、说明与证据引用', () => {
    render(
      <MethodologyNote
        methodology={{ evidence_count: 2, note: '标准披露。' }}
        contradictions={[
          { claim_text: 'A 平台显示定价 2999 元，B 平台显示 3099 元', evidence_ids: ['e_1', 'e_2'], note: '来源间说法不一致，未证实' },
          { claim_text: '仅单方渠道披露的口径', evidence_ids: [], note: '' },
        ]}
      />,
    )
    expect(screen.getByText('存在分歧/未证实的陈述')).toBeTruthy()
    expect(screen.getByText('A 平台显示定价 2999 元，B 平台显示 3099 元')).toBeTruthy()
    expect(screen.getByText('来源间说法不一致，未证实')).toBeTruthy()
    expect(screen.getByText('[e_1] [e_2]')).toBeTruthy()
    expect(screen.getByText('仅单方渠道披露的口径')).toBeTruthy()
  })
})
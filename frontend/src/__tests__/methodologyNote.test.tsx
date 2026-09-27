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
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import MethodologyNote from '../components/MethodologyNote'

// 本文件既有断言全是「存在性」，不显式 cleanup 也能过；一旦加了「不得出现」的反向断言
// （新口径不得追注到存量报告），上一次 render 留下的 DOM 就会让它假红。故显式清场。
afterEach(cleanup)

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

/* ── 舆情口径注册（词云口碑化修复 步骤 8）：新键必须肉眼可见，旧报告不得被追注 ── */

describe('MethodologyNote · 舆情口径行', () => {
  it('新报告：有效口碑与检索语料并排显示（只显一个数就会被误读成口碑暴跌）', () => {
    render(
      <MethodologyNote
        methodology={{
          evidence_count: 30,
          sentiment_samples: 7,
          sentiment_corpus: 25,
          sentiment_doc_kind_counts: { review: 7, ticket_faq: 5, flight: 3 },
          sentiment_low_sample: true,
          note: '舆情占比基于可核验用户口碑文本。',
        }}
      />,
    )
    expect(screen.getByText('有效口碑')).toBeTruthy()
    expect(screen.getByText('7 条')).toBeTruthy()
    expect(screen.getByText('检索相关语料')).toBeTruthy()
    expect(screen.getByText('25 条')).toBeTruthy()
    expect(screen.getByText('样本偏小·只报计数')).toBeTruthy()
    // 旧标签不得残留：同一数字在新口径下叫「有效口碑」，再叫「舆情样本量」就是两套口径并存
    expect(screen.queryByText('舆情样本量')).toBeNull()
  })

  it('存量报告（只有 sentiment_samples）：按今天的样子显示，不追注新口径', () => {
    render(<MethodologyNote methodology={{ sentiment_samples: 25 }} />)
    expect(screen.getByText('舆情样本量')).toBeTruthy()
    expect(screen.getByText('25')).toBeTruthy()
    expect(screen.queryByText('有效口碑')).toBeNull()
    expect(screen.queryByText('检索相关语料')).toBeNull()
    expect(screen.queryByText('样本偏小·只报计数')).toBeNull()
  })

  it('样本充足时不出「只报计数」标注（判据读后端 low_sample，前端不自算阈值）', () => {
    render(<MethodologyNote methodology={{ sentiment_samples: 34, sentiment_corpus: 120 }} />)
    expect(screen.getByText('34 条')).toBeTruthy()
    expect(screen.queryByText('样本偏小·只报计数')).toBeNull()
  })
})
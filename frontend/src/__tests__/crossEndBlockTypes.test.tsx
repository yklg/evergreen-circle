// @vitest-environment jsdom
/**
 * 跨端结构化块契约（D6b）——后端会发的块类型，前端必须有渲染器。
 *
 * 为什么需要：VStructured 的 BLOCKS 分发对未登记类型是 `return null`，即**静默不渲染**
 * （不报错、不降级）。前端在 Vercel、后端在 Railway，分开部署——后端新增一个块类型而
 * 前端 bundle 没跟上时，用户看到的是「视角专栏凭空少一块」，没有任何可诊断的痕迹。
 * 这正是核查表改单名（family_checklist → persp_checklist）时最容易踩的坑。
 *
 * 数据源用 checked-in 快照而非拉接口：vitest 在 CI 里不联网、后端也不在线，
 * 若这里去 fetch，门就会在无声中降级为「永远通过」。快照与注册表的一致性
 * 由后端 tests/test_research_types_api.py 的镜像用例钉住。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import snapshot from '../mocks/researchTypes.json'
import { STRUCTURED_BLOCK_TYPES, VStructuredBlock } from '../components/VStructured'
import type { StructuredBlock, StructuredBlockType } from '../types'

interface TypeOption { key: string; structured_block_types?: string[] }
const TYPES = (snapshot as { types: TypeOption[] }).types

describe('D6b-1 快照必须真的携带块类型清单（防空过）', () => {
  it('每个调研类型都带非空 structured_block_types', () => {
    expect(TYPES.length).toBeGreaterThan(0)
    for (const t of TYPES) {
      expect(Array.isArray(t.structured_block_types),
        `${t.key} 缺 structured_block_types —— 快照过期，请重跑 gen-research-types-fixture.mjs`)
        .toBe(true)
      expect(t.structured_block_types!.length, `${t.key} 的块类型清单为空`).toBeGreaterThan(0)
    }
  })
})

describe('D6b-2 前端渲染器覆盖后端可能下发的全部块类型', () => {
  const emitted = [...new Set(TYPES.flatMap((t) => t.structured_block_types ?? []))]

  it('BLOCKS 键集 ⊇ 后端下发的块类型全集', () => {
    const missing = emitted.filter((k) => !STRUCTURED_BLOCK_TYPES.includes(k as StructuredBlockType))
    expect(missing, `后端会下发但前端无渲染器的块类型：${missing.join(', ')}`).toEqual([])
  })

  it('视角三块在覆盖范围内（本次改名的回归靶心）', () => {
    for (const k of ['persp_checklist', 'persp_rules', 'persp_packing']) {
      expect(emitted, '视角块未出现在快照清单里').toContain(k)
      expect(STRUCTURED_BLOCK_TYPES).toContain(k)
    }
  })
})

describe('D6b-3 未登记块走可见降级，退役块仍静默跳过', () => {
  afterEach(cleanup)

  it('未知且未退役的 type → 渲染占位提示，内部标识只落 data-* 不进文案', () => {
    const block = {
      type: 'persp_zzz_not_wired' as unknown as StructuredBlockType,
      data: [{ destination: '三亚' }],
    } as StructuredBlock
    const { container } = render(<VStructuredBlock block={block} />)
    const node = container.querySelector('[data-unrecognized-block]')
    expect(node, '未登记块被静默丢弃了——用户将看不到任何痕迹').not.toBeNull()
    expect(node?.getAttribute('data-unrecognized-block')).toBe('persp_zzz_not_wired')
    // 报告页无鉴权且可 window.print() 导出：内部键名不得出现在可见文案里
    expect(container.textContent).not.toContain('persp_zzz_not_wired')
    expect(container.textContent).toContain('本块数据暂不可用')
  })

  it('已退役 type 仍不渲染（后端已无产出路径，报错只是噪声）', () => {
    for (const type of ['feature_tree', 'pricing_model', 'user_persona', 'swot', '']) {
      const block = {
        type: type as unknown as StructuredBlockType,
        data: [{ destination: '佳沃食品' }],
      } as StructuredBlock
      const r = render(<VStructuredBlock block={block} />)
      expect(r.container.textContent).toBe('')
      r.unmount()
    }
  })
})

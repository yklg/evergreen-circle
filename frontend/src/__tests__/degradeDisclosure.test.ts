/**
 * M11 · R-7 降级披露（前端侧）
 *
 * 读**跨语言契约夹具** `fixtures/degradeDetailContract.json` —— 与后端
 * `backend/tests/test_degrade_chain.py::test_m11_degrade_labels_match_contract` 同一份
 * （范式同 compareDiffContract.json：改一处必须改三处）。
 *
 * 覆盖：
 *  - 6 个已知 detail → 标签 + 标题逐字
 *  - 未知/缺失输入（4 例）一律回落「配额耗尽」，**不抛异常、不返回空串**
 *  - `degradeBanner` 的 null 语义：`degraded` 缺失 ⇒ 走原「离线估算」文案（不误伤既有报告）
 *  - ⚠️ 假绿防线：断言的是**夹具算出的字面量**，不是 `degradeDetailLabel(x)` 的返回值本身
 *    （后者会让「把标签函数改坏」时等号两边一起变）。
 */
import { describe, it, expect } from 'vitest'
import contract from './fixtures/degradeDetailContract.json'
import {
  DEGRADE_DETAIL_FALLBACK,
  DEGRADE_DETAIL_LABELS,
  degradeBanner,
  degradeDetailLabel,
} from '../lib/livingCircle'
import type { LifeCircleDegraded, LivingCircleReport } from '../types'

const CASES = contract._cases
const UNKNOWN_INPUTS = contract._unknown_inputs as (string | null)[]

describe('M11 · 降级成因标签（跨语言契约夹具）', () => {
  it('表本身与夹具逐字一致（防止前端私自改表而夹具不知）', () => {
    expect(DEGRADE_DETAIL_LABELS).toEqual(contract.labels)
    expect(DEGRADE_DETAIL_FALLBACK).toBe(contract._fallback)
  })

  for (const c of CASES) {
    it(`detail=${c.detail} → 「${c.label}」`, () => {
      // ⚠️ 与夹具字面量比，不与 degradeDetailLabel(c.detail) 比
      expect(degradeDetailLabel(c.detail)).toBe(c.label)
    })
  }

  for (const bad of UNKNOWN_INPUTS) {
    it(`未知输入 ${JSON.stringify(bad)} → 回落「${contract._fallback}」（不抛、不空）`, () => {
      const out = degradeDetailLabel(bad)
      expect(out).toBe(contract._fallback)
      expect(out.length).toBeGreaterThan(0)
    })
  }
})

describe('M11 · degradeBanner（披露唯一出口）', () => {
  for (const c of CASES) {
    it(`detail=${c.detail} → 标题「${c.title}」`, () => {
      const b = degradeBanner({ degraded: { reason: 'baidu_quota_exhausted', detail: c.detail } })
      expect(b).not.toBeNull()
      // ⚠️ 锚夹具字面量，不锚 `百度${degradeDetailLabel(...)}：…` 这类自算串
      expect(b!.title).toBe(c.title)
      expect(b!.label).toBe(c.label)
      expect(b!.body.length).toBeGreaterThan(0)
      expect(b!.tone).toBe('risk')
    })
  }

  it('行动提示带后端 note，且**不给按钮**（q-2：重检要重烧额度，不该随手触发）', () => {
    const withNote: LifeCircleDegraded = {
      reason: 'baidu_quota_exhausted',
      detail: 'total_meltdown',
      note: contract._note_en,
    }
    const b = degradeBanner({ degraded: withNote })!
    expect(b.action).toContain(contract._note_en)
    expect(b.action).toContain('配额恢复后可发起实时重检')
    // 出口只产出**文案**，不产出任何可点击动作/回调
    expect(Object.keys(b).sort()).toEqual(['action', 'body', 'label', 'title', 'tone'])
  })

  it('无 note 时行动提示退化为「配额恢复后可发起实时重检」（不出现 undefined）', () => {
    const b = degradeBanner({ degraded: { reason: 'baidu_quota_exhausted', detail: 'poi_empty' } })!
    expect(b.action).toBe('配额恢复后可发起实时重检')
    expect(b.action).not.toContain('undefined')
  })

  it('degraded 缺失 ⇒ null ⇒ 走原「离线估算」文案（不误伤未联网的离线报告）', () => {
    expect(degradeBanner({ degraded: undefined })).toBeNull()
    expect(degradeBanner({})).toBeNull()
  })

  it('degraded=null（历史列表未降级时的下发音）⇒ 同样 null', () => {
    expect(degradeBanner({ degraded: null } as unknown as Pick<LivingCircleReport, 'degraded'>)).toBeNull()
  })

  it('未知 detail 也照样出横幅（降级时更要说得出话，不能因为归因不明就不披露）', () => {
    const b = degradeBanner({ degraded: { reason: 'baidu_quota_exhausted', detail: 'NO_SUCH' } })!
    expect(b.title).toContain(contract._fallback)
    expect(b.label).toBe(contract._fallback)
  })
})

import { describe, it, expect } from 'vitest'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

/* 前后端类别键契约（rev3 §四I / 用例 26）。
 *
 * `LC_CAT_LABEL` 必须镜像后端 `category_rule.CATEGORY_RULES` / `poi.CATEGORY_DEFS` 的
 * 类别键集合：缺键（前端少一类）或多键（口径漂移）即失败，杜绝两端类别数不一致
 * 导致图例/统计错位。
 *
 * 守卫：`lcCatLabel.ts` 为目标模块，rev3 落地前不存在 —— 用 `existsSync` 探测，
 * 缺失即 skip，不造成 collector 报错；落地后自动转真实断言。
 */

const LBL = fileURLToPath(new URL('./lcCatLabel.ts', import.meta.url))

describe('LC_CAT_LABEL ↔ 后端类别键契约', () => {
  if (!existsSync(LBL)) {
    it.skip('lcCatLabel.ts 尚未落地（rev3 §四I），待实现后核验键集合', () => {})
    return
  }

  it('共 8 类民生类别键', async () => {
    const { LC_CAT_LABEL } = await import('./lcCatLabel')
    const keys = Object.keys(LC_CAT_LABEL)
    expect(keys).toHaveLength(8)
    expect(keys.sort()).toEqual(
      ['market', 'medical', 'education', 'shopping', 'elderly', 'finance', 'recreation', 'service'].sort(),
    )
  })

  it('每个类别键都有可展示 label', async () => {
    const { LC_CAT_LABEL } = await import('./lcCatLabel')
    for (const [k, v] of Object.entries(LC_CAT_LABEL)) {
      expect(k.length).toBeGreaterThan(0)
      expect(String(v).length).toBeGreaterThan(0)
    }
  })
})
// @vitest-environment jsdom
/**
 * R22-5（第 22 轮评审）· `CategoryCaliberNotes` 的**渲染**判据。
 *
 * 为什么补这份文件：片 1c-β C1 交付说明里"名单已上屏、挂在两页雷达正下方"这件事，
 * 到今天**只有 `src/lib/lcSubKindCaliber.contract.test.ts` 的头注释在承诺**，全仓零渲染用例
 * （搜屏上前缀「覆盖度只数」在测试里 0 命中）。函数级判据测得住"算得出这句话"，
 * 测不住"这句话被挂到屏上"——组件自己的 `!notes.length ⇒ null` 与"其余 N 类"那半更是零覆盖。
 *
 * ⚠️ 期望串一律由 `lcCategoryCaliberNote` 从**同一份 payload** 现取，测试里不重写措辞
 *    （重写就是第二份实现，措辞一改两边一起改、守卫却看不出区别）。
 * ⚠️ 本项目前端测试**没有 jest-dom**（`toBeVisible` 会直接抛 Invalid Chai property），
 *    所以"没上屏"用 `container.firstChild` 为 null 来判。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { CategoryCaliberNotes } from '../components/lifecircle/CategoryCaliberNotes'
import { lcCategoryCaliberNote } from '../lib/livingCircle'
import type { FacilityCategoryStat, LivingCircleReport } from '../types'

const LC = kaili as unknown as LivingCircleReport
const CATS: FacilityCategoryStat[] = LC.poi.categories
const TABLED = CATS.filter((c) => c.scored_as != null && c.required_in_circle != null)
const UNTABLED = CATS.filter((c) => c.required_in_circle == null).length

afterEach(() => cleanup())

describe('类别旁那句口径说明的上屏契约', () => {
  it('前置：这份夹具确实既有建表类、又有未建表类（否则下面两支都做空转）', () => {
    expect(TABLED.length, '夹具里没有任何带名单的类别 ⇒ 本文件什么都测不到').toBeGreaterThan(0)
    expect(UNTABLED, '夹具里全是建表类 ⇒ 兜底那句没有对照面').toBeGreaterThan(0)
  })

  it('每个建表类别各有一句上屏，且那句里带着它自己的分子', () => {
    render(<CategoryCaliberNotes lc={LC} />)
    for (const c of TABLED) {
      const want = lcCategoryCaliberNote(c)
      expect(want, `${c.category}：函数本该出句子，却返回 null`).not.toBeNull()
      expect(screen.getAllByText(String(want)), `${c.category} 那句没出现在屏上`).toHaveLength(1)
      // 分子必须钉在**句法位置**上：`中 N 处` 不会被「圈内 25 处」里的 25 白送
      // （第 22 轮 R22-4：原先只 `toContain(String(req))`，凯里 25/5、15/1 两档都印错也不会红）。
      expect(String(want)).toContain(`中 ${c.required_in_circle} 处`)
    }
  })

  it('兜底那句的数字与"未建表的类别数"同源，不是硬编码', () => {
    render(<CategoryCaliberNotes lc={LC} />)
    expect(screen.getByText(`其余 ${UNTABLED} 类：覆盖度仍按圈内点数计分`)).toBeTruthy()
  })

  it('旧载荷（两把名单键都抹掉）⇒ 整块不出现，而不是退回前端硬编码名单', () => {
    const legacy = {
      ...LC,
      poi: {
        ...LC.poi,
        categories: CATS.map((c) => {
          const copy = { ...c } as Record<string, unknown>
          delete copy.scored_as
          delete copy.unscored_as
          delete copy.required_in_circle
          return copy as unknown as FacilityCategoryStat
        }),
      },
    } as unknown as LivingCircleReport
    const tabledBefore = CATS.filter((c) => lcCategoryCaliberNote(c) !== null).length
    expect(tabledBefore, '夹具本身没有建表类 ⇒ 这一支会在空集上恒真').toBeGreaterThan(0)
    const { container } = render(<CategoryCaliberNotes lc={legacy} />)
    expect(container.firstChild, '没有名单键却仍渲染出一块 ⇒ 展示侧自己补了名单（第二份判类）').toBeNull()
  })
})

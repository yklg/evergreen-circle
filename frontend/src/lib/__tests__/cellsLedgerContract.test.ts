/**
 * 逐格台账的**读侧**契约测试（两侧同钉：`__tests__/fixtures/cellsLedgerContract.json`
 * 由后端 `tests/test_cells_ledger_contract.py` 各钉一次）。
 *
 * 这片守的只有一件事：前端**只解码、不重算**。所以断言分两头 ——
 * 一头钉"字母表/键名/格型与后端同一份"（漂了就把台账读成别的字），
 * 另一头钉"任何不符都退成 `null` 而不是猜一个结论"（半截台账比没台账更危险）。
 */
import { describe, expect, it } from 'vitest'

import contract from '../../__tests__/fixtures/cellsLedgerContract.json'
import {
  cellAt,
  cellsLedgerOf,
  cellVerdict,
  LEDGER_GRID,
  LEDGER_NO,
  LEDGER_SCHEMA_VERSION,
  LEDGER_UNKNOWN,
  LEDGER_YES,
  judgeRulerLabel,
  judgeRulerM,
  cellCenter,
  cellIndex,
} from '../livingCircle'
import type { CellsLedgerRaw, LivingCircleReport } from '../../types'

const SAMPLE = contract.sample as unknown as CellsLedgerRaw
const withLedger = (led: unknown): LivingCircleReport =>
  ({ caliber: { cells_ledger: led } }) as unknown as LivingCircleReport

describe('逐格台账契约：字母表与键名两侧同源', () => {
  it('四个记号与后端 `blindspot.LEDGER_*` 逐字相同', () => {
    expect(contract.letters).toEqual({
      yes: LEDGER_YES,
      no: LEDGER_NO,
      unknown: LEDGER_UNKNOWN,
      no_distance: '-',
    })
  })

  it('格型与 schema 版本对得上（换格型/换字母表 ⇒ 读侧必须整块不画）', () => {
    expect(contract.grid).toBe(LEDGER_GRID)
    expect(contract.schema_version).toBe(LEDGER_SCHEMA_VERSION)
  })

  it('键名集与 `render_cells_ledger` 发出的那份完全一致（多一个少一个都算漂）', () => {
    expect([...Object.keys(SAMPLE)].sort()).toEqual([...contract.keys].sort())
  })
})

describe('cellsLedgerOf：验形，不猜', () => {
  it('合规样本 ⇒ 取得到', () => {
    expect(cellsLedgerOf(withLedger(SAMPLE))).not.toBeNull()
  })

  it('缺整个键 ⇒ null（`ev-2` 之前的报告与离线骨架走这一支，图层不出现）', () => {
    expect(cellsLedgerOf({} as LivingCircleReport)).toBeNull()
    expect(cellsLedgerOf({ caliber: {} } as LivingCircleReport)).toBeNull()
  })

  // 每一档都是一次真实的坏法：截断、越字母表、换格制、版本漂、行数与 n 不符。
  const broken: Array<[string, (l: CellsLedgerRaw) => unknown]> = [
    ['n 改成偶数', (l) => ({ ...l, n: 4 })],
    ['少一行矩阵', (l) => ({ ...l, inside: l.inside.slice(0, 2) })],
    ['行长与 n 不符', (l) => ({ ...l, verdict: ['01', '010', '010'] })],
    ['字母表外的字符', (l) => ({ ...l, 'present.market': ['0?0', '101', '010'] })],
    ['格型不是 square', (l) => ({ ...l, grid: 'h3' })],
    ['schema 版本不是这一代', (l) => ({ ...l, schema_version: 99 })],
    ['距离行少一个记号', (l) => ({ ...l, 'nearest.market': ['- 320', '410 1180 260', '- 300 -'] })],
    ['距离记号不是整数也不是 `-`', (l) => ({ ...l, 'nearest.market': ['- 32.5 -', '410 1180 260', '- 300 -'] })],
    ['半径被写成 0', (l) => ({ ...l, radius_m: 0 })],
    ['矩阵键整个缺失', (l) => { const c = { ...l } as Record<string, unknown>; delete c['judge.primary']; return c }],
  ]
  it.each(broken)('坏法「%s」⇒ null（不得按"缺的那格算没事"继续画）', (_label, mutate) => {
    expect(cellsLedgerOf(withLedger(mutate(SAMPLE)))).toBeNull()
  })
})

describe('cellVerdict：只读字符，五档结论与第三态各就各位', () => {
  for (const want of contract.expected_cells) {
    it(`(${want.i},${want.j}) ⇒ ${want.verdict}`, () => {
      const got = cellVerdict(withLedger(SAMPLE), [want.i, want.j])
      expect(got).not.toBeNull()
      expect(got!.verdict).toBe(want.verdict)
      expect(got!.classes.map((c) => ({
        key: c.key, evidence: c.evidence, hit: c.hit, nearestM: c.nearestM,
      }))).toEqual(want.classes)
    })
  }

  it('`present=.` 的类必须读成 `hit=null`，**不是** `false`（判不了 ≠ 没有）', () => {
    const unknownCell = cellVerdict(withLedger(SAMPLE), [1, 0])!
    const primary = unknownCell.classes.find((c) => c.key === 'primary')!
    expect(primary.evidence).toBe(false)
    expect(primary.hit).toBeNull()
    expect(primary.nearestM).toBeNull()
  })

  it('格阵外的坐标 ⇒ null（不许回落到最近的一格）', () => {
    expect(cellVerdict(withLedger(SAMPLE), null)).toBeNull()
    expect(cellVerdict(withLedger(SAMPLE), [9, 9])).toBeNull()
    expect(cellVerdict(withLedger(SAMPLE), [-1, 0])).toBeNull()
  })
})

describe('cellAt：格阵换算与后端同一把尺', () => {
  for (const c of contract.cell_at.cases) {
    it(`${JSON.stringify(c.lnglat)} ⇒ ${JSON.stringify(c.cell)}`, () => {
      expect(cellAt(withLedger(SAMPLE), c.lnglat as [number, number])).toEqual(c.cell)
    })
  }

  it('索引 → 格心 → 索引 必须回到原地（往返不漂，否则点中的格与卡片说的不是一格）', () => {
    for (let i = 0; i < SAMPLE.n; i += 1) {
      for (let j = 0; j < SAMPLE.n; j += 1) {
        expect(cellIndex(SAMPLE, cellCenter(SAMPLE, i, j))).toEqual([i, j])
      }
    }
  })
})

describe('那把尺的文案取自产物，不写死 1km', () => {
  it('样本半径 1000m', () => {
    expect(judgeRulerLabel(withLedger(SAMPLE))).toContain('1000m')
  })

  it('换档到 800m ⇒ 文案跟着变（写死就会图上 800m 圆旁边标 1km）', () => {
    expect(judgeRulerLabel(withLedger({ ...SAMPLE, radius_m: 800 }))).toContain('800m')
  })

  it('没有台账但盲区条目自带尺 ⇒ 用它（1a 不依赖台账，可先发）', () => {
    const lc = { caliber: {}, blindspots: [{ radius_m: 700 }] } as unknown as LivingCircleReport
    expect(judgeRulerM(lc)).toBe(700)
    expect(judgeRulerLabel(lc)).toContain('700m')
  })

  it('两把尺并存时以台账为准（两者本应相等，B13 在背后钉着）', () => {
    const lc = {
      caliber: { cells_ledger: SAMPLE },
      blindspots: [{ radius_m: 700 }],
    } as unknown as LivingCircleReport
    expect(judgeRulerM(lc)).toBe(SAMPLE.radius_m)
  })

  it('既没台账也没声明 ⇒ null（不猜一个默认半径上屏）', () => {
    expect(judgeRulerLabel({} as LivingCircleReport)).toBeNull()
    expect(judgeRulerM({ caliber: {}, blindspots: [{}] } as unknown as LivingCircleReport)).toBeNull()
  })
})

/**
 * T6/E1 · 轻量 QR 编码器验证（对照 segno 参考实现矩阵，逐模块比对）。
 *
 * 参考：`fixtures/qr_ref.json` 由 segno（error='m'，byte 模式）生成，
 * 覆盖 v3/v4/v5 与中文 UTF-8 内容——与前端分享链接（ASCII URL + 中文标题）同分布。
 */
import { describe, it, expect } from 'vitest'
import { qrMatrix } from '../lib/qrcode'
import ref from './fixtures/qr_ref.json'

interface RefCase {
  text: string
  version: number
  size: number
  mask: number
  matrix: number[][]
}

describe('lib/qrcode · 对照 segno 参考矩阵', () => {
  const cases = ref as unknown as RefCase[]
  it('fixtures 载入（5 个参考用例）', () => {
    expect(cases.length).toBe(5)
    for (const c of cases) expect(c.matrix.length).toBe(c.size)
  })

  it.each(cases)('$text → v$version 矩阵逐模块一致', (c) => {
    const qr = qrMatrix(c.text)
    expect(qr.version).toBe(c.version)
    expect(qr.size).toBe(c.size)
    expect(qr.mask).toBe(c.mask)
    expect(qr.modules.length).toBe(c.size)
    let diff = 0
    for (let y = 0; y < c.size; y++) {
      for (let x = 0; x < c.size; x++) {
        if (qr.modules[y][x] !== (c.matrix[y][x] === 1)) diff++
      }
    }
    expect(diff).toBe(0)
  })

  it('超长文本（>v6-M 容量）抛错而非静默截断', () => {
    expect(() => qrMatrix('x'.repeat(200))).toThrow(/容量不足|过长/)
  })
})

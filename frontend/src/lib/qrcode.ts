/**
 * 轻量 QR 编码器（T6/E1 · 报告分享二维码）。
 *
 * 实现范围：byte 模式 + ECC M（中纠错）+ 自动版本 v1-v6 + 自动掩码。
 * 容量：v6-M 可容纳 ≤105 字节（分享链接 ~50-70 字符，足够）。
 * 零依赖（不引 qrcode 之类重库）；输出 1/0 矩阵，由调用方绘制到 canvas。
 *
 * 结构（ISO/IEC 18004）：
 *   finder / 分隔符 / timing / 对齐图案 / 格式信息 / 数据码字（分块 RS 纠错 + 交织）。
 * 版本 ≥7 需要 version info 块，本实现上限 v6，故不涉及。
 */
export interface QrMatrix {
  /** 边长（21 + 4×(version-1)） */
  size: number
  version: number
  /** 选中的掩码 0-7 */
  mask: number
  /** row-major 布尔矩阵，true=深色模块 */
  modules: boolean[][]
}

/* ── 纠错表（ECC M）：每块数据码字数 / 每块 ECC 码字数 / 分块数 ──
 * 对照 ISO 18004 Table 13-22（M 级）。v1-v6 单双块交替，无需 group2 列。 */
const ECC_M = [
  { dataPerBlock: 16, eccPerBlock: 10, blocks: 1 }, // v1
  { dataPerBlock: 28, eccPerBlock: 16, blocks: 1 }, // v2
  { dataPerBlock: 44, eccPerBlock: 26, blocks: 1 }, // v3
  { dataPerBlock: 32, eccPerBlock: 18, blocks: 2 }, // v4
  { dataPerBlock: 43, eccPerBlock: 24, blocks: 2 }, // v5
  { dataPerBlock: 27, eccPerBlock: 16, blocks: 4 }, // v6
]

/* 对齐图案中心坐标（v2-v6；不含三个角，与标准表一致） */
const ALIGN_POS: Record<number, number[]> = {
  2: [6, 18],
  3: [6, 22],
  4: [6, 26],
  5: [6, 30],
  6: [6, 34],
}

/* 格式信息串（5 位格式位 + 10 位 BCH 纠错，已含掩码 XOR；M 级 mask 0-7） */
const FORMAT_M: Record<number, number> = {
  0: 0b101010000010010,
  1: 0b101000100100101,
  2: 0b101111001111100,
  3: 0b101101101001011,
  4: 0b100010111111001,
  5: 0b100000011001110,
  6: 0b100111110010111,
  7: 0b100101010100000,
}

/* 余位（remainder bits）数：v1=0，v2-6=7（矩阵放置时以 0 填充，无需单独使用） */

/* ── GF(256) 里德-所罗门 ─────────────────────────────── */
function gfMul(a: number, b: number): number {
  let r = 0
  let x = a
  let y = b
  while (y) {
    if (y & 1) r ^= x
    y >>>= 1
    x <<= 1
    if (x & 0x100) x ^= 0x11d
  }
  return r
}

function rsGenerator(degree: number): number[] {
  // 生成多项式 ∏(x + α^i), i=0..degree-1；系数按升幂（常数项在前）
  let poly = [1]
  let ap = 1 // α^i（GF 累乘，α=2）
  for (let i = 0; i < degree; i++) {
    const next = new Array(poly.length + 1).fill(0)
    for (let j = 0; j < poly.length; j++) {
      // ×x
      next[j + 1] ^= poly[j]
      // ×α^i
      next[j] ^= gfMul(poly[j], ap)
    }
    poly = next
    ap = gfMul(ap, 2)
  }
  return poly
}

function rsRemainder(data: number[], divisorDesc: number[]): number[] {
  // 降幂合成除法（Nayuki 约定）：divisorDesc 隐含最高次系数 1，长度 = degree
  const result = new Array(divisorDesc.length).fill(0)
  for (const b of data) {
    const factor = b ^ result[0]
    result.shift()
    result.push(0)
    for (let i = 0; i < divisorDesc.length; i++) {
      result[i] ^= gfMul(divisorDesc[i], factor)
    }
  }
  return result
}

/* ── 数据码字组装 ───────────────────────────────────── */
function encodeData(text: string, version: number): { data: number[]; totalCodewords: number } {
  const bytes = new TextEncoder().encode(text)
  const cap = ECC_M[version - 1].dataPerBlock * ECC_M[version - 1].blocks
  if (bytes.length > cap) {
    throw new Error(`QR v${version}-M 容量不足（${bytes.length} > ${cap} 字节），URL 过长`)
  }
  const bits: number[] = []
  const pushBits = (val: number, n: number) => {
    for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1)
  }
  pushBits(0b0100, 4) // byte 模式
  pushBits(bytes.length, 8) // v1-9 字符数占 8 位
  for (const b of bytes) pushBits(b, 8)
  // 终止符 + 补位字节
  pushBits(0, Math.min(4, (cap * 8) - bits.length))
  while (bits.length % 8 !== 0) bits.push(0)
  const data: number[] = []
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i + j]
    data.push(byte)
  }
  const pad = [0xec, 0x11]
  for (let i = 0; data.length < cap; i++) data.push(pad[i % 2])
  return { data, totalCodewords: data.length + ECC_M[version - 1].eccPerBlock * ECC_M[version - 1].blocks }
}

function pickVersion(text: string): number {
  const bytes = new TextEncoder().encode(text).length
  const needBits = 12 + bytes * 8 // 模式(4) + 字符数(8, v1-9) + 数据字节
  for (let v = 1; v <= 6; v++) {
    if (needBits <= ECC_M[v - 1].dataPerBlock * ECC_M[v - 1].blocks * 8) return v
  }
  throw new Error('分享链接过长，无法生成二维码（>105 字节）')
}

/* 分块 + RS 纠错 + 交织 */
function buildCodewords(data: number[], version: number): number[] {
  const { dataPerBlock, eccPerBlock, blocks } = ECC_M[version - 1]
  // 生成多项式降幂存储（隐含最高次系数 1，长度 = degree）
  const genDesc = rsGenerator(eccPerBlock).slice(0, eccPerBlock).reverse()
  const blockData: number[][] = []
  const blockEcc: number[][] = []
  for (let b = 0; b < blocks; b++) {
    const chunk = data.slice(b * dataPerBlock, (b + 1) * dataPerBlock)
    blockData.push(chunk)
    blockEcc.push(rsRemainder(chunk, genDesc))
  }
  const out: number[] = []
  for (let i = 0; i < dataPerBlock; i++) {
    for (let b = 0; b < blocks; b++) out.push(blockData[b][i])
  }
  for (let i = 0; i < eccPerBlock; i++) {
    for (let b = 0; b < blocks; b++) out.push(blockEcc[b][i])
  }
  return out
}

/* 功能图形判定（数据码字放置 / 掩码共用；格式信息区也计入，格式位在掩码后写入） */
function isFunction(x: number, y: number, size: number, version: number): boolean {
  if (x === 6 || y === 6) return true
  const inFinder = (fx: number, fy: number) => x >= fx - 1 && x <= fx + 7 && y >= fy - 1 && y <= fy + 7
  if (inFinder(0, 0) || inFinder(size - 7, 0) || inFinder(0, size - 7)) return true
  if (version >= 2) {
    for (const cy of ALIGN_POS[version]) {
      for (const cx of ALIGN_POS[version]) {
        if ((cx === 6 && cy === 6) || (cx === 6 && cy === size - 7) || (cx === size - 7 && cy === 6)) continue
        if (Math.abs(x - cx) <= 2 && Math.abs(y - cy) <= 2) return true
      }
    }
  }
  // 格式信息区（位 8 上下两行 + 左列/上行）
  if (y === 8 && x >= 0 && x <= 8) return true
  if (x === 8 && y >= 0 && y <= 8) return true
  if (y === 8 && x >= size - 8 && x < size) return true
  if (x === 8 && y >= size - 7 && y < size) return true
  // 固定暗模块（右下角上方）
  if (x === 8 && y === size - 8) return true
  return false
}

/* ── 矩阵绘制 ───────────────────────────────────────── */
function buildMatrix(version: number, codewords: number[]): boolean[][] {
  const size = 21 + 4 * (version - 1)
  const m: boolean[][] = Array.from({ length: size }, () => new Array(size).fill(false))
  const set = (x: number, y: number, v: boolean) => {
    m[y][x] = v
  }

  const drawFinder = (tlx: number, tly: number) => {
    // 7×7 finder（tlx..tlx+6，外圈深色 + 中心 3×3 深色）+ 四周 1 模块浅色分隔符
    for (let dy = -1; dy <= 7; dy++) {
      for (let dx = -1; dx <= 7; dx++) {
        const x = tlx + dx
        const y = tly + dy
        if (x < 0 || y < 0 || x >= size || y >= size) continue
        const inCore = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6
        const ring = inCore && (dx === 0 || dy === 0 || dx === 6 || dy === 6)
        set(x, y, ring)
      }
    }
    // 中心 3×3 实心（dx=2..4）
    for (let dy = 2; dy <= 4; dy++) {
      for (let dx = 2; dx <= 4; dx++) {
        const x = tlx + dx
        const y = tly + dy
        if (x >= 0 && y >= 0 && x < size && y < size) set(x, y, true)
      }
    }
  }

  // finder（左上/右上/左下），分隔符保持浅色
  drawFinder(0, 0)
  drawFinder(size - 7, 0)
  drawFinder(0, size - 7)

  // timing
  for (let i = 8; i < size - 8; i++) {
    set(i, 6, i % 2 === 0)
    set(6, i, i % 2 === 0)
  }

  // alignment（v≥2）
  if (version >= 2) {
    for (const cy of ALIGN_POS[version]) {
      for (const cx of ALIGN_POS[version]) {
        if ((cx === 6 && cy === 6) || (cx === 6 && cy === size - 7) || (cx === size - 7 && cy === 6)) continue
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1)
          }
        }
      }
    }
  }

  // 数据码字蛇形放置（跳过功能区）
  let bit = 0
  const allBits: number[] = []
  for (const c of codewords) for (let i = 7; i >= 0; i--) allBits.push((c >>> i) & 1)
  // 余位补 0
  while (allBits.length < size * size) allBits.push(0)

  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5 // 跳过 timing 列
    const upward = ((right + 1) & 2) === 0
    for (let dy = 0; dy < size; dy++) {
      const y = upward ? size - 1 - dy : dy
      for (let dx = 0; dx < 2; dx++) {
        const x = right - dx
        if (isFunction(x, y, size, version)) continue
        set(x, y, allBits[bit++] === 1)
      }
    }
  }
  // 固定暗模块（恒为深色，不属于任何数据，掩码跳过）
  set(8, size - 8, true)
  return m
}

/* 掩码函数（0-7） */
function applyMask(m: boolean[][], mask: number, version: number): boolean[][] {
  const size = m.length
  const out = m.map((r) => r.slice())
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (isFunction(x, y, size, version)) continue // 掩码只作用于数据模块
      let f = false
      switch (mask) {
        case 0: f = (x + y) % 2 === 0; break
        case 1: f = y % 2 === 0; break
        case 2: f = x % 3 === 0; break
        case 3: f = (x + y) % 3 === 0; break
        case 4: f = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break
        case 5: f = ((x * y) % 2) + ((x * y) % 3) === 0; break
        case 6: f = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break
        case 7: f = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0; break
      }
      if (f) out[y][x] = !out[y][x]
    }
  }
  return out
}

/* 掩码惩罚分（ISO 18004 §8.8.2 规则 1-4；finder 图案检测与规则 4 精确移植 Nayuki，保证掩码选择一致） */
function penalty(m: boolean[][]): number {
  const size = m.length
  const N1 = 3
  const N2 = 3
  const N3 = 40
  const N4 = 10
  let result = 0

  const addHistory = (hist: number[], runLen: number): void => {
    if (hist[0] === 0) runLen += size // 行首虚拟浅色边界
    hist.unshift(runLen)
    hist.pop()
  }
  const countPatterns = (hist: number[]): number => {
    const n = hist[1]
    const core = n > 0 && hist[2] === n && hist[4] === n && hist[5] === n && hist[3] === n * 3
    return (
      (core && hist[0] >= n * 4 && hist[6] >= n ? 1 : 0) +
      (core && hist[6] >= n * 4 && hist[0] >= n ? 1 : 0)
    )
  }
  const terminateAndCount = (hist: number[], color: boolean, runLen: number): number => {
    if (color) {
      addHistory(hist, runLen)
      runLen = 0
    }
    runLen += size // 行尾虚拟浅色边界
    addHistory(hist, runLen)
    return countPatterns(hist)
  }

  // 规则 1 + 规则 3（行 / 列）
  const scanLine = (get: (i: number) => boolean): void => {
    let runColor = false
    let runLen = 0
    const hist = [0, 0, 0, 0, 0, 0, 0]
    for (let i = 0; i < size; i++) {
      if (get(i) === runColor) {
        runLen++
        if (runLen === 5) result += N1
        else if (runLen > 5) result += 1
      } else {
        addHistory(hist, runLen)
        if (!runColor) result += countPatterns(hist) * N3
        runColor = get(i)
        runLen = 1
      }
    }
    result += terminateAndCount(hist, runColor, runLen) * N3
  }
  for (let y = 0; y < size; y++) {
    scanLine((x) => m[y][x])
  }
  for (let x = 0; x < size; x++) {
    scanLine((y) => m[y][x])
  }

  // 规则 2：2×2 同色块
  for (let y = 0; y < size - 1; y++) {
    for (let x = 0; x < size - 1; x++) {
      const v = m[y][x]
      if (v === m[y][x + 1] && v === m[y + 1][x] && v === m[y + 1][x + 1]) result += N2
    }
  }

  // 规则 4：暗模块比例（Nayuki 整数式）
  let dark = 0
  for (const row of m) for (const c of row) if (c) dark++
  const total = size * size
  const k = Math.floor((Math.abs(dark * 20 - total * 10) + total - 1) / total) - 1
  result += Math.max(0, k) * N4
  return result
}

/* 格式信息写入（两份拷贝，M 级 mask 串来自 FORMAT_M；位序 LSB-first，同 ISO/Nayuki） */
function writeFormat(m: boolean[][], mask: number): void {
  const size = m.length
  const bits = FORMAT_M[mask]
  const bitAt = (i: number) => ((bits >>> i) & 1) === 1
  // 第一份：左上（绕 finder 左下 → 右）
  for (let i = 0; i <= 5; i++) m[i][8] = bitAt(i)
  m[7][8] = bitAt(6)
  m[8][8] = bitAt(7)
  m[8][7] = bitAt(8)
  for (let i = 9; i <= 14; i++) m[8][14 - i] = bitAt(i)
  // 第二份：右上/左下
  for (let i = 0; i <= 7; i++) m[8][size - 1 - i] = bitAt(i)
  for (let i = 8; i <= 14; i++) m[size - 15 + i][8] = bitAt(i)
}

/** 生成 QR 矩阵（byte 模式，ECC M，自动版本与掩码）。 */
export function qrMatrix(text: string): QrMatrix {
  const version = pickVersion(text)
  const { data } = encodeData(text, version)
  const codewords = buildCodewords(data, version)
  const base = buildMatrix(version, codewords)

  let best: { m: boolean[][]; mask: number; score: number } | null = null
  for (let mask = 0; mask < 8; mask++) {
    const masked = applyMask(base, mask, version)
    writeFormat(masked, mask)
    const score = penalty(masked)
    if (!best || score < best.score) best = { m: masked, mask, score }
  }
  return { size: base.length, version, mask: best!.mask, modules: best!.m }
}

/** 绘制到 canvas（quietZone 默认 4 模块留白）。 */
export function drawQrToCanvas(canvas: HTMLCanvasElement, text: string, scale = 4, quietZone = 4): void {
  const qr = qrMatrix(text)
  const size = (qr.size + quietZone * 2) * scale
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, size, size)
  ctx.fillStyle = '#000000'
  for (let y = 0; y < qr.size; y++) {
    for (let x = 0; x < qr.size; x++) {
      if (qr.modules[y][x]) ctx.fillRect((x + quietZone) * scale, (y + quietZone) * scale, scale, scale)
    }
  }
}

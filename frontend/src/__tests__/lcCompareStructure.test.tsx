// @vitest-environment jsdom
/**
 * L-GUARD-2 · `/compare` 结构基线（范式照 L-GUARD-1，但基线是**这一页自己的**）
 *
 * ## 为什么不能拿体检台那份比
 * `预览与计划/生活圈-体检台布局落地计划-B-v1.md:597-598` 早写明这页结构不同：体检台的几何风险在
 * **百分比高度链**（`lg:h-full` / `minmax(0,1fr)`，多包一层整页塌），而这页是竖排卡片流，风险在别处：
 *  ① **卡片顺序＝读者顺序**（六笔一路往中间插节：逐类目 → 门槛 → 形状 → 盲区 → 参照列）；
 *  ② **地图槽必须定高**（`h-[440px]` / `h-[400px]`；BMapGL canvas 按父容器像素高撑开，
 *     在这页写成 `h-full` 就是零高）；
 *  ③ **两条呈现分支各自成立**（同片 → 一张图叠加；跨城 → 两张图各居其城 + 归一化示意）。
 *     3c 之后两条都挂三颗解释层开关，那排开关的**条件式必须还是同一份**，所以两条都钉它。
 * 这里不钉 `lg:grid-rows` —— 那在这页压根不存在，钉它是空判。
 *
 * ## 采到哪、不采哪
 * 只采页面骨架：卡片标题序列（DOM 顺序）+ 地图那张卡片的子树（depth ≤ `maxDepth`）。
 * 走到地图槽（class 带 `h-[440px]`/`h-[400px]`）就**停下不往下钻**，只记一层数 ——
 * 画布内部是图层的事，已由 `lcLayerRoster` / `lcCellLayer` / `lcReportLocalMap` 三处守着，
 * 让它进基线只会把"数据换了"误报成"结构变了"。
 * 卡片身份取**卡内第一行标题文本**，不给生产码加 testid（同一页多个同名无障碍名的教训在前）。
 *
 * ## 就绪门（同 L-GUARD-1，被踩过两次）
 * `LcMap` 异步：`boot` 态先渲染 live 容器，拿不到 AK 才改渲染降级画布 ⇒
 * 只认已落定的降级画布，并显式要求 `data-lc-map` 不在。早一秒晚一秒取到的是两棵不同的树。
 *
 * ## 重采是显式动作
 * `LC_COMPARE_CAPTURE=1 npx vitest run src/__tests__/lcCompareStructure.test.tsx` 才重写
 * `fixtures/lcCompareStructure.json`；重写前**先打印结构差分**再落盘 —— 让"重采"是一次可见的记账。
 *
 * ## 重采那一趟的已知现象
 * 采集模式**先跑测试再落盘**，而 `import baseline` 取的是重写前那份 ⇒ 首采或加字段那一趟，
 * "正对照"那组会先红一次（它读到的还是旧结构），紧接着正常跑就绿。这不是判据坏，
 * 是"重采必须让人看见差分"的代价 —— 别把它读成"基线不可信"。
 *
 * ## 效力上限
 * 只证明结构与 class 不变。像素与真实排版仍归计划 B-v1 的 2.2 与 `e2e/lcComparePage.spec.ts`。
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import ComparePage from '../pages/ComparePage'
import { useDataModeStore } from '../store/dataModeStore'
import baseline from './fixtures/lcCompareStructure.json'

const MAX_DEPTH = (baseline.maxDepth as number) ?? 3
const CAPTURE = process.env.LC_COMPARE_CAPTURE === '1'
const FIXTURE_FILE = join(process.cwd(), 'src', '__tests__', 'fixtures', 'lcCompareStructure.json')
/** 定高地图槽：既是这一页的硬不变量，也是"到此为止"的边界。 */
const MAP_SLOT = /h-\[(440|400)px\]/

type Tree = Record<string, unknown> & { kids?: Tree[] }

function node(el: Element): Tree {
  const out: Tree = { tag: el.tagName, class: el.getAttribute('class') ?? '' }
  for (const attr of ['aria-label', 'role', 'type', 'checked']) {
    const v = el.getAttribute(attr)
    if (v != null) out[attr] = v
  }
  return out
}

function subtree(el: Element, depth: number): Tree {
  const out = node(el)
  if (depth >= MAX_DEPTH) return out
  if (MAP_SLOT.test(String(out.class))) {
    out.stop = 'map-slot'                 // 画布内部不进基线（见文件头"采到哪、不采哪"）
    out.kidCount = el.children.length
    return out
  }
  const kids = Array.from(el.children).map((c) => subtree(c, depth + 1))
  if (kids.length) out.kids = kids
  return out
}

const cards = () => [...document.querySelectorAll('main [class*="rounded-card"]')]

/** 卡片标题＝卡内第一个"短且非纯数字"的文本节点（标题行都这么写，不依赖 testid）。 */
function cardTitle(el: Element): string {
  const walk: Element[] = [el, ...Array.from(el.querySelectorAll('*'))]
  for (const n of walk) {
    const own = Array.from(n.childNodes)
      .filter((c) => c.nodeType === 3)
      .map((c) => (c.textContent ?? '').trim())
      .join(' ')
    if (own && own.length <= 24 && !/^\d+(\.\d+)?$/.test(own)) return own
  }
  return '(无名卡)'
}

/** 卡片往上到 `main` 的祖先链 —— "在卡片外面多包一层"只有这条链看得见。 */
function ancestorsOf(el: Element): Tree[] {
  const chain: Tree[] = []
  let cur: Element | null = el
  while (cur && cur.tagName !== 'BODY') {
    chain.unshift(node(cur))
    if (cur.tagName === 'MAIN') break
    cur = cur.parentElement
  }
  return chain
}

function captureBranch(mapCardTitle: string) {
  const order = cards().map(cardTitle)
  const hit = cards().find((el) => cardTitle(el) === mapCardTitle)
  expect(hit, `找不到标题为「${mapCardTitle}」的卡片 ⇒ 卡片改名或顺序变了`).toBeTruthy()
  return { order, ancestors: ancestorsOf(hit as Element), mapCard: subtree(hit as Element, 0) }
}

function renderCompare() {
  return render(
    <MemoryRouter initialEntries={['/compare']}>
      <Routes>
        <Route
          path="/compare"
          element={
            <div className="min-h-screen bg-bg">
              <main className="mx-auto max-w-[1180px]"><ComparePage /></main>
            </div>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

/** 等 N 张图全部落定到降级画布（本环境唯一稳定态）。 */
async function settle(expectMaps: number) {
  await waitFor(() => {
    const settled = [...document.querySelectorAll('[data-lc-mode]')]
      .filter((e) => e.getAttribute('data-lc-mode') !== 'boot')
    expect(settled.length, `${expectMaps} 张图都该落定（boot 没结束 ⇒ 基线取到半棵树）`).toBe(expectMaps)
  })
  expect(document.querySelector('[data-lc-map]'), '还没从 boot 的 live 容器落定').toBeNull()
}

function writeBranch(branch: 'cross' | 'co', value: unknown) {
  const cur = JSON.parse(readFileSync(FIXTURE_FILE, 'utf-8'))
  writeFileSync(FIXTURE_FILE, JSON.stringify({ maxDepth: MAX_DEPTH, ...cur, [branch]: value }, null, 2) + '\n')
}

/** 人可读逐节点差分（与 L-GUARD-1 同形：给人看账，不做最小编辑距离）。 */
function diffNode(exp: Tree, got: Tree, path: string, out: string[]): void {
  for (const key of new Set([...Object.keys(exp), ...Object.keys(got)])) {
    if (key === 'kids') continue
    if (exp[key] !== got[key]) out.push(`${path} · ${key}: ${JSON.stringify(exp[key])} → ${JSON.stringify(got[key])}`)
  }
  const a = exp.kids ?? []
  const b = got.kids ?? []
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const at = `${path}/${(b[i] ?? a[i])?.tag ?? '?'}[${i}]`
    if (!a[i]) out.push(`${at} · 新增子节点 class=${JSON.stringify(b[i].class ?? '')}`)
    else if (!b[i]) out.push(`${path}/${a[i].tag}[${i}] · 少掉子节点 class=${JSON.stringify(a[i].class ?? '')}`)
    else diffNode(a[i] as Tree, b[i] as Tree, at, out)
  }
}

beforeAll(() => useDataModeStore.setState({ mode: 'fixture' }))
afterEach(cleanup)

const CROSS_CARD = 'A / B 所在城市等时圈 · 真实地理位置'
const CO_CARD = '同图叠加 · 等时圈对比'

describe('/compare 结构基线 · 跨城那一对（双图分支）', () => {
  it('卡片序列 + 地图卡骨架逐节点相同', async () => {
    renderCompare()
    await settle(2)
    const got = captureBranch(CROSS_CARD)
    if (CAPTURE) {
      const out: string[] = []
      const exp = (baseline.cross ?? {}) as { mapCard?: Tree; ancestors?: Tree[] }
      if (exp.mapCard) diffNode(exp.mapCard, got.mapCard, 'cross.mapCard', out)
      for (let i = 0; i < Math.max((exp.ancestors ?? []).length, got.ancestors.length); i++)
        diffNode((exp.ancestors ?? [])[i] ?? {}, got.ancestors[i] ?? {}, `cross.ancestors[${i}]`, out)
      writeBranch('cross', got)
      console.info(`[LC_COMPARE_CAPTURE] cross 已重写（${got.order.length} 张卡）。`
        + (out.length ? `被放行的结构差分 ${out.length} 处：\n  ${out.slice(0, 20).join('\n  ')}` : '与旧基线无差异 ⇒ 这次重写没内容。'))
      return
    }
    expect(got).toEqual(baseline.cross)
  })
})

describe('/compare 结构基线 · 同片那一对（同图叠加分支）', () => {
  it('换成凯里 ev2 × 凯里后：卡片序列 + 那张同框图骨架逐节点相同', async () => {
    renderCompare()
    await settle(2)
    fireEvent.change(document.querySelector('select[aria-label="场景 B"]')!, { target: { value: 'kaili' } })
    await waitFor(() => expect(document.querySelectorAll('[data-lc-mode]')).toHaveLength(1))
    await settle(1)
    const got = captureBranch(CO_CARD)
    if (CAPTURE) {
      const out: string[] = []
      const exp = (baseline.co ?? {}) as { mapCard?: Tree; ancestors?: Tree[] }
      if (exp.mapCard) diffNode(exp.mapCard, got.mapCard, 'co.mapCard', out)
      for (let i = 0; i < Math.max((exp.ancestors ?? []).length, got.ancestors.length); i++)
        diffNode((exp.ancestors ?? [])[i] ?? {}, got.ancestors[i] ?? {}, `co.ancestors[${i}]`, out)
      writeBranch('co', got)
      console.info(`[LC_COMPARE_CAPTURE] co 已重写（${got.order.length} 张卡）。`
        + (out.length ? `被放行的结构差分 ${out.length} 处：\n  ${out.slice(0, 20).join('\n  ')}` : '与旧基线无差异 ⇒ 这次重写没内容。'))
      return
    }
    expect(got).toEqual(baseline.co)
  })
})

describe('正对照：两份基线都不是空壳', () => {
  /** 下限取实测值留余量：cross 18 / co 15 个节点。低于它＝采集时机退化成半棵树。 */
  const FLOOR: Record<'cross' | 'co', number> = { cross: 14, co: 12 }
  /** 这一页的地图槽张数：跨城两张（各居其城）、同片一张（真实叠加）。 */
  const SLOTS: Record<'cross' | 'co', number> = { cross: 2, co: 1 }
  for (const branch of ['cross', 'co'] as const) {
    it(`${branch}：节点数、定高槽张数、到槽即停、开关排都在`, () => {
      const b = baseline[branch] as { order: string[]; mapCard: Tree } | undefined
      expect(b, `${branch} 基线不存在 ⇒ 首采没跑过（先 LC_COMPARE_CAPTURE=1 采一次）`).toBeTruthy()
      const flat = JSON.stringify(b)
      const n = (flat.match(/"tag":/g) || []).length
      expect(n, `${branch} 只有 ${n} 个节点，低于下限 ${FLOOR[branch]}`).toBeGreaterThan(FLOOR[branch])
      expect(flat, `${branch} 里没有定高地图槽 ⇒ 这一页的硬不变量丢了`).toMatch(/h-\[\d+px\]/)
      const stops = (flat.match(/"stop":\s*"map-slot"/g) || []).length   // 紧凑 stringify：冒号后没空格
      expect(stops, `${branch} 在地图槽处停下 ${stops} 次，应为 ${SLOTS[branch]} 张槽`).toBe(SLOTS[branch])
      // 3c 之后两条分支都挂那排开关；开关排不在基线里＝这一支又变成"摆着没反应"或整排丢了
      const boxes = (flat.match(/"type":\s*"checkbox"/g) || []).length
      expect(boxes, `${branch} 基线里没有解释层开关`).toBe(3)
      expect(b!.order.length, '卡片序列太短 ⇒ 采到的不是整页').toBeGreaterThan(8)
      const anc = (b as unknown as { ancestors: Tree[] }).ancestors
      expect(anc.length, `${branch} 没有祖先链 ⇒ 卡片外面多包一层就看不见（L-GUARD-1 的教训）`).toBeGreaterThan(1)
      expect(anc[0].tag, `${branch} 祖先链该从滚动容器 main 起` ).toBe('MAIN')
    })
  }
  it('两条分支的卡片序列不同（同图那支没有"归一化示意"那张卡）', () => {
    const cross = (baseline.cross as { order: string[] }).order
    const co = (baseline.co as { order: string[] }).order
    expect(cross).not.toEqual(co)
    expect(cross.join('|')).not.toContain(CO_CARD)
    expect(co.join('|')).not.toContain(CROSS_CARD)
    expect(cross.join('|')).toContain('归一化')
    expect(co.join('|')).not.toContain('归一化')
  })
})

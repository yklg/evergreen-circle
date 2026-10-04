// @vitest-environment jsdom
/**
 * L-GUARD-1 · 舞台结构基线（抽件的护栏；`fixtures/lcStageStructure.json` 是裁决者）
 *
 * ## 它守的是什么
 *
 * 体检台的几何靠 `lg:h-full` / `lg:min-h-0` / `grid-rows-[minmax(0,1fr)]` 这套 utility 成立，
 * 而**百分比高度按父层解析** —— 抽 `LcStage` 只要多包一层 div，整页几何就变了。
 * 本仓测试环境没有渲染步（2026-10-04 实测：内置面板里 `requestAnimationFrame` 3.6 秒 0 帧），
 * 像素量不了；但 jsdom 给得了**树**。于是把"层级与 class 有没有变"变成一个可判定的等式：
 *
 *  - `ancestors`：从 `main`（AppLayout 的滚动容器）一路记到两栏容器 —— 这条链就是
 *    百分比高度的解析上下文，包一层立刻红；
 *  - `split`：两栏往下 depth 2 的子树（地图格 / 图例 / 右栏四张卡的 tag+class）。
 *
 * ## 就绪门（这条被踩过两次，写死在这儿）
 *
 * `LcMap` 是异步的：`boot` 态渲染 live 分支的容器（带 `data-lc-map`），拿不到 AK 后**改渲染
 * 降级 SVG 画布**（`data-lc-map` 消失）。所以"容器出现"或"画布出现"这种或门**不稳定** ——
 * 早一秒晚一秒取到的是两棵不同的树。这里只认已落定的降级画布，并显式要求 `data-lc-map` 不在。
 *
 * ## 效力上限
 *
 * 只证明**结构与 class 不变**。"像素因此不变"是推论（同祖先链 + 同类 + 同层级 ⇒ 同解析），
 * 真实渲染表现仍归计划 B-v1 的 2.2。
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import LifeCirclePage from '../pages/LifeCirclePage'
import { useDataModeStore } from '../store/dataModeStore'
import baseline from './fixtures/lcStageStructure.json'

const MAX_DEPTH = baseline.maxDepth as number

function node(el: Element): Record<string, unknown> {
  const out: Record<string, unknown> = { tag: el.tagName, class: el.getAttribute('class') ?? '' }
  for (const attr of ['aria-label', 'role', 'aria-expanded']) {
    const v = el.getAttribute(attr)
    if (v != null) out[attr] = v
  }
  return out
}

function subtree(el: Element, depth: number): Record<string, unknown> {
  const out = node(el)
  if (depth >= MAX_DEPTH) return out
  const kids = Array.from(el.children).map((c) => subtree(c, depth + 1))
  if (kids.length) out.kids = kids
  return out
}

/** 从滚动容器 `main` 记到两栏容器的祖先链 —— 百分比高度的解析上下文 */
function ancestorsOf(split: Element): Record<string, unknown>[] {
  const chain: Record<string, unknown>[] = []
  let cur: Element | null = split
  while (cur && cur.tagName !== 'BODY') {
    chain.unshift(node(cur))
    if (cur.tagName === 'MAIN') break
    cur = cur.parentElement
  }
  return chain.reverse()
}

function renderStage() {
  return render(
    <MemoryRouter initialEntries={['/life-circle/kaili-ev2']}>
      <Routes>
        <Route
          path="/life-circle/:sceneId"
          element={
            <div className="flex h-screen w-screen overflow-hidden bg-bg">
              <main className="relative min-w-0 flex-1 overflow-y-auto">
                <LifeCirclePage />
              </main>
            </div>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

/** 等 LcMap 落定到降级画布：这是本环境唯一的稳定态 */
async function settle() {
  await waitFor(() => expect(document.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
  expect(document.querySelector('[data-lc-map]'), '还没从 boot 的 live 容器落定').toBeNull()
  const split = document.querySelector('main div div[class*="lg:grid-rows-"]')
  expect(split, '找不到两栏容器（类里已无 lg:grid-rows）').not.toBeNull()
  return split as Element
}

beforeAll(() => useDataModeStore.setState({ mode: 'fixture' }))
afterEach(cleanup)

describe('舞台结构必须与抽件前基线逐节点相同', () => {
  it('祖先链 + 两栏子树（depth≤' + MAX_DEPTH + '）不变 ⇒ 包一层就红', async () => {
    renderStage()
    const split = await settle()
    expect({ ancestors: ancestorsOf(split), split: subtree(split, 0) })
      .toEqual({ ancestors: baseline.ancestors, split: baseline.split })
  })

  it('正对照：基线确实含关键节点，且不是空壳（否则上面的比对是空过）', () => {
    const flat = JSON.stringify(baseline)
    expect(flat).toContain('lg:grid-rows-[minmax(0,1fr)]')     // 两栏：行高锁成容器高
    expect(flat).toContain('lg:overflow-hidden')               // 页根：大屏接管滚动
    expect(flat).toContain('lg:overflow-y-auto')               // 右栏：内部滚
    expect(flat).toContain('backdrop-blur')                    // 图例浮层在地图格内
    expect(flat).toContain('MAIN')                             // 祖先链一路量到滚动容器
    const n = (flat.match(/"tag":/g) || []).length
    // 三层基线（两栏 → 槽 → 槽内首层）实测 45 个节点；下限取 40，
    // 低于它就说明采集时机或选择器退化成了半棵树，此时上面的等式会变成空过。
    expect(n, `基线只有 ${n} 个节点，太薄`).toBeGreaterThan(40)
  })
})

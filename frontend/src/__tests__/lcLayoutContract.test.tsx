// @vitest-environment jsdom
/**
 * L-CT-1 / L-GUARD-1 · 体检台布局契约（计划 B-v1 的 TC-18、TC-12，及 TC-05/TC-11 两枚红钉）。
 *
 * ## 两类判据为什么分开钉
 *
 * 本轮改动的本体是**排版**：谁给地图高度、谁负责滚动、读数从行式改 2 列 tile。
 * jsdom 没有排版引擎 ⇒ 像素层主张（图例真常驻吗、地图真没被右栏撑高吗）在这一层
 * **测不到**（覆盖评估文档 §四 效力上限，像素层归 TC-21/TC-22）。
 * 所以这里钉两件测得到的事：
 *  ① **class 串逐字不动**（沿用 `recordStatsStripDom.test.tsx:22-31` 的先例）——
 *     滚动/高度所有权现在是靠这四组 utility 表达的，改一个字就得显式处理一次；
 *  ② **读数文本逐字等于生产 label 函数输出**（沿用 `eventFlowNumbersMatchFixture.test.ts`
 *     那条纪律）—— 版式从 9 行改成 2 列 tile 时，最坏的不是难看，是"结构看着对、
 *     数字与图上点数对不上账"，那是本项目真踩过的坑。
 *
 * ## 红钉只留一枚
 *
 * TC-11（S1 · 无界通知区压塌 stage）已在 `LifeCirclePage.tsx:648` 落地并转成普通 `it`。
 * TC-05（S3 · 折叠销毁判读控件）仍未实施，保留 `it.fails` 把已知缺陷钉成可见事实 ——
 * S3 落地后它会反过来报 "Expected to fail, but passed"，提醒把它改回 `it`。
 * 这不是把套件弄脏，也不是掩盖：红钉的意义就是让"以后再说"无处可藏。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import LifeCirclePage from '../pages/LifeCirclePage'
import ev2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import { useDataModeStore } from '../store/dataModeStore'
import {
  blindspotCoverageBrief,
  confidenceBadgeLabel,
  judgeRulerLabel,
  poiMetricLabel,
  samplingReachLabel,
} from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

const SRC = join(process.cwd(), 'src', 'pages', 'LifeCirclePage.tsx')
const src = readFileSync(SRC, 'utf8')

const EV2 = ev2 as unknown as LivingCircleReport
const KAILI = kaili as unknown as LivingCircleReport

/* ── 现状四组布局 utility（逐字抄自 LifeCirclePage.tsx:480,681,683,830） ────────── */
const PAGE_ROOT =
  'mx-auto flex min-h-full max-w-[1240px] flex-col gap-4 px-6 py-6 lg:h-full lg:min-h-0 lg:overflow-hidden'
const SPLIT =
  'grid flex-1 grid-cols-1 gap-4 lg:min-h-0 lg:grid-cols-[1fr_320px] lg:grid-rows-[minmax(0,1fr)]'
const MAP_CELL =
  'relative min-h-[480px] overflow-hidden rounded-card border border-line bg-card shadow-card lg:h-full lg:min-h-0'
const ASIDE =
  'flex flex-col gap-4 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-1'
/* 图例浮层的 `z-10` 不是装饰：BMapGL 注入 `.BMap_mask`（z-index:9）会吞掉勾选点击
   （见 LifeCirclePage.tsx:695-700 的实测注释）。谁把它改回 auto，谁就在真机上摆一个点不动的控件。 */
const LEGEND =
  'absolute left-3 top-3 z-10 flex max-w-[190px] flex-col gap-1.5 rounded-btn border border-line bg-card/90 p-3 backdrop-blur'

/** 出现次数必须恰为 1：0 次是漂移，2 次是有人复制了一份滚动契约。 */
function exactlyOnce(hay: string, needle: string, label: string) {
  const n = hay.split(needle).length - 1
  expect(n, `${label} 出现 ${n} 次（应恰为 1 次）`).toBe(1)
}

function renderScene(sceneId: string) {
  return render(
    <MemoryRouter initialEntries={[`/life-circle/${sceneId}`]}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useDataModeStore.setState({ mode: 'fixture' })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('TC-18 · 布局契约的 class 串逐字钉死', () => {
  it('正对照：源文件确实读到了（否则下面的判据全是空过）', () => {
    expect(src.length).toBeGreaterThan(10_000)
    expect(src).toContain('export default function LifeCirclePage')
  })

  it('页根 / 两栏 / 地图格 / 右栏四组 utility 各出现恰一次', () => {
    exactlyOnce(src, PAGE_ROOT, '页根（大屏接管滚动）')
    exactlyOnce(src, SPLIT, '两栏（行高锁成容器高，杜绝右栏反向撑高）')
    exactlyOnce(src, MAP_CELL, '地图格（高度交给视口）')
    exactlyOnce(src, ASIDE, '右栏（内部滚动）')
  })

  it('图例浮层保持 z-10（压过 .BMap_mask 的 z-index:9）', () => {
    exactlyOnce(src, LEGEND, '图例浮层')
  })

  it('读数改的是版式不是文案：2 列 tile 网格存在且原行式面已撤下', () => {
    expect(src).toContain('<div className="mt-2 grid grid-cols-2 gap-2">')
    expect(src).toContain('<div className="grid grid-cols-2 gap-2">')
    // StatRow 那套「border-b py-1.5」的行式面在体检台里不该再有残留
    expect(src).not.toContain('flex items-center justify-between gap-3 border-b border-line/60 py-1.5')
  })
})

describe('TC-12 · tile 版式下读数文本逐字等于生产 label 函数（ev-2 真跑件）', () => {
  it('九条读数与 label 函数输出逐字相同，不是"看着像"', async () => {
    renderScene('kaili-ev2')
    await screen.findByText('凯里老街 · 生活圈体检单')

    const iso15 = `${(EV2.isochrones.find((z) => z.minutes === 15)!.area_km2).toFixed(2)} km²`
    const cal = EV2.caliber!
    const mustMatch: string[] = [
      poiMetricLabel(EV2),
      samplingReachLabel(EV2),
      iso15,
      `${EV2.blindspots.length} 处`,
      `${cal.speed_m_per_min} m/min`,
      `×${cal.detour_k}`,
      `${cal.study_radius_m} m`,
      cal.iso_minutes.map((m) => `${m}min`).join(' / '),
    ]
    for (const text of mustMatch) {
      expect(screen.getByText(text), `读数「${text}」未上屏`).toBeTruthy()
    }
    // 出行方式是三元链的产物，单独比一次，防止以后有人把"步行"硬编码进 JSX
    expect(screen.getByText('步行')).toBeTruthy()
  })

  it('判盲覆盖度披露 + 降档徽标在 tile 版式下仍与盲区数同屏（不靠位置巧合）', async () => {
    renderScene('kaili-ev2')
    await screen.findByText('凯里老街 · 生活圈体检单')
    const brief = blindspotCoverageBrief(EV2)!
    const badge = confidenceBadgeLabel(EV2)!
    expect(screen.getByText(brief)).toBeTruthy()
    expect(screen.getByText(badge)).toBeTruthy()
    expect(screen.getByText(`${EV2.blindspots.length} 处`)).toBeTruthy()
    // 前提守卫：夹具若变成"全判完"，这两句都该不出现，本用例就白测
    expect(brief).toContain('未判')
  })

  it('三要素 chips 与判定尺那句口径同源（半径取自产物，不写死 1km）', async () => {
    renderScene('kaili-ev2')
    await screen.findByText('凯里老街 · 生活圈体检单')
    for (const t of EV2.scores.triads) {
      expect(screen.getByText(`${t.facility} · 最近 ${t.nearest_minutes}min`)).toBeTruthy()
    }
    const ruler = judgeRulerLabel(EV2)!
    expect(ruler).not.toContain('1000m 的圆，写死')
    expect(screen.getByText(`判盲问的是${ruler}，不是眼前这一小块`)).toBeTruthy()
  })

  it('台账上线前的那份冻结件（kaili）在 tile 版式下不出现台账卡与尺开关', async () => {
    renderScene('kaili')
    await screen.findByText('凯里老街 · 生活圈体检单')
    expect(screen.getByText(poiMetricLabel(KAILI))).toBeTruthy()
    expect(screen.queryByText('逐格台账')).toBeNull()
  })
})

describe('P0 落地状态钉（S1 已转绿 · S3 仍是红钉）', () => {
  // S3 · 折叠实现目前是条件渲染（LifeCirclePage.tsx:722-774），收起时判定尺/证据域
  // 勾选连同 DOM 一起消失 —— 与 :695-700「别摆一个勾不动的控件」是同一条纪律的两面。
  it.fails('TC-05：图例折叠按钮应报出展开态，且折叠不销毁判读控件', async () => {
    renderScene('kaili-ev2')
    await screen.findByText('凯里老街 · 生活圈体检单')
    const fold = screen.getByRole('button', { name: '收起' }) as HTMLButtonElement
    expect(fold.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(fold)
    // 折叠后判定尺勾选仍应可达（当前实现把它整个摘掉，故本支红）
    expect(screen.getByRole('checkbox', { name: /判定尺/ })).toBeTruthy()
  })

  // S1 已落（`LifeCirclePage.tsx:648` 那列加了 `lg:max-h-[22vh] lg:overflow-y-auto`）：
  // 这块按取证轮次逐行增长，页根大屏下已定高不滚，不限高就会把地图格与右栏压向 0 高。
  it('TC-11：可无界增长的通知列自带高度上界并在内部滚', () => {
    const start = src.indexOf('{!isFixture && runActive && (')
    expect(start).toBeGreaterThan(-1)
    const region = src.slice(start, start + 900)
    expect(region).toMatch(/max-h-\[[^\]]+\]\s+overflow-y-auto|overflow-y-auto/)
  })
})

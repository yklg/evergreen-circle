// @vitest-environment jsdom
/**
 * 笔 B · 口径对照环的前端三件事：取值口与那句口径、图例接线（方案②）、两条渲染路径的落图。
 *
 * ## 为什么这三层都要测
 * 这条链上有三种各自独立的坏法，缺哪只眼睛都发现不了另外两种：
 *  ① **文案没有出处** —— 阈值写死 8，口径表改一次屏幕就说一次谎；分母借 20min 圈，
 *     16% 会被说成 9%。所以句子里每个数都必须能追到载荷。
 *  ② **接线是条件渲染** —— 载荷没发（骑行/驾车档、离线件、早于本口径的存量件）时
 *     那一整块必须不出现；摆一个点开没内容的折叠标题，等于摆一个假入口。
 *  ③ **勾了要真画** —— 判定尺当年就是只有 live 分支有实现、降级画布零落点，那颗开关在
 *     降级态点下去毫无反应而全套件没人能发现（`judgeScaleCanvas.test.tsx` 的来由）。
 *     所以这里 live 与降级**两档各测一次**。
 *
 * ## 措辞纪律也在判据里
 * 「两把尺的对比」不能只写在注释里：主语一旦滑到人群，屏幕上就是一句对具体居民的能力断言。
 * 所以有一条现扫 `src/components` + `src/pages` 的短语禁令（按目录扫，不点名文件）。
 *
 * ## 效力上限
 * jsdom 没有排版引擎（`getBoundingClientRect` 恒 0×0），"折叠标题会不会把图例撑到内滚"
 * 这条**不在这里销账** —— 那是 Playwright 的活（`e2e/stageChecks.ts` 图例底边那四条）。
 * live 档"勾一次会不会把视野弹走"已经在这里钉住（假件把每次地图方法调用记了账，零网络常驻）；
 * 而"那条虚线在真机上到底画没画出来、吃不吃鼠标事件"**这里证不了**，10-06 由一次性真机 spike
 * 答过（`skip/tmp/iso_compare_live_spike*.mjs`：真实例回读 dashed/#B45309/35 点、overlay +1、
 * 中心与缩放逐字不动、`e.overlay === ring` 为 false），它要真 AK＋外网 ⇒ 不适合当常驻守卫。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import kailiFixture from '../mocks/fixtures/livingCircle/kaili.json'
import { useDataModeStore } from '../store/dataModeStore'
import type { IsoCompare, LivingCircleReport } from '../types'
import { LC_ISO_COMPARE_COLOR, isoCompareLabel, isoCompareOf } from '../lib/livingCircle'
import { instances, mapConfig, resetInstances } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')
const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')

const KAILI = kailiFixture as unknown as LivingCircleReport

/** 环上的点不必是真形状，只要是**闭合**的一圈（首尾同点、≥4 点）—— 契约判的就是这个。 */
function cmpLike(center: [number, number], over: Partial<IsoCompare> = {}): IsoCompare {
  const [lng, lat] = center
  const dLat = 300 / 111320
  const dLng = 300 / (111320 * Math.cos((lat * Math.PI) / 180))
  const ring: [number, number][] = Array.from({ length: 12 }, (_, i) => {
    const a = (i / 12) * Math.PI * 2
    return [lng + dLng * Math.cos(a), lat + dLat * Math.sin(a)]
  })
  ring.push([ring[0][0], ring[0][1]])
  return {
    minutes: 8,
    geojson: { type: 'Polygon', coordinates: [ring] },
    area_km2: 0.255,
    basis: '口径对照（非第五档）：文献 5–8min，取区间保守侧 8min',
    claim: 'caliber_comparison_only',
    ...over,
  }
}

const RING_LEN = cmpLike(KAILI.scene.center).geojson.coordinates[0].length

const withCmp = (over: Partial<IsoCompare> = {}): LivingCircleReport =>
  ({ ...KAILI, iso_compare: cmpLike(KAILI.scene.center, over) }) as unknown as LivingCircleReport

const withoutCmp = (): LivingCircleReport => {
  const rest: Record<string, unknown> = { ...KAILI }
  delete rest.iso_compare
  return rest as unknown as LivingCircleReport
}

beforeEach(() => {
  cleanup()
  resetInstances()
  useDataModeStore.setState({ mode: 'fixture' })
  mapConfig.browserAk = 'test-ak'          // 有 AK ⇒ LcMap 走 live；降级档的用例各自清空它
})

/** 降级画布不是 prop，是**内部 mode**：没有浏览器 AK 时才落到那条路径（与 judgeScaleCanvas 同法） */
function renderFallback(report: LivingCircleReport, showIsoCompare: boolean = true) {
  mapConfig.browserAk = ''
  return render(<LcMap report={report} showIsoCompare={showIsoCompare} />)
}

/** 假件注册表没有类型（它是测试替身），这里只声明用例真正关心的那几个入参，
 *  不用 any 把断言对象糊掉 —— 糊掉之后 `enableClicking` 拼错也会绿。 */
type FakePoly = {
  opts?: { strokeColor?: string; strokeStyle?: string; enableClicking?: boolean; fillOpacity?: number }
}

/**
 * 从假件的 poly 注册表里挑出**这条环**。
 *
 * 按描边色认，**不按 `strokeStyle`**：盲区面在 `LcMap.tsx:795` 也是 `dashed`，而主绘制 effect
 * 声明在环之前 ⇒ 按线型 `find` 会先撞上别人那一层，等于拿别人的属性给自己作证（第一版就是这么写的）。
 */
function ringPolys(): FakePoly[] {
  return (instances.polys as unknown as FakePoly[]).filter((q) => q.opts?.strokeColor === LC_ISO_COMPARE_COLOR)
}

describe('① 取值口与那句口径', () => {
  it('夹具现在带着这一位（10-06 烘的），且数值与生产常量同源', () => {
    const c = KAILI.iso_compare
    expect(c, '演示态夹具没带 iso_compare ⇒ 评审用的那一态永远看不到这一层，B 等于没上屏').toBeTruthy()
    expect(c!.claim).toBe('caliber_comparison_only')
    expect(c!.minutes).toBe(8)
    expect(c!.area_km2).toBeGreaterThan(0)
    // basis 的判据是"说了出处、也说了这不是能力断言"，且**三份夹具逐字同一条**
    // （前端没有那份常量的副本 —— 有副本才是问题；逐字相同证明它来自同一个写口）
    expect(c!.basis).toContain('5–8min')
    expect(c!.basis).toContain('不构成对任何具体个体')
    const bases = ['kaili.json', 'kaili-ev2.json', 'beijing-jinsong.json'].map(
      (n) => JSON.parse(readFileSync(join(process.cwd(), 'src/mocks/fixtures/livingCircle', n), 'utf-8'))
        .living_circle?.iso_compare?.basis
        ?? JSON.parse(readFileSync(join(process.cwd(), 'src/mocks/fixtures/livingCircle', n), 'utf-8'))
          .iso_compare?.basis)
    expect(new Set(bases).size, '三份夹具的 basis 各不相同 ⇒ 有人在夹具里各抄了一份').toBe(1)
    expect(isoCompareOf(KAILI)).toBe(c)
    expect(isoCompareLabel(KAILI)).toContain('0.255')
  })

  it('把这一位剥掉 ⇒ 取值为 null（缺席的语义仍然是"不渲染"，不是"渲染成 0"）', () => {
    const bare = withoutCmp()
    expect(isoCompareOf(bare)).toBeNull()
    expect(isoCompareLabel(bare)).toBeNull()
  })

  it('齐备 ⇒ 句子里两个数都来自载荷，百分比的分母是 15min 那一档', () => {
    const lc = withCmp()
    const fifteen = (lc.isochrones ?? []).find((z) => z.minutes === 15)
    expect(fifteen).toBeTruthy()
    const text = isoCompareLabel(lc) ?? ''
    expect(text).toContain('8')
    expect(text).toContain('0.255')
    expect(text).toContain(`是 15 分钟圈的 ${Math.round((0.255 / fifteen!.area_km2) * 100)}%`)
  })

  it('阈值改成 6，句子里就不该再有那个 8（钉"不写死"）', () => {
    const text = isoCompareLabel(withCmp({ minutes: 6 })) ?? ''
    expect(text).toContain('6')
    expect(text).not.toMatch(/\b8\b/)
  })

  it('没有 15min 档 ⇒ 退化成不带百分比的那句，不借别的档当分母', () => {
    const lc = { ...withCmp(), isochrones: (KAILI.isochrones ?? []).filter((z) => z.minutes !== 15) }
    const text = isoCompareLabel(lc as unknown as LivingCircleReport) ?? ''
    expect(text).toContain('两把尺的对比')
    expect(text).not.toContain('%')
  })

  it.each([
    ['缺 claim', { claim: undefined }],
    ['claim 是能力断言', { claim: 'elderly_capability' }],
    ['面积为 0', { area_km2: 0 }],
    ['阈值非数', { minutes: Number.NaN }],
    ['环是空数组', { geojson: { type: 'Polygon', coordinates: [[]] } }],
  ])('%s ⇒ 整位不可用（null，不是 0、不是"暂无"）', (_label, over) => {
    const lc = withCmp(over as Partial<IsoCompare>)
    expect(isoCompareOf(lc)).toBeNull()
    expect(isoCompareLabel(lc)).toBeNull()
  })
})

describe('② 图例接线（方案②：常驻的只有标题，勾选与副行点开才出现）', () => {
  /**
   * 页面在演示态有**两条取数路径**（`LifeCirclePage.tsx:327` 直接取 `SAMPLE_COMMUNITIES[0].report`，
   * 只有另一支走 `getLifeCircleMock`），所以这里不靠 mock 造"缺席"——造不干净，
   * 只会得到一支能剥、一支剥不掉的假可控。缺席语义由 ①（`isoCompareLabel` 返回 null）
   * 与 ③（载荷没这一位 ⇒ 两档都不画）测，那两处才是这句话真正的归属层。
   * 出厂夹具 10-06 起自带这一位 ⇒ 这里测的就是**评审那一态**。
   */
  const renderScene = () => render(
    <MemoryRouter initialEntries={['/life-circle/kaili']}>
      <Routes>
        <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
      </Routes>
    </MemoryRouter>,
  )

  it('演示态出厂件 ⇒ 折叠标题真的在，且默认收起（勾选项根本不在 DOM 里）', async () => {
    renderScene()
    const head = (await screen.findByText('更多口径对比')).closest('button')
    expect(head).not.toBeNull()
    expect(head!.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('口径对照环（文献阈值）')).toBeNull()
  })

  it('点标题 ⇒ 展开、勾选项出现且默认未勾；那句口径的数来自出厂夹具；再点收起', async () => {
    renderScene()
    fireEvent.click(await screen.findByText('更多口径对比'))
    const label = screen.getByText('口径对照环（文献阈值）').closest('label')
    expect(label!.textContent).toContain('0.255')       // 环面积：出厂夹具自己的数
    expect(label!.textContent).toContain('16%')         // 分母是 15min 档（0.255/1.562）
    const box = label!.querySelector('input[type="checkbox"]') as HTMLInputElement
    expect(box.checked).toBe(false)
    fireEvent.click(box)
    expect(box.checked).toBe(true)
    fireEvent.click(screen.getByText('更多口径对比'))
    expect(screen.queryByText('口径对照环（文献阈值）')).toBeNull()
  })
})

describe('③ 落图：live 与降级两档都要画得出来', () => {
  it('降级画布：勾了才有那一层，且只描边不填充、与四档实线拉开', async () => {
    const { container } = renderFallback(withCmp())
    // 降级画布是**异步**出现的（mode 先 boot，拿不到 AK/脚本才落 fallback）⇒ 同步查会读到空
    await waitFor(() => expect(container.querySelector('[data-lc-iso-compare]')).not.toBeNull())
    const g = container.querySelector('[data-lc-iso-compare]')
    const poly = g!.querySelector('polygon')!
    expect(poly.getAttribute('points')!.trim().split(/\s+/)).toHaveLength(RING_LEN)
    expect(poly.getAttribute('fill')).toBe('none')       // 填充会压掉五级等时圈色阶
    expect(poly.getAttribute('stroke')).toBe(LC_ISO_COMPARE_COLOR)
    expect(poly.getAttribute('stroke-dasharray')).toBeTruthy()
  })

  it('降级画布：不勾 ⇒ 整层缺席（不是画一条透明的骗过判据）', async () => {
    const { container } = renderFallback(withCmp(), false)
    await waitFor(() => expect(container.querySelector('svg')).not.toBeNull())   // 画布在，层不在
    expect(container.querySelector('[data-lc-iso-compare]')).toBeNull()
  })

  it('降级画布：载荷没发这一位 ⇒ 勾了也不画、也不报错', async () => {
    const { container } = renderFallback(withoutCmp())
    await waitFor(() => expect(container.querySelector('svg')).not.toBeNull())
    expect(container.querySelector('[data-lc-iso-compare]')).toBeNull()
  })

  it('live：走 bmap.Polygon，且 enableClicking:false + fillOpacity:0（不吃点击、不压色阶）', async () => {
    render(<LcMap report={withCmp()} showIsoCompare />)
    await waitFor(() => expect(ringPolys().length).toBe(1))
    // 假件注册表没有类型（它是测试替身），这里只声明本用例真正关心的那几个入参，
    // 不用 any 把断言对象糊掉 —— 糊掉之后 `enableClicking` 拼错也会绿。
    const [cmp] = ringPolys()
    expect(cmp.opts?.enableClicking).toBe(false)
    expect(cmp.opts?.fillOpacity).toBe(0)
    expect(cmp.opts?.strokeStyle).toBe('dashed')
  })

  /**
   * 相机不动这条，是 10-06 真机 spike 里唯一**不需要真 AK** 就能常驻的一条，所以留在这儿。
   *
   * 机制：主绘制 effect 的 deps 里没有 `showIsoCompare`，但它收尾那句是
   * `centerAndZoom(center, 15)`（`LcMap.tsx:1067`）⇒ 谁哪天图省事把对照环**并进**那个 effect，
   * 屏幕上就是"每勾一次图例，地图跳回中心 15 级"。真 AK 那条 e2e 在 CI 里恒 skip（拿不到
   * 网络和 key 就自我跳过、报表里还算通过），守不住这件事；这里假件把每次方法调用都记了账，
   * 于是同一句话可以零网络常驻。
   *
   * 恒真防线照 `lifeCircleForensicUi.test.tsx:297` 那条：先钉"挂载时确实复位过"，
   * 否则"次数没变多"会因为一次都没发生而恒成立。
   */
  it('live：勾一次只多一条线，不复位相机（视图开关不许并进主绘制 effect）', async () => {
    const CAM = new Set(['centerAndZoom', 'setViewport', 'panTo', 'setZoom', 'flyTo'])
    // 三次渲染必须喂**同一份** report 对象：主 effect 的 deps 里有 `report`，每轮现造一个新
    // 对象会让它照常重跑并复位相机，那条就测不出"是不是勾选项触发的"（第一版红在此，2≠1）。
    const lc = withCmp()
    const { rerender } = render(<LcMap report={lc} />)
    await waitFor(() => expect(instances.maps.length).toBe(1))
    const map = instances.maps[0] as { calls: [string, unknown[]][] }
    const camMoves = () => map.calls.filter(([m]) => CAM.has(m)).length
    await waitFor(() => expect(camMoves()).toBeGreaterThan(0)) // 前提守卫：一次都没动过 ⇒ 下面恒真
    const before = camMoves()
    expect(ringPolys()).toHaveLength(0)

    rerender(<LcMap report={lc} showIsoCompare />)
    await waitFor(() => expect(ringPolys()).toHaveLength(1))
    expect(camMoves(), '勾开就把相机复位了 ⇒ 环被并进了主绘制 effect').toBe(before)

    rerender(<LcMap report={lc} />)
    await waitFor(() => expect(instances.removed).toContain(ringPolys()[0])) // 摘干净，不留残影
    expect(camMoves(), '取消勾选同样不该动视野').toBe(before)
  })

  /**
   * 上一条的**正对照**（红先审判据与台架）：数相机次数的这把尺，得在相机真动的时候真的数到。
   *
   * 这里不动盘上的生产文件，而是走一条**真实存在**的触发链：每轮换一个新 `report` 对象 ⇒
   * 主绘制 effect 的 deps 变化 ⇒ 它照常重跑并 `centerAndZoom`。上一条用例红过一次（2≠1）就是
   * 这条链，把它固化下来当反证 —— 否则"次数没变多"可能只是因为那个计数器根本看不见调用。
   */
  it('正对照：换了 report 对象（主 effect 照常重跑）⇒ 那条判据必须数到相机复位', async () => {
    const CAM = new Set(['centerAndZoom', 'setViewport', 'panTo', 'setZoom', 'flyTo'])
    const { rerender } = render(<LcMap report={withCmp()} />)
    await waitFor(() => expect(instances.maps.length).toBe(1))
    const map = instances.maps[0] as { calls: [string, unknown[]][] }
    const camMoves = () => map.calls.filter(([m]) => CAM.has(m)).length
    await waitFor(() => expect(camMoves()).toBeGreaterThan(0))
    const before = camMoves()

    rerender(<LcMap report={withCmp()} />) // ← 新对象，等同"勾一次把环并进主 effect"的效果
    await waitFor(() => expect(camMoves()).toBeGreaterThan(before))
  })
})

describe('④ 措辞纪律（现扫组件与页面，不点名文件）', () => {
  const BANNED = ['老人只能', '老年人只能', '老人走不到', '高龄人群实际只能', '老年人实际只能']

  function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const full = join(dir, name)
      if (statSync(full).isDirectory()) return walk(full)
      return /\.(ts|tsx)$/.test(name) ? [full] : []
    })
  }

  it('不许出现"把口径写成人群能力"的句式', () => {
    const files = [join(process.cwd(), 'src/components'), join(process.cwd(), 'src/pages')].flatMap(walk)
    expect(files.length, '扫描面为空 ⇒ 这条判据在空转').toBeGreaterThan(20)
    for (const file of files) {
      const src = readFileSync(file, 'utf-8')
      for (const b of BANNED) {
        expect(`${file}::${src}`, `${file} 出现禁用句式「${b}」`).not.toContain(b)
      }
    }
  })
})

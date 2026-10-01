/**
 * 守卫 · 从 BMap 事件里取坐标只许走 `lib/geo` 那一处出口
 *
 * 起因（真机第一轮，2026-10-01）：`LcMap.tsx` 的地图点选格写了 `e.latLng.lng()`，
 * 而 BMapGL 事件上的 `latLng` 给的是 `{lng, lat}` **属性**不是方法 —— 那一行当场抛
 * TypeError，把整个 click handler 打死：不但不选格，连既有的「点空白关卡」一起失灵。
 *
 * 为什么值域闸与 TypeScript 都没拦住：类型是我自己就地声明的（`{ lng(): number }`），
 * 编译器只会照着那个**错的**形状点头。⇒ 这类"自行声明第三方对象形状"必须靠静态守卫拦，
 * 不能靠类型系统。
 *
 * 判据形状对齐本仓既有静态守卫（`archiveSourceGuards` / `domainEnumSingleSource`）：
 * 先钉一条"读到的是真文件"的可达性对照，再钉否定式判据，最后用旧文案做反向对照
 * 证明这判据真的有牙。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')
const read = (rel: string): string => readFileSync(join(SRC, rel), 'utf8')

/** 剥掉整行注释与块注释 —— 本文件的判据就写在注释里，不剥会自己判自己红（假红）。 */
const codeOnly = (text: string): string => text
  .split('\n')
  .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
  .join('\n')

/** 这条判据：把方法式取值当违规。 */
const METHOD_CALL = /\.\s*(?:lng|lat|lnglat)\s*\(\s*\)/

describe('BMap 事件坐标取值（只许走 toDiagPair + asBdLngLatOrNull）', () => {
  const lcMap = read('components/lifecircle/LcMap.tsx')

  it('正面对照：读到的是真文件，且两条出口都在用', () => {
    expect(lcMap.length).toBeGreaterThan(1000)
    expect(lcMap).toContain('toDiagPair')
    expect(lcMap).toContain('asBdLngLatOrNull')
  })

  it('剥注释后本文件不再出现方法式取坐标', () => {
    const hits = codeOnly(lcMap).split('\n').filter((l) => METHOD_CALL.test(l))
    expect(hits).toEqual([])
  })

  it('反向对照：出事那一行喂给同一判据必须变红', () => {
    // 不这么钉，"扫不到违规"可能只是因为判据写空了或路径指错了。
    expect(METHOD_CALL.test('  const cell = cellIndex(led, [e.latLng.lng(), e.latLng.lat()])')).toBe(true)
  })

  it('地图点选那条链路只经 `lib/geo` 的唯一出口，且出口两案字段名都试', () => {
    // 出事的是"猜第三方对象的字段名"。所以钉三件：click handler 不自己解字段、
    // 那个出口两案都试（GL 地图级事件是内部名 `latlng`，覆盖物事件才是 `latLng`）、
    // 出口内部仍走值域闸且失败不静默。
    const body = lcMap.slice(lcMap.indexOf('const onBlankClick'), lcMap.indexOf("map.addEventListener('click'"))
    expect(body).toContain('bmapEventLngLat(e, ')
    expect(METHOD_CALL.test(body)).toBe(false)

    const geo = codeOnly(read('lib/geo.ts'))
    const helper = geo.slice(geo.indexOf('export function bmapEventLngLat'), geo.indexOf('export function describeBMapEvent'))
    expect(helper).toContain("'latlng'")
    expect(helper).toContain("'latLng'")
    expect(helper).toContain('parseBdLngLat(toDiagPair(')
    expect(helper).toContain('rejectBdLngLatSource(')   // 全落空要报真实键名，不许静默
  })
})

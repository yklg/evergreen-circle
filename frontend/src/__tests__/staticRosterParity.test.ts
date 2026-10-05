// @vitest-environment node
/**
 * 静态名册一致性 + 离线回落不得跨域借册。
 *
 * 两条都是被实测逼出来的：
 * 1. `public/assets/experts.json` 曾手工抄写且**整本漂移** —— 里面装的是生活圈人设
 *    （48/48 姓名与后端 travel 名册不同，L3-001 静态=温叙白、后端=沈砚）。
 * 2. 生活圈域原本**没有**静态名册，而 `fetchExperts` 最后一行无条件回落
 *    `/assets/experts.json` ⇒ 后端不可达时生活圈拿到旅游人设，且完全静默。
 *
 * 判据形状沿用 `silentFallbackGuard.test.ts` 的"集合相等、两向都钉"：
 * 静态文件既不能比后端旧（漂移），也不能凭空多出后端没有的人。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

import { fetchExperts } from '../lib/api'
import type { ExpertDomainName } from '../store/expertStore'

const FRONTEND = process.cwd()
const PAIRS: [ExpertDomainName, string, string][] = [
  ['travel', '../backend/app/data/experts.json', 'public/assets/experts.json'],
  ['living_circle', '../backend/app/data/experts_living_circle.json', 'public/assets/experts/living_circle.json'],
]

const load = (rel: string) => JSON.parse(readFileSync(join(FRONTEND, rel), 'utf8')) as { id: string; name: string }[]

describe('静态名册必须与后端名册同源', () => {
  for (const [domain, src, dst] of PAIRS) {
    it(`${domain}：静态文件存在且逐 id 与后端一致`, () => {
      expect(existsSync(join(FRONTEND, dst)), `缺静态名册 ${dst} ⇒ 跑 scripts/gen-static-rosters.mjs`).toBe(true)
      const backend = load(src)
      const statics = load(dst)
      expect(statics).toHaveLength(backend.length)
      expect(new Set(statics.map((e) => e.id))).toEqual(new Set(backend.map((e) => e.id)))
      const byId = new Map(statics.map((e) => [e.id, e.name]))
      const drifted = backend.filter((e) => byId.get(e.id) !== e.name).map((e) => `${e.id} 静态=${byId.get(e.id)} 后端=${e.name}`)
      expect(drifted, `静态名册漂移：${drifted.slice(0, 4).join('；')}`).toEqual([])
    })
  }

  it('两域同 id 必须是不同姓名（借册才会可被察觉）', () => {
    const t = new Map(load(PAIRS[0][1]).map((e) => [e.id, e.name]))
    const l = new Map(load(PAIRS[1][1]).map((e) => [e.id, e.name]))
    const same = [...t.keys()].filter((id) => t.get(id) === l.get(id))
    expect(same, `这些 id 在两域同名，取错域将无法从人名察觉：${same.join('、')}`).toEqual([])
  })
})

describe('fetchExperts 离线回落', () => {
  const realFetch = globalThis.fetch
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })
  afterEach(() => {
    globalThis.fetch = realFetch
  })

  it('后端不可达时读本域静态名册，绝不读另一本', async () => {
    const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mock.mockImplementation(async (url: string) => {
      if (String(url).includes('/api/experts')) throw new Error('backend down')
      return { ok: true, json: async () => load(PAIRS[1][2]) } as Response
    })
    const list = await fetchExperts('living_circle')
    expect(list[0].name).toBe('温叙白')
    const asked = mock.mock.calls.map((c) => String(c[0]))
    expect(asked.some((u) => u.endsWith('/assets/experts.json')), `生活圈域去借了 travel 静态册：${asked.join(' ')}`).toBe(false)
  })

  it('本域静态册也取不到 ⇒ 抛错，不返回另一本人设', async () => {
    const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    mock.mockImplementation(async (url: string) => {
      if (String(url).includes('/api/experts')) throw new Error('backend down')
      return { ok: false, json: async () => [] } as Response
    })
    await expect(fetchExperts('living_circle')).rejects.toThrow(/专家名册不可用/)
  })
})

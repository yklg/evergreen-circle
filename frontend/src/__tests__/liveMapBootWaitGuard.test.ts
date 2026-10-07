// @vitest-environment node
import { mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * 防回潮守卫（task 23 第 3 步）：live 侧「地图建出来了没有」这句等待，全仓只许有一颗出口
 * —— `helpers/waitDrawn.ts`。
 *
 * 为什么只钉 `maps`：各测试文件里 `waitFor(... instances.circles.length ...)` 那类是**判据**
 * （"勾开必须建 2 枚环"），不是启动等待，语法上分不开、也不该禁。而"等地图建出来"这件事
 * 此前被抄成 7 份、深浅不一（只等 maps 的那些，在 CPU 被抢时会对着还没挂监听/还没画过的对象
 * 动作），10-07 台架实测干净树三路并发 15 遍红 6 遍。收成一颗之后，谁再抄一份就当场红。
 */
const TESTS_DIR = join(process.cwd(), 'src', '__tests__')
const SCAFFOLD_PREFIX = '.tmp-guard-bootwait-'
/** 本文件自己：那段正则、用例标题和正对照里的字符串样例都会被这条规则命中 ⇒ 必须排除，
 *  否则守卫一上线就红在三行自己身上（第一次跑就是这个读数）。 */
const SELF = 'liveMapBootWaitGuard.test.ts'

/** 违规形状：同一行里既 `waitFor(` 又手写 `.maps.length`。 */
const BOOT_WAIT = /waitFor\(.*\.maps\.length/

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      // 正对照自造的脚手架不能进负扫描：并发跑全量时 A 写的假违规会被 B 抓到（#22 同一颗雷）。
      if (name.startsWith(SCAFFOLD_PREFIX) || name === 'node_modules') continue
      out.push(...walk(full))
    } else if (/\.(ts|tsx)$/.test(name)) {
      if (name === SELF) continue
      out.push(full)
    }
  }
  return out
}

function scanForBootWait(root: string): string[] {
  const hits: string[] = []
  for (const file of walk(root)) {
    const lines = readFileSync(file, 'utf-8').split('\n')
    lines.forEach((line, n) => {
      if (BOOT_WAIT.test(line)) hits.push(`${file.slice(root.length + 1)}:${n + 1} ${line.trim()}`)
    })
  }
  return hits
}

describe('live 侧启动等待 · 唯一出口守卫', () => {
  it('src/__tests__ 下不许再有手写的 waitFor(... .maps.length ...)', () => {
    expect(scanForBootWait(TESTS_DIR), '等地图建出来请走 helpers/waitDrawn.ts，别再抄一份（深浅会不一致）').toEqual([])
  })

  it('故意写一次手写等待 ⇒ 守卫必须转红（正对照）', () => {
    // 目录名带 pid：两个进程共用固定名时，finally 的 rmSync 会删掉对方正在用的那份。
    const tmp = join(TESTS_DIR, `${SCAFFOLD_PREFIX}${process.pid}`)
    mkdirSync(tmp, { recursive: true })
    const fake = join(tmp, 'BadMount.tsx')
    try {
      writeFileSync(
        fake,
        'const x = 1\nawait waitFor(() => expect(instances.maps.length).toBe(1))\nexport default x\n',
        'utf-8',
      )
      // 以脚手架目录自己为根来扫：负扫描跳过 `.tmp-guard-*`，若还从 TESTS_DIR 扫，
      // 这条正对照就成了「扫的东西根本不在范围内」⇒ 静默空转，比红更坏。
      const hits = scanForBootWait(tmp)
      expect(hits.map((h) => h.split(':')[0])).toEqual(['BadMount.tsx'])
      expect(hits.join('\n')).toContain('.maps.length')
    } finally {
      rmSync(tmp, { recursive: true, force: true })
    }
  })
})

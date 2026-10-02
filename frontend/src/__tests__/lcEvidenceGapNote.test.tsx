// @vitest-environment jsdom
/**
 * 片 R23-A（乙）·「没查过 / 没查全」那半句在**演示态正文**里的上屏契约。
 *
 * 后端同一组判据在 `backend/tests/test_evidence_gap_note.py`，两端字面量逐字相同的守卫在
 * `backend/tests/test_fixture_mirror.py::test_evidence_gap_note_is_one_text_on_both_ends`。
 * 这份文件只管三件事：①那句话真的被拼进了 `sections[].paragraphs`（不是只活在函数里）；
 * ②**别类的词不许印到本节**；③**达标分支不许说"没查完"**。外加一条回归网：两份出厂夹具今天
 * 一个字都不许多出来。
 *
 * ⚠️ 期望串是**按规格手写的字面量**，不从实现回抄（回抄=恒真）。
 * ⚠️ 注入只动内存里的演示件对象（`SAMPLE_COMMUNITIES[i].report`），磁盘夹具零改动，`finally` 还原；
 *    走的是生产出口 `buildLivingCircleReport()`，不是直调私有函数。
 */
import { describe, it, expect } from 'vitest'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'
import { buildLivingCircleReport } from '../mocks/livingCircleReports'
import type { LivingCircleReport, Report } from '../types'

const TAIL = ' ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。'
const NOTE_BOTH_MED =
  '另需交代：本次有 2 个医疗类检索词因预算未发起（medical:社区医院、medical:社区卫生服务中心）' +
  '；本次有 1 个医疗类检索词发了但没查全（medical:诊所）' + TAIL
const NOTE_EDU = '另需交代：本次有 1 个教育类检索词因预算未发起（education:小学）' + TAIL

/** 换内存里的演示件跑一次真构建，用完立刻还原（磁盘夹具一个字节都不动） */
function buildWith(sceneId: string, mutate: (lc: LivingCircleReport) => void): Report {
  const sample = SAMPLE_COMMUNITIES.find((s) => s.id === sceneId)
  if (!sample) throw new Error(`缺演示件 ${sceneId}`)
  const saved = sample.report
  const clone = structuredClone(saved) as LivingCircleReport
  mutate(clone)
  sample.report = clone
  try {
    const r = buildLivingCircleReport(sceneId)
    if (!r) throw new Error(`buildLivingCircleReport(${sceneId}) 返回 null`)
    return r
  } finally {
    sample.report = saved
  }
}

const setCaliber =
  (patch: Record<string, unknown>) =>
  (lc: LivingCircleReport) => {
    lc.caliber = { ...(lc.caliber ?? {}), ...patch } as LivingCircleReport['caliber']
  }
/** 构造对照：把医疗类压成「门槛项未计满」⇒ 缺口分支才可达（两份演示件的医疗都是 100%） */
const forceMedGap = (lc: LivingCircleReport) => {
  const m = lc.poi.categories.find((c) => c.category === 'medical')
  if (m) {
    m.required_in_circle = 1
    m.coverage = 1 / 3
  }
}
const para = (r: Report, id: string) => (r.sections.find((s) => s.id === id)?.paragraphs ?? [''])[0]

describe('演示态正文里「没查过 / 没查全」那句的上屏契约', () => {
  it('前置：两份出厂夹具今天一个字都不许多出来（回归网）', () => {
    for (const id of ['kaili', 'beijing-jinsong']) {
      const r = buildLivingCircleReport(id) as Report
      for (const sec of ['medical', 'education']) {
        for (const frag of ['因预算未发起', '发了但没查全', '接口自称还有货却断了页', '请求没成',
                            '本轮没有额度', '扩词在到达标线之前']) {
          expect(para(r, sec), `${id}/${sec}：夹具数据没变却印出了「${frag}」⇒ 闸门失效`).not.toContain(frag)
        }
        expect(para(r, sec), `${id}/${sec}`).not.toContain('另需交代：')
      }
    }
  })

  it('两种成因同时命中 ⇒ 医疗节一句里并列，计数与词名都来自载荷', () => {
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({
        evidence_starved_terms: ['medical:社区医院', 'medical:社区卫生服务中心', 'education:小学'],
        evidence_truncated_terms: ['medical:诊所', 'shopping:超市'],
      })(lc)
    })
    expect(para(r, 'medical')).toContain(NOTE_BOTH_MED)
    // R23-B2 撤句之后的读感契约：①那句"停止线按点数"的收尾必须**完全不在**（撤没撤干净
    // 另有全仓扫的那条守卫，见 `test_fixture_mirror.py`）；②同段只许出现**一个**「另需交代：」
    // —— 旧状态下"两次是合法的"那条豁免随撤句作废。
    expect(para(r, 'medical')).not.toContain('不能只读成「社区没有」')
    expect(para(r, 'medical').split('另需交代：').length - 1).toBe(1)
  })

  it('教育节只看见教育自己的词（全类混合表必须按类别筛）', () => {
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({ evidence_starved_terms: ['medical:社区医院', 'education:小学'] })(lc)
    })
    expect(para(r, 'education')).toContain(NOTE_EDU)
    // 插入点也是契约：教育节那句后面还跟着「最近设施…」，不许掉到段落末尾之后
    const at = para(r, 'education').indexOf(NOTE_EDU)
    expect(at).toBeGreaterThan(-1)
    expect(para(r, 'education').slice(at + NOTE_EDU.length)).toContain('最近设施')
  })

  it('反向对照：只有别类有饿词 ⇒ 本节一个字都不加（不许拿别类的账冒充本类结论）', () => {
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({ evidence_starved_terms: ['education:小学'], evidence_truncated_terms: ['shopping:超市'] })(lc)
    })
    expect(para(r, 'medical')).not.toContain('另需交代：本次有')
    // 活证人：同一份载荷在教育节**确实印了** ⇒ 医疗节那句的缺席是"筛掉了"，不是"根本没产"。
    // （撤掉停止线那句之后，医疗节这里再没有别的句子可以兼任这个证人。）
    expect(para(r, 'education')).toContain(NOTE_EDU)
  })

  it('达标分支不印：覆盖度 ≥75% 时，"没查全"不会让"分子已计满"变假话', () => {
    const r = buildWith('beijing-jinsong', (lc) => {
      setCaliber({
        evidence_starved_terms: ['medical:社区医院', 'medical:社区卫生服务中心'],
        evidence_truncated_terms: ['medical:诊所'],
      })(lc)
    })
    expect(para(r, 'medical')).toContain('本节写「达标」')
    expect(para(r, 'medical')).not.toContain('因预算未发起')
    expect(para(r, 'medical')).not.toContain('发了但没查全')
  })

  it('门槛项口径之前的快照（缺 required_in_circle）⇒ 正文照点数说，不挂这句', () => {
    const r = buildWith('kaili', (lc) => {
      const m = lc.poi.categories.find((c) => c.category === 'medical')
      if (m) delete (m as unknown as Record<string, unknown>).required_in_circle
      setCaliber({ evidence_starved_terms: ['medical:社区医院'] })(lc)
    })
    expect(para(r, 'medical')).toContain('这份快照出自门槛项口径之前')
    expect(para(r, 'medical')).not.toContain('因预算未发起')
  })

  it('第三种成因（R23-B1 新键）：整轮没跑过扩词的类才印，别类不印', () => {
    const UNFUNDED = '另需交代：本轮没有额度为这一类扩词（一次都没扩成）' + TAIL
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({ evidence_expansion_unfunded_categories: ['medical'] })(lc)
    })
    expect(para(r, 'medical')).toContain(UNFUNDED)
    // ⚠️ 反向对照必须拿**真句子的片段**去否：原先写的「本轮没跑过任何扩词」在生产件里
    // 根本不存在 ⇒ 类别筛坏掉了它也照样绿。
    expect(para(r, 'education'), '教育类不在这张表里却印了句子 ⇒ 类别筛失效')
      .not.toContain('本轮没有额度为这一类扩词')
    expect(para(r, 'education'), '同上：整段都不许出现').not.toContain('另需交代：本轮没有')
    // 与前两种成因并列时，各条自己完整（分号连接，不许互相吞掉计数）
    const both = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({
        evidence_starved_terms: ['medical:社区医院'],
        evidence_expansion_unfunded_categories: ['medical'],
      })(lc)
    })
    expect(para(both, 'medical')).toContain(
      '另需交代：本次有 1 个医疗类检索词因预算未发起（medical:社区医院）；本轮没有额度为这一类扩词（一次都没扩成）')
  })

  it('第四种成因（R23-B3 新键）：扩到一半没额度的类才印，别类不印', () => {
    const OUT = '另需交代：这一类的扩词在到达标线之前因额度见底中断（扩过词，不是查够了）' + TAIL
    // 形状照 §11 真跑那一格（教育扩满 4 个扩词单位、门槛项仍 1/3）。⚠️ 但真跑重测核出那一格
    // **同时**有 2 个教育类词落在 truncated 里 ⇒ "只有第四种命中"是本例的构造（凯里演示件另三个键**缺席**），
    // 不是 §11 的读数；原先这里写"之前四个键都是空的"是假的（脚本绕过了 bind_evidence 那个唯一注入点）。
    const r = buildWith('kaili', (lc) => {
      setCaliber({ evidence_expansion_out_of_budget_categories: ['education'] })(lc)
    })
    expect(para(r, 'education')).toContain(OUT)
    expect(para(r, 'education').split('另需交代：').length - 1, `前缀长了：${para(r, 'education')}`).toBe(1)
    // 反向对照：把医疗也压成缺口分支（否则它本来就因达标不印，否证恒真），类别筛一坏它就会印
    const med = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({ evidence_expansion_out_of_budget_categories: ['education'] })(lc)
    })
    expect(para(med, 'medical'), '教育的账印到了医疗节头上')
      .not.toContain('这一类的扩词在到达标线之前')
    expect(para(med, 'medical')).not.toContain('另需交代：这一类的扩词')
  })

  it('第二、四种成因并列：两条都在、共用一个前缀（顺序即键序）', () => {
    // 载荷形状 = §19 真跑那一格（教育：2 个词没查全 + 扩词额度见底），屏上这句话是真会印的。
    // ⚠️ 这里不用「unfunded + out_of_budget」凑一对：那两位按 `searched` 是否为 0 分家，
    //    同一类不可能都占（后端 `test_expansion_out_of_budget.py` 第 1 节钉着互斥）⇒
    //    拿永不可达的载荷验"将来上屏的那句话"等于没验（探针 G 档同注）。
    const r = buildWith('kaili', setCaliber({
      evidence_truncated_terms: ['education:幼儿园', 'education:博南高级中学'],
      evidence_expansion_out_of_budget_categories: ['education'],
    }))
    expect(para(r, 'education')).toContain(
      '另需交代：本次有 2 个教育类检索词发了但没查全（education:幼儿园、education:博南高级中学）'
      + '；这一类的扩词在到达标线之前因额度见底中断（扩过词，不是查够了）')
    expect(para(r, 'education').split('另需交代：').length - 1).toBe(1)
  })

  it('并集键（R23-C 新键）在场与否都不改演示态正文 ⇒ 本刀零行为变更', () => {
    const base = { evidence_expansion_out_of_budget_categories: ['education'] }
    const a = buildWith('kaili', setCaliber(base))
    // 故意给一份"并集里写着别的类"的载荷：若措辞哪天改挂到并集上，这两段就会分叉
    const b = buildWith('kaili', setCaliber({
      ...base, coverage_numerator_incomplete_categories: ['medical', 'finance', 'shopping'],
    }))
    expect(para(a, 'education'), '比较两头都得有内容，否则是在比空串')
      .toContain('这一类的扩词在到达标线之前')
    expect(para(b, 'education')).toBe(para(a, 'education'))
    expect(para(b, 'medical')).toBe(para(a, 'medical'))
  })

  it('⑤接口断页单独命中：只印「断了页」，那一句「发了但没查全」不许出现', () => {
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({ evidence_capped_terms: ['medical:诊所'] })(lc)
    })
    expect(para(r, 'medical')).toContain(
      '另需交代：本次有 1 个医疗类检索词接口自称还有货却断了页（medical:诊所）' + TAIL)
    expect(para(r, 'medical'), '断页的词又被说成我们没翻完 ⇒ 归责错位回来了')
      .not.toContain('发了但没查全')
    // 反向对照：教育节达标分支 + 载荷里没有教育类 ⇒ 一个字都不许印
    expect(para(r, 'education')).not.toContain('另需交代：')
  })

  it('⑥请求没成单独命中：只印「请求没成」，也不许说「发了」', () => {
    const r = buildWith('kaili', setCaliber({ evidence_failed_terms: ['education:小学'] }))
    expect(para(r, 'education')).toContain(
      '另需交代：本次有 1 个教育类检索词请求没成（education:小学）' + TAIL)
    // 「发了但没查全」对这一档是假话（那一行可能压根没发出去）⇒ 必须不出现
    expect(para(r, 'education')).not.toContain('发了但没查全')
    expect(para(r, 'education')).not.toContain('断了页')
    expect(para(r, 'medical')).not.toContain('另需交代：')
  })

  it('同一类四种词级成因并列：四条子句共用一个前缀、各报各的数', () => {
    const r = buildWith('kaili', (lc) => {
      forceMedGap(lc)
      setCaliber({
        evidence_starved_terms: ['medical:社区医院'],
        evidence_truncated_terms: ['medical:诊所'],
        evidence_capped_terms: ['medical:药房'],
        evidence_failed_terms: ['medical:医药公司'],
      })(lc)
    })
    const p = para(r, 'medical')
    expect(p.split('另需交代：').length - 1, `前缀长了：${p}`).toBe(1)
    // 只数**那半句**里的分号：整段正文自己就带一个（"圈内 25 处；其中计入分子…"），
    // 拿整段数会把它算进来 ⇒ 判据测的就不再是拼装规则。
    const note = p.slice(p.indexOf('另需交代：'))
    expect(note.split('；').length - 1, `分号数不对：${note}`).toBe(3)
    for (const frag of ['因预算未发起', '发了但没查全', '接口自称还有货却断了页', '请求没成']) {
      expect(note, `${frag} 没上屏：${note}`).toContain(frag)
    }
    // 词名各归各位：断页那句里不许混进"没翻完"的那个词
    expect(p).toContain('断了页（medical:药房）')
    expect(p).toContain('没查全（medical:诊所）')
  })

  it('空表与键缺席都不许回落成「0 个」（前者=查全了、后者=不知道）', () => {
    for (const patch of [{ evidence_starved_terms: [] }, {}]) {
      const r = buildWith('kaili', (lc) => {
        forceMedGap(lc)
        setCaliber(patch)(lc)
      })
      expect(para(r, 'medical')).not.toContain('0 个')
      expect(para(r, 'medical')).not.toContain('另需交代：本次有')
    }
  })
})

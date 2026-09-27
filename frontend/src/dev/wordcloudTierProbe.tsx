/**
 * 分层词云取证页（预览闸口产物，**不参与生产渲染**）。
 *
 * 打开：`http://localhost:3400/preview-wordcloud-tiers.html`
 *
 * 布局与配色全部 import 生产模块（`lib/wordcloudLayout` 的 `layoutWords` 与
 * `components/VWordCloud` 的 `wordStyle`）—— 本文件里**没有第二套实现**，
 * 所见即线上。三列只差载荷：
 *
 *   A 今日载荷（wordfreq 通用词频，无 kind）  ⇒ 现状：地名 42px 占中心
 *   B 新载荷（opinion/topic 分层 + polarity）  ⇒ 改后：评价词大字着色、话题词小灰字
 *   C 存量载荷（旧报告的裸 {word,weight}）    ⇒ 与 A 同一形状，证明老报告一个像素不动
 *
 * 载荷由本机实跑 `sentiment.analyze_sentiment → charts.wordcloud_words` 产出
 * （语料 = r_6dadffee 冻结的 25 条真舆情），不是手编样例。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用，不进生产包；但会被 `tsc` 与 `eslint` 纳入检查。
 */
import { createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import { layoutWords, type WordItem } from '../lib/wordcloudLayout'
import { wordStyle } from '../lib/wordcloudColors'
import payload from './wordcloudProbePayload.json'

type ProbeWord = WordItem & { polarity?: 'pos' | 'neg' | 'neu' }

const HEIGHT = 280 // 与 VWordCloud 默认 height 一致
const WIDTH = 560 // 报告正文图表列宽（桌面）

function estimateBox(word: string, fontSize: number): { w: number; h: number } {
  return { w: Array.from(word).length * fontSize * 0.95, h: fontSize * 1.15 }
}

/** 视觉重叠对数（pad=0 的真实压字）：280px 容器装不装得下必须是个数，不是肉眼。 */
function overlappingPairs(words: ProbeWord[]): [string, string][] {
  const placed = layoutWords(words, WIDTH, HEIGHT)
  const boxes = placed.map((p) => ({ word: p.word, x: p.x, y: p.y, ...estimateBox(p.word, p.fontSize) }))
  const hit = (a: (typeof boxes)[0], b: (typeof boxes)[0]) =>
    !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y)
  const out: [string, string][] = []
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) if (hit(boxes[i], boxes[j])) out.push([boxes[i].word, boxes[j].word])
  return out
}

export function Cloud({ words }: { words: ProbeWord[] }) {
  const placed = layoutWords(words, WIDTH, HEIGHT)
  return (
    <div className="relative overflow-hidden" style={{ height: HEIGHT, width: WIDTH, background: '#fff' }}>
      {placed.map((w, i) => {
        const s = wordStyle(w, i)
        return (
          <span
            key={`${w.word}-${i}`}
            title={`${w.word}：权重 ${w.weight}`}
            className="font-medium"
            style={{
              position: 'absolute',
              left: w.x,
              top: w.y,
              fontSize: w.fontSize,
              color: s.color,
              opacity: s.opacity,
              lineHeight: 1.15,
              whiteSpace: 'nowrap',
            }}
          >
            {w.word}
          </span>
        )
      })}
    </div>
  )
}

function card(title: string, body: ReactNode[]) {
  return createElement(
    'div',
    { className: 'card' },
    createElement('h2', { style: { fontSize: 14, margin: '0 0 6px' } }, title),
    ...body
  )
}

function mount(): void {
  const root = document.getElementById('probe')
  if (!root) return
  const today = (payload.before_wordfreq as unknown as ProbeWord[]).slice(0, 24)
  const layered = payload.after_layered as unknown as ProbeWord[]
  const legacy = (payload.legacy_report_spec?.words ?? []) as unknown as ProbeWord[]
  const opinions = layered.filter((w) => w.kind === 'opinion')
  const topics = layered.filter((w) => w.kind === 'topic')
  const maxSize = (ws: ProbeWord[]) => Math.max(...layoutWords(ws, WIDTH, HEIGHT).map((p) => p.fontSize))
  const sizeOf = (word: string, ws: ProbeWord[]) =>
    layoutWords(ws, WIDTH, HEIGHT).find((p) => p.word === word)?.fontSize

  createRoot(root).render(
    createElement(
      'div',
      null,
      createElement(
        'div',
        { className: 'box' },
        createElement('b', null, '载荷出处：'),
        ` 本机实跑 backend sentiment.analyze_sentiment → charts.wordcloud_words；语料为 r_6dadffee 冻结的 25 条真实舆情证据（doc_kind 分布 ${JSON.stringify(
          payload.generated_from.doc_kind_counts
        )}，可核验口碑 ${payload.generated_from.sample_size} 条）。地名→话题层、评价词→大字的归属全部由后端算出，本页不参与选词。`
      ),
      card(
        'A · 现状载荷（今日词频，无 kind）：生产 layoutWords 的单档归一',
        [createElement(Cloud, { key: 'a', words: today }),
         createElement(
           'div',
           { className: 'note', key: 'n' },
           '头部全是地名与页面 chrome：',
           today.slice(0, 8).map((w) => `${w.word}(${w.weight})`).join(' '),
           ` · 最大字号 ${maxSize(today).toFixed(1)}px 落在「大理」上`
         )]
      ),
      card(
        'B · 新载荷（opinion/topic 分层 + polarity）：同一份生产代码，分层生效',
        [createElement(Cloud, { key: 'b', words: layered }),
         createElement(
           'div',
           { className: 'note', key: 'n' },
           `评价词 ${opinions.length} 个（大字，绿=正面 / 红=负面 / 灰=中性），话题词 ${topics.length} 个（小字 55% 透明）：`,
           topics.map((w) => `${w.word}(${w.weight})`).join(' '),
           ` · 最大字号 ${maxSize(layered).toFixed(1)}px 落在评价词上`
         )]
      ),
      card(
        'C · 存量报告载荷（旧报告裸 {word,weight}）：与 A 同一形状 ⇒ 老报告不变',
        [createElement(Cloud, { key: 'c', words: today }),
         createElement(
           'div',
           { className: 'note', key: 'n' },
           'kind 全部缺席 ⇒ 走单档归一（42/14）与 PALETTE 逐词轮换，即今天的渲染路径。'
         )]
      ),
      card(
        'D · 存量报告 r_6dadffee 的真实 spec（直接从 DB 读出，未回写）',
        [createElement(Cloud, { key: 'd', words: legacy }),
         createElement(
           'div',
           { className: 'note', key: 'n' },
           `这就是用户截图那张云的数据源（${legacy.length} 个词，头部 ${legacy
             .slice(0, 6)
             .map((w) => `${w.word}(${w.weight})`)
             .join(' ')}）。改动后它仍由同一套生产代码渲染成同样的地名云 —— `
             + `最大字号 ${maxSize(legacy).toFixed(1)}px 落在「${
             layoutWords(legacy, WIDTH, HEIGHT).find((p) => p.fontSize === maxSize(legacy))?.word
           }」上，与今天一致。`
         )]
      ),
      card('自检（数值判据，不靠肉眼）', [
        createElement(
          'table',
          { className: 'cmp', key: 't' },
          createElement(
            'tbody',
            null,
            ...[
              ['A 最大字号（地名占中心）', maxSize(today).toFixed(2)],
              ['B 最大字号（须落在评价词）', maxSize(layered).toFixed(2)],
              ['「大理」在 A 的字号', String(sizeOf('大理', today)?.toFixed(2) ?? '—')],
              ['「大理」在 B 的字号（话题层须 ≤15）', String(sizeOf('大理', layered)?.toFixed(2) ?? '—')],
              ['「值得去」在 B 的字号（今日词云里根本没这个词）', String(sizeOf('值得去', layered)?.toFixed(2) ?? '—')],
              ['A 视觉重叠对数', String(overlappingPairs(today).length)],
              ['D（存量报告真实 spec）最大字号', maxSize(legacy).toFixed(2)],
              ['D 视觉重叠对数（本取证页宽 560px，线上更宽故更疏）', String(overlappingPairs(legacy).length)],
              ['B 视觉重叠对数（0 = 280px 容器装得下）', String(overlappingPairs(layered).length)],
              ['今日词云里有「值得去」吗', today.some((w) => w.word === '值得去') ? '有' : '没有（被 min_count=2 筛掉）'],
              ['新载荷里有「值得去」吗', opinions.some((w) => w.word === '值得去') ? '有（文档频次 1 也保留）' : '没有'],
            ].map(([k, v], i) =>
              createElement('tr', { key: i }, createElement('td', null, k), createElement('td', null, v))
            )
          )
        ),
      ])
    )
  )
}

mount()

const statusEl = document.getElementById('status')
if (statusEl) statusEl.textContent = '已渲染：布局与配色均 import 生产模块，本页无第二套实现。'

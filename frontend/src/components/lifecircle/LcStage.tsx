import type { ReactNode } from 'react'
import { LC_ASIDE, LC_LEGEND, LC_MAP_CELL, LC_SPLIT } from './stageContract'

/**
 * 舞台面板件（评审 S4 的完整形态）：左=地图（含图例浮层与覆盖控件），右=滚动面板。
 *
 * ## 为什么是复合组件而不是四个 props
 *
 * `canvas / legend / overlays / panel` 那种 API 要把页面里几百行 JSX 抽出来重新传参 ——
 * 一次纯机械的大搬迁。而本件的唯一硬约束是**DOM 形状不许变**（`lg:h-full` / `min-h-0`
 * 是按父层解析的百分比高度，多包一层就改几何），换标签写法则子节点原地不动：
 * 组件本身不产生 DOM 节点，所以树形逐字不变，由
 * `__tests__/lcStageStructure.test.tsx` 的基线当场钉死（多包一层立刻红）。
 *
 * 类名一律来自 `stageContract.ts`，本文件不内联副本 —— 契约只有一个家。
 *
 * ## 谁在用 / 还没用
 *
 * 现在只有体检台一个消费者。`LifeCircleReportView`（报告页镜像）与 `ComparePage`
 * 的结构不同（`grid-cols-[1.6fr_1fr]` + 快照 / 两块定高小图），套用之前要先各自
 * 采一份结构基线 —— 那属于计划 2.2/2.4b 的"需要能出帧的环境"那一档，不在本件里偷做。
 */
export default function LcStage({ children }: { children: ReactNode }) {
  return <div className={LC_SPLIT}>{children}</div>
}

/** 左槽：地图格。子节点顺序即图层顺序（地图 → 图例 → 覆盖控件） */
function Canvas({ children }: { children: ReactNode }) {
  return <div className={LC_MAP_CELL}>{children}</div>
}

/** 图例浮层。`z-10` 的来由见 `stageContract.ts` 规矩 2（压过注入的 `.BMap_mask`） */
function Legend({ children }: { children: ReactNode }) {
  return <div className={LC_LEGEND}>{children}</div>
}

/** 右槽：大屏下自己滚，因此槽里的控件永不进整页滚动链 */
function Panel({ children }: { children: ReactNode }) {
  return <aside className={LC_ASIDE}>{children}</aside>
}

LcStage.Canvas = Canvas
LcStage.Legend = Legend
LcStage.Panel = Panel

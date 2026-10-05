import { motion } from 'framer-motion'
import { Check, Loader2, RotateCcw, Circle } from 'lucide-react'
import type { DAGNode } from '../types'
import { useExpertStore } from '../store/expertStore'

/** 纵向 DAG 时间线：展示 7 节点流转，working 呼吸、done 打勾、rework 回环。 */
export function VFlowDag({ nodes }: { nodes: DAGNode[] }) {
  const byId = useExpertStore((s) => s.byId)
  return (
    <div className="flex flex-col">
      {nodes.map((n, i) => {
        const expert = n.expert ? byId(n.expert, 'travel') : undefined
        const last = i === nodes.length - 1
        return (
          <div key={n.id} className="flex gap-3">
            {/* 轴 */}
            <div className="flex flex-col items-center">
              <NodeDot status={n.status} />
              {!last && (
                <div
                  className={`w-px flex-1 ${
                    n.status === 'done' ? 'bg-primary-soft' : 'bg-line'
                  }`}
                  style={{ minHeight: 28 }}
                />
              )}
            </div>
            {/* 内容 */}
            <div className="pb-5">
              <div
                className={`text-aux font-medium ${
                  n.status === 'idle' ? 'text-ink-3' : 'text-ink'
                }`}
              >
                {n.label}
              </div>
              {expert && n.status !== 'idle' && (
                <div className="mt-1 flex items-center gap-1.5">
                  <img
                    src={expert.avatar}
                    alt={expert.name}
                    className="h-4 w-4 rounded-full object-cover"
                  />
                  <span className="text-tag text-ink-3">{expert.name}</span>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function NodeDot({ status }: { status: DAGNode['status'] }) {
  if (status === 'done')
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full bg-primary text-white">
        <Check size={13} strokeWidth={2.5} />
      </span>
    )
  if (status === 'working')
    return (
      <motion.span
        animate={{ scale: [1, 1.12, 1] }}
        transition={{ repeat: Infinity, duration: 1.4 }}
        className="grid h-6 w-6 place-items-center rounded-full bg-primary-tint text-primary"
      >
        <Loader2 size={13} className="animate-spin" />
      </motion.span>
    )
  if (status === 'rework')
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full bg-warn/20 text-warn">
        <RotateCcw size={13} />
      </span>
    )
  return (
    <span className="grid h-6 w-6 place-items-center rounded-full border border-line text-ink-3">
      <Circle size={8} />
    </span>
  )
}

import { useState } from 'react'
import { Table2, Download, ChevronDown, ExternalLink } from 'lucide-react'
import type { DataGrid } from '../types'

/** 数据空间：可展开数据表 + 导出 CSV（对应需求 7）。 */
export function VDataGrid({ grid, title = '数据空间' }: { grid: DataGrid; title?: string }) {
  const [open, setOpen] = useState(false)
  if (!grid?.rows?.length) return null
  const preview = open ? grid.rows : grid.rows.slice(0, 3)

  const exportCsv = () => {
    const head = grid.columns.join(',')
    const lines = grid.rows.map((r) =>
      [r.name, r.value, r.metric, r.source, r.source_url]
        .map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`)
        .join(','),
    )
    const csv = '\ufeff' + [head, ...lines].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mt-4 overflow-hidden rounded-card border border-line bg-white">
      <div className="flex items-center justify-between bg-bg px-4 py-2">
        <div className="flex items-center gap-1.5 text-aux font-semibold text-ink">
          <Table2 size={14} className="text-primary" /> {title} · {grid.rows.length} 条数据
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportCsv} className="flex items-center gap-1 rounded-chip bg-primary-tint px-2 py-1 text-tag text-primary-deep hover:bg-primary-soft/40">
            <Download size={12} /> 导出 CSV
          </button>
          <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 rounded-chip px-2 py-1 text-tag text-ink-3">
            {open ? '收起' : '展开全部'} <ChevronDown size={12} className={open ? 'rotate-180 transition' : 'transition'} />
          </button>
        </div>
      </div>
      <table className="w-full text-tag">
        <thead>
          <tr className="border-b border-line text-ink-3">
            {grid.columns.map((c) => (
              <th key={c} className="px-3 py-1.5 text-left font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.map((r, i) => (
            <tr key={i} className="border-b border-line/60 last:border-0">
              <td className="px-3 py-1.5 font-medium text-ink">{r.name}</td>
              <td className="px-3 py-1.5 text-primary-deep">{r.value}</td>
              <td className="px-3 py-1.5 text-ink-2">{r.metric}</td>
              <td className="px-3 py-1.5 text-ink-2">{r.source}</td>
              <td className="px-3 py-1.5">
                {r.source_url ? (
                  <a href={r.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                    链接 <ExternalLink size={10} />
                  </a>
                ) : (
                  <span className="text-ink-3">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!open && grid.rows.length > 3 && (
        <button onClick={() => setOpen(true)} className="w-full bg-bg/60 py-1.5 text-tag text-ink-3 hover:text-primary-deep">
          点击查看全部 {grid.rows.length} 条数据 →
        </button>
      )}
    </div>
  )
}

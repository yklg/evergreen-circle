/**
 * 报告分享弹窗（T6/E1）：复制直达链接 + 轻量 canvas 二维码。
 *
 * 后端 /api/life-circle/{id}/share 返回 {url,title}（报告页公开可读，无需鉴权）；
 * mock 态（USE_MOCK）本地拼链接，不依赖后端。
 * 二维码由 lib/qrcode（自研、对照 Nayuki 参考矩阵验证）生成，零第三方依赖。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Copy, QrCode, Share2, X } from 'lucide-react'
import { fetchLifeCircleShare } from '../../lib/api'
import { drawQrToCanvas } from '../../lib/qrcode'
import { isFixtureMode } from '../../store/dataModeStore'

export interface ShareModalProps {
  reportId: string
  title: string
  onClose: () => void
}

export default function ShareModal({ reportId, title, onClose }: ShareModalProps) {
  // 演示态本地拼链接；真实态调 /share 端点（弹窗打开时取一次快照即可）
  const [url, setUrl] = useState<string>(isFixtureMode() ? `/report/${reportId}?share=1` : '')
  const [copied, setCopied] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const fullUrl = useMemo(() => {
    if (!url) return ''
    return `${window.location.origin}${url}`
  }, [url])

  useEffect(() => {
    if (isFixtureMode()) return
    let cancelled = false
    fetchLifeCircleShare(reportId)
      .then((r) => {
        if (!cancelled && r?.url) setUrl(r.url)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [reportId])

  useEffect(() => {
    if (canvasRef.current && fullUrl) {
      try {
        drawQrToCanvas(canvasRef.current, fullUrl, 4, 4)
      } catch {
        // 超长链接（>105 字节）不画二维码，仅保留复制
      }
    }
  }, [fullUrl])

  async function copy() {
    if (!fullUrl) return
    try {
      await navigator.clipboard.writeText(fullUrl)
    } catch {
      // 非安全上下文兜底：选中输入框内容
      const el = document.getElementById('share-link-input') as HTMLInputElement | null
      el?.select()
      document.execCommand('copy')
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm" role="dialog" aria-label="分享体检报告">
      <div className="w-full max-w-sm rounded-card border border-line bg-card p-6 shadow-float">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-aux font-semibold text-ink">
            <Share2 size={15} className="text-primary" /> 分享体检报告
          </div>
          <button onClick={onClose} title="关闭" className="grid h-8 w-8 place-items-center rounded-btn text-ink-3 hover:bg-primary-tint">
            <X size={15} />
          </button>
        </div>
        <p className="mt-1 truncate text-tag text-ink-3" title={title}>
          {title}
        </p>

        <div className="mt-4 flex items-center gap-2">
          <input
            id="share-link-input"
            readOnly
            value={fullUrl || '加载中…'}
            className="h-10 min-w-0 flex-1 rounded-btn border border-line bg-bg px-3 text-tag text-ink outline-none"
          />
          <button
            onClick={copy}
            disabled={!fullUrl}
            title="复制直达链接"
            className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-btn bg-primary px-3.5 text-aux font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? '已复制' : '复制'}
          </button>
        </div>

        <div className="mt-4 flex flex-col items-center gap-2 rounded-card border border-line bg-white p-4">
          <canvas ref={canvasRef} className="h-40 w-40 rounded-btn" aria-label="分享链接二维码" />
          <span className="inline-flex items-center gap-1 text-tag text-ink-3">
            <QrCode size={12} /> 扫码直达本报告（手机可读）
          </span>
        </div>

        <p className="mt-3 text-tag text-ink-3">
          报告为公开只读直达链接，无需登录；分享后可通过 40% 实时性评分项快速评审。
        </p>
      </div>
    </div>
  )
}

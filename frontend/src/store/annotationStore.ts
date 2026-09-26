import { create } from 'zustand'

/* 飞书式标注 + 可溯源知识库（本地持久化，localhost / Vercel 均可用） */

export type HighlightColor = 'sun' | 'ok' | 'risk' | 'info'

export interface Highlight {
  id: string
  sectionId: string
  text: string
  color: HighlightColor
  comment: string
  createdAt: number
}

export interface ReportAnnotations {
  edits: Record<string, string> // blockId -> 编辑后文本
  highlights: Highlight[]
}

export type KBKind = 'claim' | 'evidence' | 'quote' | 'figure' | 'note' | 'highlight'

export interface KBEntry {
  id: string
  reportId: string
  reportTitle: string
  kind: KBKind
  title: string
  content: string
  sourceUrl?: string
  evidenceId?: string
  brand?: string
  destination?: string
  imageSrc?: string
  tags: string[]
  createdAt: number
}

interface AnnotationState {
  annotations: Record<string, ReportAnnotations>
  knowledge: KBEntry[]
  // 编辑
  setEdit: (reportId: string, blockId: string, text: string) => void
  getEdit: (reportId: string, blockId: string) => string | undefined
  // 高亮 + 批注
  addHighlight: (reportId: string, h: Omit<Highlight, 'id' | 'createdAt'>) => void
  updateHighlight: (reportId: string, id: string, patch: Partial<Highlight>) => void
  removeHighlight: (reportId: string, id: string) => void
  // 知识库
  addToKB: (entry: Omit<KBEntry, 'id' | 'createdAt'>) => boolean
  removeFromKB: (id: string) => void
  isInKB: (reportId: string, dedupeKey: string) => boolean
}

const LS_KEY = 'verda.annotations.v1'
const LS_KB = 'verda.knowledge.v1'

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore quota */
  }
}
function uid(p: string) {
  return `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export const useAnnotationStore = create<AnnotationState>((set, get) => ({
  annotations: load<Record<string, ReportAnnotations>>(LS_KEY, {}),
  knowledge: load<KBEntry[]>(LS_KB, []),

  setEdit: (reportId, blockId, text) =>
    set((s) => {
      const cur = s.annotations[reportId] ?? { edits: {}, highlights: [] }
      const next = {
        ...s.annotations,
        [reportId]: { ...cur, edits: { ...cur.edits, [blockId]: text } },
      }
      save(LS_KEY, next)
      return { annotations: next }
    }),

  getEdit: (reportId, blockId) => get().annotations[reportId]?.edits[blockId],

  addHighlight: (reportId, h) =>
    set((s) => {
      const cur = s.annotations[reportId] ?? { edits: {}, highlights: [] }
      const hl: Highlight = { ...h, id: uid('hl'), createdAt: Date.now() }
      const next = {
        ...s.annotations,
        [reportId]: { ...cur, highlights: [...cur.highlights, hl] },
      }
      save(LS_KEY, next)
      return { annotations: next }
    }),

  updateHighlight: (reportId, id, patch) =>
    set((s) => {
      const cur = s.annotations[reportId]
      if (!cur) return s
      const next = {
        ...s.annotations,
        [reportId]: {
          ...cur,
          highlights: cur.highlights.map((h) => (h.id === id ? { ...h, ...patch } : h)),
        },
      }
      save(LS_KEY, next)
      return { annotations: next }
    }),

  removeHighlight: (reportId, id) =>
    set((s) => {
      const cur = s.annotations[reportId]
      if (!cur) return s
      const next = {
        ...s.annotations,
        [reportId]: { ...cur, highlights: cur.highlights.filter((h) => h.id !== id) },
      }
      save(LS_KEY, next)
      return { annotations: next }
    }),

  addToKB: (entry) => {
    const dupe = get().knowledge.some(
      (k) => k.reportId === entry.reportId && k.content === entry.content && k.kind === entry.kind,
    )
    if (dupe) return false
    set((s) => {
      const e: KBEntry = { ...entry, id: uid('kb'), createdAt: Date.now() }
      const next = [e, ...s.knowledge]
      save(LS_KB, next)
      return { knowledge: next }
    })
    return true
  },

  removeFromKB: (id) =>
    set((s) => {
      const next = s.knowledge.filter((k) => k.id !== id)
      save(LS_KB, next)
      return { knowledge: next }
    }),

  isInKB: (reportId, dedupeKey) =>
    get().knowledge.some((k) => k.reportId === reportId && k.content === dedupeKey),
}))

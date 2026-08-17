import { apiJson } from './client'

export interface WorkspaceProject {
  project_id: string
  workspace: string
  name: string
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface HistoryItem {
  history_id: string
  workspace: string
  title: string
  summary: string
  artifact_path: string
  metadata: Record<string, unknown>
  starred: boolean
  created_at: string
}

export interface Archetype {
  archetype_id: string
  name: string
  language: string
  use_case: string
  instruct: string
  sample_text: string
  gender: string
  age: string
  pitch: string
  accent: string
  style: string
  featured: boolean
}

export interface GalleryPageData {
  total: number
  page: number
  page_size: number
  items: Archetype[]
}

export interface TranscriptEntry {
  entry_id: string
  text: string
  language: string
  source_path: string
  source_srt: string
  translated_srt: string
  created_at: string
}

export interface DocumentItem {
  item_id: string
  chapter: string
  speaker: string
  text: string
  profile_id: string
  speed: number
  volume: number
  pause_after_ms: number
  preview_path: string
}

export interface LongformDocument {
  doc_id: string
  kind: 'stories' | 'audiobook'
  document: { chapters: string[]; items: DocumentItem[] }
  script: string
  voice_names: string[]
}

export interface DubbingSegment {
  segment_id: string
  start_ms: number
  end_ms: number
  source_text: string
  text: string
  speaker_id: string
  profile_id: string
  speed: number
  volume: number
}

export interface RenderResultPayload {
  project_dir: string
  wav_path: string
  srt_path: string
  mp3_path: string | null
  m4b_path: string | null
  stems_dir: string | null
  manifest_path: string
  span_count: number
  warnings: string[]
}

export interface ResumeJob {
  project_dir: string
  project_name: string
  total_spans: number
  completed_spans: number
  status: string
  error: string
  updated_at: string
}

// Projects
export const fetchProjects = (workspace = '') =>
  apiJson<WorkspaceProject[]>(`/api/workspaces/projects?workspace=${encodeURIComponent(workspace)}`)
export const saveProject = (body: {
  workspace: string
  name: string
  payload?: Record<string, unknown>
  project_id?: string
}) =>
  apiJson<WorkspaceProject>('/api/workspaces/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const deleteProject = (projectId: string) =>
  apiJson<{ ok: boolean }>(`/api/workspaces/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  })

// History
export const fetchHistory = (params: { workspace?: string; query?: string; starred_only?: boolean } = {}) => {
  const search = new URLSearchParams()
  if (params.workspace) search.set('workspace', params.workspace)
  if (params.query) search.set('query', params.query)
  if (params.starred_only) search.set('starred_only', 'true')
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return apiJson<HistoryItem[]>(`/api/workspaces/history${suffix}`)
}

// Gallery
export const fetchGalleryCategories = () => apiJson<string[]>('/api/workspaces/gallery/categories')
export const fetchGallery = (params: { query?: string; use_case?: string; page?: number } = {}) => {
  const search = new URLSearchParams({ page: String(params.page ?? 1) })
  if (params.query) search.set('query', params.query)
  if (params.use_case) search.set('use_case', params.use_case)
  return apiJson<GalleryPageData>(`/api/workspaces/gallery?${search.toString()}`)
}

// Transcripts
export const fetchTranscripts = (query = '') =>
  apiJson<TranscriptEntry[]>(`/api/workspaces/transcripts?query=${encodeURIComponent(query)}`)
export const addTranscript = (body: {
  text: string
  language?: string
  source_path?: string
  source_srt?: string
  translated_srt?: string
}) =>
  apiJson<TranscriptEntry>('/api/workspaces/transcripts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const deleteTranscript = (entryId: string) =>
  apiJson<{ ok: boolean }>(`/api/workspaces/transcripts/${encodeURIComponent(entryId)}`, {
    method: 'DELETE',
  })
export const clearTranscripts = () =>
  apiJson<{ ok: boolean }>('/api/workspaces/transcripts', { method: 'DELETE' })

// Documents
export const createDocument = (kind: 'stories' | 'audiobook', source: string) =>
  apiJson<LongformDocument>('/api/workspaces/document', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, source }),
  })
export const fetchDocument = (docId: string, kind: 'stories' | 'audiobook') =>
  apiJson<LongformDocument>(`/api/workspaces/document/${encodeURIComponent(docId)}?kind=${kind}`)
export const documentOp = (
  docId: string,
  kind: 'stories' | 'audiobook',
  op: {
    op: 'update' | 'add' | 'delete' | 'move' | 'split' | 'merge'
    item_id?: string
    after_id?: string
    chapter?: string
    changes?: Record<string, unknown>
    position?: number
    delta?: number
    second_id?: string
  },
) =>
  apiJson<LongformDocument>(`/api/workspaces/document/${encodeURIComponent(docId)}/ops?kind=${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(op),
  })

// Dubbing
export const fetchDubbingPlan = (srtText: string) =>
  apiJson<{ segments: DubbingSegment[]; issues: { code: string; segment_id: string; message: string; severity: string }[] }>(
    `/api/workspaces/dubbing/plan?srt_text=${encodeURIComponent(srtText)}`,
  )

// Render + resume
export const startRender = (body: {
  doc_id?: string
  kind: 'stories' | 'audiobook' | 'dubbing'
  segments?: DubbingSegment[]
  output_dir: string
  project_name?: string
  mode?: string
  model_id?: string
  device?: string
  language?: string
  speed?: number
  cast_map?: Record<string, string>
  gap_ms?: number
  export_mp3?: boolean
  export_m4b?: boolean
  export_stems?: boolean
  title?: string
  author?: string
  cover_path?: string
  resume_project_dir?: string
}) =>
  apiJson<{ task_id: string }>('/api/workspaces/render', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const fetchResumeJobs = (outputDir: string) =>
  apiJson<ResumeJob[]>(`/api/workspaces/resume-jobs?output_dir=${encodeURIComponent(outputDir)}`)

export const importSource = (path: string) =>
  apiJson<{ text: string; path: string }>('/api/workspaces/import-source', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })

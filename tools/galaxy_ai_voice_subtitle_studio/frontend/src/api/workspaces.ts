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
  spoken_text: string
  emotion: string
  emphasis: boolean
  spell: boolean
}

export interface PronunciationRule {
  rule_id: string
  source: string
  replacement: string
  language: string
  case_sensitive: boolean
  whole_word: boolean
}

export interface ExpressiveIssue {
  code: string
  message: string
  severity: string
  offset: number
}

export interface LongformDocument {
  doc_id: string
  kind: 'stories' | 'audiobook'
  document: {
    chapters: string[]
    language: string
    items: DocumentItem[]
    pronunciation_rules: PronunciationRule[]
  }
  script: string
  voice_names: string[]
  issues: ExpressiveIssue[]
}

export interface LongformProjectSummary {
  project_id: string
  galaxy_project_id: string
  name: string
  kind: 'stories' | 'audiobook'
  stage: string
  revision: number
  item_count: number
  chapter_count: number
  updated_at: string
}

export interface LongformProject extends LongformProjectSummary {
  source: string
  document: LongformDocument['document']
  language: string
  options: Record<string, unknown>
  metadata: Record<string, unknown>
  last_result: Record<string, unknown>
  created_at: string
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
  preview_path?: string
  source_speaker_id?: string
}

export interface DubbingIssue {
  code: string
  segment_id: string
  message: string
  severity: 'error' | 'warning' | string
}

export interface DubbingMeasurement {
  segment_id: string
  raw_duration_ms: number
  tempo: number
  tempo_duration_ms: number
  fitted_duration_ms: number
  method: string
  clipped_ms: number
  padded_ms: number
}

export interface DubbingQualityReport {
  report_id: string
  score: number
  segment_count: number
  error_count: number
  warning_count: number
  issues: DubbingIssue[]
  measurements: DubbingMeasurement[]
}

export interface DubbingProjectSummary {
  project_id: string
  galaxy_project_id: string
  name: string
  stage: string
  revision: number
  segment_count: number
  language: string
  updated_at: string
}

export interface DubbingProject extends DubbingProjectSummary {
  source_srt: string
  translated_srt: string
  source_video: string
  source_audio: string
  segments: DubbingSegment[]
  options: Record<string, unknown>
  quality: Partial<DubbingQualityReport>
  last_result: Record<string, unknown>
  created_at: string
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
  quality_report_path?: string | null
  mixed_audio_path?: string | null
  video_path?: string | null
  fit_measurements?: DubbingMeasurement[]
  quality?: DubbingQualityReport | null
  preview_files?: string[]
  wav_file?: string | null
  mixed_audio_file?: string | null
  video_file?: string | null
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
export const addHistory = (body: {
  workspace: string
  title: string
  summary?: string
  artifact_path?: string
  metadata?: Record<string, unknown>
}) =>
  apiJson<HistoryItem>('/api/workspaces/history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

// Gallery
export const fetchGalleryCategories = () => apiJson<string[]>('/api/workspaces/gallery/categories')
export const fetchGallery = (params: {
  query?: string
  use_case?: string
  language?: string
  gender?: string
  age?: string
  pitch?: string
  style?: string
  page?: number
} = {}) => {
  const search = new URLSearchParams({ page: String(params.page ?? 1) })
  if (params.query) search.set('query', params.query)
  if (params.use_case) search.set('use_case', params.use_case)
  if (params.language) search.set('language', params.language)
  if (params.gender) search.set('gender', params.gender)
  if (params.age) search.set('age', params.age)
  if (params.pitch) search.set('pitch', params.pitch)
  if (params.style) search.set('style', params.style)
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
export const createDocument = (
  kind: 'stories' | 'audiobook',
  source: string,
  document?: LongformDocument['document'],
  language = 'auto',
) =>
  apiJson<LongformDocument>('/api/workspaces/document', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, source, document, language }),
  })
export const fetchDocument = (docId: string, kind: 'stories' | 'audiobook') =>
  apiJson<LongformDocument>(`/api/workspaces/document/${encodeURIComponent(docId)}?kind=${kind}`)
export const documentOp = (
  docId: string,
  kind: 'stories' | 'audiobook',
  op: {
    op: 'update' | 'add' | 'delete' | 'move' | 'split' | 'merge' | 'add_chapter' | 'rename_chapter' | 'move_chapter'
    item_id?: string
    after_id?: string
    chapter?: string
    name?: string
    changes?: Record<string, unknown>
    position?: number
    delta?: number
    second_id?: string
    document?: LongformDocument['document']
  },
) =>
  apiJson<LongformDocument>(`/api/workspaces/document/${encodeURIComponent(docId)}/ops?kind=${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(op),
  })

export const fetchLongformProjects = (kind: 'stories' | 'audiobook', galaxyProjectId = '') => {
  const search = new URLSearchParams({ kind })
  if (galaxyProjectId) search.set('galaxy_project_id', galaxyProjectId)
  return apiJson<LongformProjectSummary[]>(`/api/workspaces/longform/projects?${search.toString()}`)
}

export const fetchLongformProject = (projectId: string) =>
  apiJson<LongformProject>(`/api/workspaces/longform/projects/${encodeURIComponent(projectId)}`)

export const saveLongformProject = (body: Partial<LongformProject> & {
  name: string
  kind: 'stories' | 'audiobook'
  stage: string
  source: string
  document: LongformDocument['document']
  expected_revision: number
}) => apiJson<LongformProject>('/api/workspaces/longform/projects', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const deleteLongformProject = (projectId: string) =>
  apiJson<{ ok: boolean }>(`/api/workspaces/longform/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  })

export const longformProjectMediaUrl = (projectId: string, kind: 'wav' | 'mp3' | 'm4b') =>
  `/api/workspaces/longform/projects/${encodeURIComponent(projectId)}/media/${kind}`

// Dubbing
export const fetchDubbingPlan = (sourceSrt: string, translatedSrt = '') =>
  apiJson<{ segments: DubbingSegment[]; issues: DubbingIssue[]; quality: DubbingQualityReport }>(
    '/api/workspaces/dubbing/plan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_srt: sourceSrt, translated_srt: translatedSrt }),
    },
  )

export const fetchDubbingQuality = (segments: DubbingSegment[], options: Record<string, number> = {}) =>
  apiJson<DubbingQualityReport>('/api/workspaces/dubbing/qc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segments, ...options }),
  })

export const startDubbingTranslation = (body: {
  galaxy_project_id?: string
  workflow_id?: string
  source_srt: string
  source_language?: string
  target_language?: string
  provider?: string
  model?: string
  base_url?: string
  api_key?: string
  batch_size?: number
  max_workers?: number
}) => apiJson<{ task_id: string }>('/api/workspaces/dubbing/translate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const fetchDubbingProjects = (galaxyProjectId = '') => {
  const suffix = galaxyProjectId
    ? `?galaxy_project_id=${encodeURIComponent(galaxyProjectId)}`
    : ''
  return apiJson<DubbingProjectSummary[]>(`/api/workspaces/dubbing/projects${suffix}`)
}

export const fetchDubbingProject = (projectId: string) =>
  apiJson<DubbingProject>(`/api/workspaces/dubbing/projects/${encodeURIComponent(projectId)}`)

export const dubbingProjectMediaUrl = (projectId: string, kind: 'video' | 'mixed' | 'voice') =>
  `/api/workspaces/dubbing/projects/${encodeURIComponent(projectId)}/media/${kind}`

export const saveDubbingProject = (body: Partial<DubbingProject> & {
  name: string
  stage: string
  source_srt: string
  segments: DubbingSegment[]
  expected_revision: number
}) => apiJson<DubbingProject>('/api/workspaces/dubbing/projects', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const deleteDubbingProject = (projectId: string) =>
  apiJson<{ ok: boolean }>(`/api/workspaces/dubbing/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  })

// Render + resume
export const startRender = (body: {
  project_id?: string
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
  mastering?: boolean
  target_lufs?: number
  true_peak_db?: number
  preview_item_index?: number
  title?: string
  author?: string
  cover_path?: string
  resume_project_dir?: string
  source_video?: string
  source_audio?: string
  mix_mode?: 'replace' | 'mix' | 'duck'
  source_volume?: number
  dub_volume?: number
  fit_min_tempo?: number
  fit_max_tempo?: number
  fit_tolerance_ms?: number
  min_gap_ms?: number
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

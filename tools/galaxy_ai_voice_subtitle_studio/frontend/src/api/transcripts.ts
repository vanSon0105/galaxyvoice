import { apiJson } from './client'

export interface TranscriptWord {
  word_id: string
  text: string
  start_ms: number
  end_ms: number
  confidence: number | null
}

export interface TranscriptCue {
  cue_id: string
  position: number
  start_ms: number
  end_ms: number
  text: string
  speaker_id: string
  confidence: number | null
  words: TranscriptWord[]
}

export interface TranscriptSpeaker {
  speaker_id: string
  label: string
  color: string
  reference_path?: string
  reference_start_ms?: number | null
  reference_end_ms?: number | null
}

export interface TranscriptProject {
  schema_version: number
  transcript_id: string
  project_id: string
  name: string
  status: string
  revision: number
  source_path: string
  source_kind: 'audio' | 'video' | 'document' | 'manual'
  requested_language: string
  detected_language: string
  model_id: string
  requested_device: string
  resolved_device: string
  diarization_requested: boolean
  diarization_state: string
  created_at: string
  updated_at: string
  duration_ms: number
  speakers: TranscriptSpeaker[]
  cue_count: number
  warnings: string[]
  provenance: Record<string, unknown>
  handoffs: Record<string, unknown>[]
  cues?: TranscriptCue[]
}

export const fetchTranscriptProjects = (projectId = '', query = '') => {
  const search = new URLSearchParams()
  if (projectId) search.set('project_id', projectId)
  if (query) search.set('query', query)
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return apiJson<TranscriptProject[]>(`/api/transcripts/projects${suffix}`)
}

export const fetchTranscriptProject = (transcriptId: string) =>
  apiJson<TranscriptProject>(`/api/transcripts/projects/${encodeURIComponent(transcriptId)}`)

export const deleteTranscriptProject = (transcriptId: string) =>
  apiJson<{ ok: boolean }>(`/api/transcripts/projects/${encodeURIComponent(transcriptId)}`, {
    method: 'DELETE',
  })

export const importMediaForTranscription = (body: {
  project_id: string
  media_path: string
  name?: string
  language?: string
  model_size?: string
  device?: string
  diarization?: boolean
}) =>
  apiJson<{ task_id: string }>('/api/transcripts/import-media', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const importTextTranscript = (body: {
  project_id: string
  name: string
  content: string
  format_type?: 'srt' | 'vtt' | 'txt'
  language?: string
  source_path?: string
}) =>
  apiJson<TranscriptProject>('/api/transcripts/import-text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const editTranscriptCue = (
  transcriptId: string,
  cueId: string,
  body: {
    text?: string
    start_ms?: number
    end_ms?: number
    speaker_id?: string
    expected_revision?: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/cues/${encodeURIComponent(cueId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const saveTranscriptDocument = (
  transcriptId: string,
  body: {
    cues: TranscriptCue[]
    speakers: TranscriptSpeaker[]
    expected_revision: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/document`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const splitTranscriptCue = (
  transcriptId: string,
  cueId: string,
  body: {
    split_ms: number
    first_text: string
    second_text: string
    expected_revision?: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/cues/${encodeURIComponent(cueId)}/split`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const mergeTranscriptCues = (
  transcriptId: string,
  body: {
    first_cue_id: string
    second_cue_id: string
    separator?: string
    expected_revision?: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/merge-cues`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const deleteTranscriptCue = (
  transcriptId: string,
  cueId: string,
  expectedRevision?: number,
) => {
  const suffix = expectedRevision !== undefined ? `?expected_revision=${expectedRevision}` : ''
  return apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/cues/${encodeURIComponent(cueId)}${suffix}`,
    { method: 'DELETE' },
  )
}

export const addTranscriptSpeaker = (
  transcriptId: string,
  body: {
    label: string
    color?: string
    expected_revision?: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/speakers`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const updateTranscriptSpeaker = (
  transcriptId: string,
  speakerId: string,
  body: {
    label: string
    color?: string
    expected_revision?: number
  },
) =>
  apiJson<TranscriptProject>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/speakers/${encodeURIComponent(speakerId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )

export const transcriptExportUrl = (transcriptId: string, format = 'srt') =>
  `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/export?format=${format}`

export const transcriptMediaUrl = (transcriptId: string) =>
  `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/media`

export const transcriptSpeakerReferenceUrl = (transcriptId: string, speakerId: string) =>
  `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/speakers/${encodeURIComponent(speakerId)}/reference`

export interface TranscriptHandoff {
  schema_version: number
  kind: 'transcript_handoff'
  handoff_id?: string
  target: 'dubbing' | 'longform'
  transcript_id: string
  project_id: string
  source_revision: number
  source_path: string
  language: string
  srt_text?: string
  text?: string
  segments?: Array<Record<string, unknown>>
}

export const createTranscriptHandoff = (
  transcriptId: string,
  target: 'dubbing' | 'longform',
) =>
  apiJson<TranscriptHandoff>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/handoffs/${target}`,
    { method: 'POST' },
  )

export const fetchTranscriptHandoff = (
  transcriptId: string,
  target: 'dubbing' | 'longform',
) =>
  apiJson<TranscriptHandoff>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/handoffs/${target}`,
  )

export const fetchDubbingHandoff = (transcriptId: string) =>
  apiJson<Array<Record<string, unknown>>>(
    `/api/transcripts/projects/${encodeURIComponent(transcriptId)}/dubbing-handoff`,
  )

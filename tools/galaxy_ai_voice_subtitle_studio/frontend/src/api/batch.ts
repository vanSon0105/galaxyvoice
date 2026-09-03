import { apiJson } from './client'
import type { StudioVoiceSource } from './studio'

export interface BatchItemInput {
  item_id: string
  text: string
  language: string
  speed: number | null
  duration: number | null
  voice_source: StudioVoiceSource | ''
  profile_id: string
  instruction: string
  formats: ('wav' | 'mp3')[]
}

export interface BatchItemResult extends BatchItemInput {
  status: 'pending' | 'running' | 'done' | 'failed'
  attempts: number
  error: string | null
  wav_path: string | null
  mp3_path: string | null
  warnings: string[]
  audio_url: string | null
}

export interface BatchRun {
  batch_id: string
  project_id: string
  title: string
  status: 'queued' | 'running' | 'paused' | 'completed' | 'partial' | 'failed' | 'cancelled' | 'interrupted'
  task_id: string
  engine_id: string
  language: string
  formats: string[]
  combine: boolean
  gap_ms: number
  max_workers: number
  root_dir: string
  manifest_path: string
  combined_wav_path: string | null
  combined_mp3_path: string | null
  completed_count: number
  failed_count: number
  total_count: number
  warnings: string[]
  created_at: string
  updated_at: string
  items: BatchItemResult[]
}

export interface CreateBatchRunRequest {
  project_id: string
  title: string
  output_dir: string
  engine_id?: string
  model_id?: string
  device: string
  language: string
  speed: number
  duration?: number | null
  formats: ('wav' | 'mp3')[]
  voice: {
    source: StudioVoiceSource
    profile_id?: string
    reference_audio?: string
    reference_text?: string
    instruction?: string
  }
  engine_options?: Record<string, unknown>
  combine: boolean
  gap_ms: number
  max_workers?: number
  items: BatchItemInput[]
}

export const parseBatchSource = (source: string, longForm: boolean) =>
  apiJson<BatchItemInput[]>('/api/batch/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, long_form: longForm }),
  })

export const startBatchRun = (body: CreateBatchRunRequest) =>
  apiJson<{ batch_id: string; task_id: string }>('/api/batch/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const fetchBatchRuns = (projectId = '') =>
  apiJson<BatchRun[]>(`/api/batch/runs${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)

export const fetchBatchRun = (batchId: string) =>
  apiJson<BatchRun>(`/api/batch/runs/${encodeURIComponent(batchId)}`)

export const resumeBatchRun = (batchId: string) =>
  apiJson<{ batch_id: string; task_id: string }>(`/api/batch/runs/${encodeURIComponent(batchId)}/resume`, { method: 'POST' })

export const retryBatchRun = (batchId: string) =>
  apiJson<{ batch_id: string; task_id: string }>(`/api/batch/runs/${encodeURIComponent(batchId)}/retry`, { method: 'POST' })

export const pauseTask = (taskId: string) =>
  apiJson<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(taskId)}/pause`, { method: 'POST' })

export const resumeTask = (taskId: string) =>
  apiJson<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(taskId)}/resume`, { method: 'POST' })

export const cancelTask = (taskId: string) =>
  apiJson<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })

export const batchManifestUrl = (batchId: string) =>
  `/api/batch/runs/${encodeURIComponent(batchId)}/manifest`

export const batchCombinedAudioUrl = (run: BatchRun, format?: 'wav' | 'mp3', download = false) => {
  const selected = format ?? (run.combined_mp3_path ? 'mp3' : 'wav')
  return `/api/batch/runs/${encodeURIComponent(run.batch_id)}/audio?format=${selected}${download ? '&download=true' : ''}`
}

export const batchItemAudioUrl = (item: BatchItemResult, download = false) => {
  const selected = item.mp3_path ? 'mp3' : 'wav'
  return `${item.audio_url}?format=${selected}${download ? '&download=true' : ''}`
}

import { apiJson } from './client'

export interface EditorCue {
  index: number
  start_ms: number
  end_ms: number
  text: string
}

export interface EditorMedia {
  source_id: string
  url: string
  name: string
  path: string
  kind: 'video' | 'audio'
  duration_seconds: number
  width: number
  height: number
  fps: number
  has_audio: boolean
}

export interface EditorSubtitleAsset {
  name: string
  path: string
  cues: EditorCue[]
}

export interface EditorExportRequest {
  galaxy_project_id: string
  video_path: string
  output_dir: string
  project_name: string
  audio_path?: string
  cues: EditorCue[]
  segments: Array<{
    source_start_ms: number
    source_end_ms: number
  }>
  audio_offset_ms: number
  audio_mode: string
  source_volume: number
  external_volume: number
  resolution: string
  fps: string
  encoder: string
  quality: number
  subtitle_font_size: number
  subtitle_margin: number
  video_clips?: EditorExportClip[]
  audio_clips?: EditorExportClip[]
}

export interface EditorExportClip {
  path: string
  timeline_start_ms: number
  source_start_ms: number
  source_end_ms: number
  track_order: number
  volume: number
  has_audio: boolean
}

export interface EditorExportResult {
  project_dir: string
  video_path: string
  video_url: string
  subtitle_path: string | null
  manifest_path: string
  warnings: string[]
}

export interface EditorSpeechCueRequest {
  item_id: string
  track_id: string
  cue_id: string
  start_ms: number
  text: string
  language: string
}

export interface EditorSpeechRequest {
  job_id: string
  project_id: string
  title: string
  output_dir: string
  engine_id: string
  model_id?: string
  device: string
  language: string
  speed: number
  max_workers?: number
  voice: {
    source: string
    profile_id: string
    reference_audio: string
    reference_text: string
    instruction: string
  }
  engine_options: Record<string, unknown>
  cues: EditorSpeechCueRequest[]
}

export interface EditorSpeechItemResult {
  item_id: string
  track_id: string
  cue_id: string
  start_ms: number
  status: 'done' | 'failed'
  wav_path: string | null
  error: string | null
  warnings: string[]
}

export interface EditorSpeechResult {
  job_id: string
  project_id: string
  root_dir: string
  status: 'completed' | 'partial' | 'failed'
  completed_count: number
  failed_count: number
  total_count: number
  items: EditorSpeechItemResult[]
}

export interface EditorSpeechItemEvent extends EditorSpeechItemResult {
  job_id: string
  task_id: string
  completed: number
  failed: number
  total: number
}

export function loadEditorMedia(path: string, kind: 'video' | 'audio'): Promise<EditorMedia> {
  return apiJson<EditorMedia>('/api/editor/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, kind }),
  })
}

export function loadEditorCues(path: string, durationMs?: number): Promise<EditorSubtitleAsset> {
  return apiJson<EditorSubtitleAsset>('/api/editor/cues', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, duration_ms: durationMs }),
  })
}

export async function startEditorExport(request: EditorExportRequest): Promise<string> {
  const response = await apiJson<{ task_id: string }>('/api/editor/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return response.task_id
}

export function startEditorSpeech(request: EditorSpeechRequest): Promise<{ job_id: string; task_id: string }> {
  return apiJson<{ job_id: string; task_id: string }>('/api/editor/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

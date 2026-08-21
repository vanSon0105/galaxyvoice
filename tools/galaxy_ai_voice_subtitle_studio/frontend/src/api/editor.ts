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
}

export interface EditorExportResult {
  project_dir: string
  video_path: string
  video_url: string
  subtitle_path: string | null
  manifest_path: string
  warnings: string[]
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

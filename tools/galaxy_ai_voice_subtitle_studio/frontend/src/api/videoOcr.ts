import { apiJson } from './client'

export interface VideoOcrRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface VideoOcrMeta {
  runtime_ready: boolean
  runtime_path: string
  installer_available: boolean
  modes: Array<{ code: 'fast' | 'accurate'; label: string; sample_fps: number }>
}

export interface VideoOcrCue {
  index: number
  start_ms: number
  end_ms: number
  text: string
  confidence: number
  boxes: Array<{ x: number; y: number; width: number; height: number }>
}

export interface VideoOcrResult {
  project_dir: string
  srt_path: string
  manifest_path: string
  source_video_path: string
  cues: VideoOcrCue[]
  sampled_frames: number
  ocr_frames: number
  reused_frames: number
  probe_runs?: number
  rescue_frames?: number
  discarded_static_cues?: number
  cache_hit: boolean
}

export interface VideoOcrRequest {
  galaxy_project_id: string
  video_path: string
  output_dir: string
  project_name: string
  mode: 'fast' | 'accurate'
  language: string
  region: VideoOcrRegion
}

export const fetchVideoOcrMeta = (): Promise<VideoOcrMeta> =>
  apiJson<VideoOcrMeta>('/api/editor/ocr/meta')

export const installVideoOcr = (): Promise<{ task_id: string }> =>
  apiJson<{ task_id: string }>('/api/editor/ocr/install', { method: 'POST' })

export const startVideoOcr = (request: VideoOcrRequest): Promise<{ task_id: string }> =>
  apiJson<{ task_id: string }>('/api/editor/ocr/recognize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

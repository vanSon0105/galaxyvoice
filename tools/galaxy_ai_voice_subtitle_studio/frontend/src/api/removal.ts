import { apiFetch, apiJson } from './client'

export interface RemovalMode {
  code: string
  label: string
  uses_ai: boolean
}

export interface RemovalMeta {
  modes: RemovalMode[]
  region_presets: RemovalRegionPreset[]
  propainter_ready: boolean
  runtime_path: string
  installer_available: boolean
}

export interface RemovalSource {
  source_id: string
  url: string
  width: number
  height: number
  duration: number
  name: string
}

export interface RemovalRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface RemovalRegionPreset {
  code: string
  name: string
  region: RemovalRegion
}

export interface RemovalMask {
  id: string
  name: string
  region: RemovalRegion
  start_seconds: number
  end_seconds: number | null
}

export interface RemovalRequest {
  galaxy_project_id: string
  video_path: string
  output_dir: string
  project_name: string
  mode: string
  region: RemovalRegion
  blur_strength: number
  processing_device: string
  license_accepted: boolean
  masks?: RemovalMask[]
}

export interface RemovalResult {
  project_dir: string
  video_path: string
  video_url: string
  manifest_path: string
  mode: string
  warnings: string[]
  source_video_path: string
  masks: RemovalMask[]
}

export const fetchRemovalMeta = (): Promise<RemovalMeta> =>
  apiJson<RemovalMeta>('/api/removal/modes')

export const registerRemovalSource = (videoPath: string): Promise<RemovalSource> =>
  apiJson<RemovalSource>('/api/removal/source', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_path: videoPath }),
  })

export async function fetchRemovalPreview(
  videoPath: string,
  timestampSeconds: number,
  region: RemovalRegion,
): Promise<Blob> {
  const response = await apiFetch('/api/removal/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_path: videoPath,
      timestamp_seconds: timestampSeconds,
      region,
    }),
  })
  if (!response.ok) throw new Error(`Không tạo được ảnh xem trước (${response.status}).`)
  return response.blob()
}

export const startSubtitleRemoval = (
  payload: RemovalRequest,
): Promise<{ task_id: string }> =>
  apiJson<{ task_id: string }>('/api/removal/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const installProPainter = (device: string): Promise<{ task_id: string }> =>
  apiJson<{ task_id: string }>('/api/removal/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device }),
  })

import { apiJson } from './client'

export interface AudioOption {
  code: string
  label: string
}

export interface MethodControls {
  segment_label: string
  segment_values: string[]
  segment_default: string
  overlap_label: string
  overlap_values: string[]
  overlap_default: string
}

export interface AudioPreset {
  method?: string
  model_filename?: string
  output_format?: string
  segment_size?: string
  overlap?: string
  processing_device?: string
  gpu_conversion?: boolean
  vocals_only?: boolean
  instrumental_only?: boolean
  sample_mode?: boolean
}

export interface AudioMeta {
  methods: AudioOption[]
  devices: AudioOption[]
  formats: string[]
  method_controls: Record<string, MethodControls>
  builtin_presets: Record<string, AudioPreset>
  uvr_root: string
  managed_models_root: string
  runtime_path: string
  installer_available: boolean
}

export interface AudioModel {
  method: string
  label: string
  filename: string
}

export interface DownloadableAudioModel {
  filename: string
  name: string
  model_type: string
  method: string
  stems: string[]
  installed: boolean
}

export interface AudioPresets {
  builtin: Record<string, AudioPreset>
  custom: Record<string, AudioPreset>
}

export interface AudioRuntimeStatus {
  state: 'checking' | 'ready' | 'unavailable'
  ready: boolean
  message: string
  resolved_device: string | null
}

export interface SeparationRequest {
  galaxy_project_id: string
  input_path: string
  output_dir: string
  project_name: string
  method: string
  model_filename: string
  output_format: string
  segment_size: string
  overlap: string
  processing_device: string
  gpu_conversion: boolean
  vocals_only: boolean
  instrumental_only: boolean
  sample_mode: boolean
}

export interface SeparationResult {
  project_dir: string
  output_paths: string[]
  files: { name: string; url: string }[]
  manifest_path: string
  warnings: string[]
}

export function fetchAudioMeta(): Promise<AudioMeta> {
  return apiJson<AudioMeta>('/api/audio/meta')
}

export function fetchAudioModels(refresh = false): Promise<AudioModel[]> {
  return apiJson<AudioModel[]>(`/api/audio/models${refresh ? '?refresh=true' : ''}`)
}

export function fetchAudioModelCatalog(refresh = false): Promise<DownloadableAudioModel[]> {
  return apiJson<DownloadableAudioModel[]>(
    `/api/audio/models/catalog${refresh ? '?refresh=true' : ''}`,
  )
}

export function startAudioModelDownload(filename: string): Promise<{ task_id: string }> {
  return apiJson('/api/audio/models/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  })
}

export function fetchAudioPresets(): Promise<AudioPresets> {
  return apiJson<AudioPresets>('/api/audio/presets')
}

export function fetchAudioRuntime(
  device: string,
  method: string,
  refresh = false,
): Promise<AudioRuntimeStatus> {
  const params = new URLSearchParams({ device, method })
  if (refresh) params.set('refresh', 'true')
  return apiJson<AudioRuntimeStatus>(`/api/audio/runtime?${params}`)
}

export function saveAudioPreset(name: string, settings: AudioPreset): Promise<unknown> {
  return apiJson('/api/audio/presets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, settings }),
  })
}

export function deleteAudioPreset(name: string): Promise<{ ok: boolean }> {
  return apiJson(`/api/audio/presets/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export function installAudioRuntime(device: string): Promise<{ task_id: string }> {
  return apiJson('/api/audio/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device }),
  })
}

export function startAudioSeparation(payload: SeparationRequest): Promise<{ task_id: string }> {
  return apiJson('/api/audio/separate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

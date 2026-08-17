import { apiJson } from './client'
import type { Option } from './settings'

export interface DesignOption {
  label: string
  value: string
}

export interface DesignOptions {
  gender: DesignOption[]
  age: DesignOption[]
  pitch: DesignOption[]
  style: DesignOption[]
  accent: DesignOption[]
  dialect: DesignOption[]
}

export interface OmniVoiceStatus {
  installed: boolean
  message: string
  python_path: string
  languages: string[]
  devices: Option[]
  design_options: DesignOptions
}

export interface VoiceProfile {
  profile_id: string
  display_name: string
  language: string
  created_at: string
  reference_text: string
  has_reference_audio: boolean
}

export interface OmniVoiceGenerateRequest {
  mode: 'auto' | 'clone' | 'design'
  text: string
  output_dir: string
  project_name?: string
  model_id?: string
  device?: string
  language?: string
  reference_audio?: string
  reference_text?: string
  profile_id?: string
  save_profile_name?: string
  instruct?: string
  num_step?: number
  guidance_scale?: number
  t_shift?: number
  layer_penalty_factor?: number
  position_temperature?: number
  class_temperature?: number
  speed?: number
  duration?: number | null
  denoise?: boolean
  normalize_text?: boolean
  preprocess_prompt?: boolean
  postprocess_output?: boolean
  audio_chunk_duration?: number
  audio_chunk_threshold?: number
  pad_duration?: number
  fade_duration?: number
  export_mp3?: boolean
  enable_flashinfer?: boolean
  flashinfer_cuda_graph?: boolean
  lora_adapter?: string
}

export interface OmniVoiceBatchRequest {
  source: string
  long_form: boolean
  combine: boolean
  gap_ms: number
  mode: 'auto' | 'clone' | 'design'
  output_dir: string
  project_name?: string
  model_id?: string
  device?: string
  language?: string
  speed?: number
  duration?: number | null
  export_mp3?: boolean
}

export interface GenerateResultPayload {
  project_dir: string
  wav_path: string
  mp3_path: string | null
  manifest_path: string
  profile_id: string
  warnings: string[]
}

export interface BatchResultPayload {
  project_dir: string
  manifest_path: string
  combined_wav_path: string | null
  combined_mp3_path: string | null
  preview_path: string | null
  item_count: number
  warnings: string[]
}

export function fetchOmniVoiceStatus(): Promise<OmniVoiceStatus> {
  return apiJson<OmniVoiceStatus>('/api/omnivoice/status')
}

export function installOmniVoiceRuntime(): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>('/api/omnivoice/install', { method: 'POST' })
}

export function startOmniVoiceGenerate(
  body: OmniVoiceGenerateRequest,
): Promise<{ task_id: string }> {
  return apiJson<{ task_id: string }>('/api/omnivoice/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function startOmniVoiceBatch(body: OmniVoiceBatchRequest): Promise<{ task_id: string }> {
  return apiJson<{ task_id: string }>('/api/omnivoice/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function fetchProfiles(): Promise<VoiceProfile[]> {
  return apiJson<VoiceProfile[]>('/api/omnivoice/profiles')
}

export function deleteProfile(profileId: string): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>(`/api/omnivoice/profiles/${encodeURIComponent(profileId)}`, {
    method: 'DELETE',
  })
}

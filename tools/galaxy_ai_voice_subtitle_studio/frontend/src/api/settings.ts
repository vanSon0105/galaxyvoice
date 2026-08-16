import { apiJson } from './client'

/** Flat settings record mirroring AppConfig (no secrets — the backend
 *  deliberately excludes API keys from the config). */
export type AppSettings = Record<string, string | number | boolean | undefined>

export interface Option {
  code: string
  label: string
}

export interface ProviderMeta extends Option {
  default_model: string
  default_base_url: string
  models: string[]
}

export interface SettingsMeta {
  tts_engines: Option[]
  default_tts_engine: string
  whisper_models: string[]
  translation_providers: ProviderMeta[]
  default_translation_provider: string
  source_languages: Option[]
  target_languages: Option[]
  processing_devices: Option[]
  audio_methods: Option[]
  audio_devices: Option[]
  audio_formats: string[]
  removal_modes: Option[]
  editor_resolutions: Option[]
  editor_fps: Option[]
  editor_encoders: Option[]
  editor_audio_modes: Option[]
  omnivoice_devices: Option[]
}

export function fetchSettings(): Promise<AppSettings> {
  return apiJson<AppSettings>('/api/settings')
}

export function updateSettings(patch: Record<string, unknown>): Promise<AppSettings> {
  return apiJson<AppSettings>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export function fetchSettingsMeta(): Promise<SettingsMeta> {
  return apiJson<SettingsMeta>('/api/settings/meta')
}

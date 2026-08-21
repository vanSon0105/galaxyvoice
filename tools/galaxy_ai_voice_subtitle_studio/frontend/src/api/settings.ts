import { apiJson } from './client'

/** Flat settings record mirroring AppConfig. Provider keys are stored only in
 *  the Windows user environment and deliberately excluded from this record. */
export type AppSettings = Record<string, string | number | boolean | undefined>

export interface Option {
  code: string
  label: string
}

export interface ProviderMeta extends Option {
  default_model: string
  default_base_url: string
  models: string[]
  api_key_configured: boolean
  api_key_environment_name: string
}

export interface SavedTranslationApiKey {
  provider: string
  environment_name: string
  configured: boolean
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

export function saveTranslationApiKey(
  provider: string,
  apiKey: string,
): Promise<SavedTranslationApiKey> {
  return apiJson<SavedTranslationApiKey>('/api/settings/translation-api-key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, api_key: apiKey }),
  })
}

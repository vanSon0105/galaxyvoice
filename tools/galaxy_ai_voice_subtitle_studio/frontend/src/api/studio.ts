import { apiJson } from './client'

export type StudioVoiceSource = 'auto' | 'profile' | 'reference' | 'design'

export interface StudioVoiceRequest {
  source: StudioVoiceSource
  profile_id?: string
  reference_audio?: string
  reference_text?: string
  save_profile_name?: string
  instruction?: string
  consent_confirmed?: boolean
  consent_basis?: string
  consent_statement?: string
}

export interface StudioGenerationRequest {
  project_id: string
  title: string
  text: string
  engine_id?: string
  language: string
  output_dir: string
  output_name: string
  model_id?: string
  device?: string
  speed: number
  duration?: number | null
  formats: ('wav' | 'mp3')[]
  voice: StudioVoiceRequest
  engine_options?: {
    num_step?: number
    guidance_scale?: number
    t_shift?: number
    denoise?: boolean
    normalize_text?: boolean
    preprocess_prompt?: boolean
    postprocess_output?: boolean
  }
}

export interface StudioTake {
  take_id: string
  project_id: string
  title: string
  engine_id: string
  text: string
  language: string
  voice_source: StudioVoiceSource
  voice_profile_id: string
  speed: number
  formats: string[]
  project_dir: string
  wav_path: string
  mp3_path: string | null
  manifest_path: string
  profile_id: string
  warnings: string[]
  generation_run_id: string
  starred: boolean
  primary: boolean
  rerun_of: string
  created_at: string
  audio_url: string
}

export const startStudioGeneration = (body: StudioGenerationRequest) =>
  apiJson<{ task_id: string }>('/api/studio/generations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const fetchStudioTakes = (params: {
  project_id?: string
  query?: string
  starred_only?: boolean
} = {}) => {
  const search = new URLSearchParams()
  if (params.project_id) search.set('project_id', params.project_id)
  if (params.query) search.set('query', params.query)
  if (params.starred_only) search.set('starred_only', 'true')
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return apiJson<StudioTake[]>(`/api/studio/takes${suffix}`)
}

export const setStudioTakeStarred = (takeId: string, starred: boolean) =>
  apiJson<StudioTake>(`/api/studio/takes/${encodeURIComponent(takeId)}/starred`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ starred }),
  })

export const setStudioTakePrimary = (takeId: string, primary: boolean) =>
  apiJson<StudioTake>(`/api/studio/takes/${encodeURIComponent(takeId)}/primary`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ primary }),
  })

export const rerunStudioTake = (takeId: string) =>
  apiJson<{ task_id: string }>(`/api/studio/takes/${encodeURIComponent(takeId)}/rerun`, {
    method: 'POST',
  })

export const deleteStudioTake = (takeId: string) =>
  apiJson<{ ok: boolean }>(`/api/studio/takes/${encodeURIComponent(takeId)}`, {
    method: 'DELETE',
  })

export const studioTakeAudioUrl = (
  take: StudioTake,
  format?: 'wav' | 'mp3',
  download = false,
) => {
  const selected = format ?? (take.formats.includes('mp3') && take.mp3_path ? 'mp3' : 'wav')
  return `${take.audio_url}?format=${selected}${download ? '&download=true' : ''}`
}

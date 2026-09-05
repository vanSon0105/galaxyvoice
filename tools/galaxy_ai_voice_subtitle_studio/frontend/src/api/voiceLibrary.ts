import { apiJson } from './client'

export type LibraryVoiceSource = 'system' | 'imported' | 'cloned' | 'designed'

export interface LibraryVoiceSelection {
  source: 'system' | 'profile' | 'reference' | 'design'
  profile_id: string
  reference_audio: string
  reference_text: string
  instruction: string
  system_engine: string
  system_voice: string
}

export interface LibraryVoice {
  voice_id: string
  revision: number
  name: string
  source: LibraryVoiceSource
  language: string
  engine_id: string
  selection: LibraryVoiceSelection
  tags: string[]
  notes: string
  favorite: boolean
  consent: {
    confirmed: boolean
    basis: string
    statement: string
    recorded_at: string
    provenance: string
  }
  stable_sample: boolean
  created_at: string
  updated_at: string
  capabilities: string[]
  preview_available: boolean
  preview_url: string
  usage_count: number
  editable: boolean
  identity_editable: boolean
  deletable: boolean
  compatibility: Record<'studio' | 'batch' | 'editor', boolean>
}

export const fetchLibraryVoices = (params: {
  query?: string
  source?: string
  language?: string
  favorite_only?: boolean
} = {}) => {
  const search = new URLSearchParams()
  if (params.query) search.set('query', params.query)
  if (params.source) search.set('source', params.source)
  if (params.language) search.set('language', params.language)
  if (params.favorite_only) search.set('favorite_only', 'true')
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return apiJson<LibraryVoice[]>(`/api/voice-library/voices${suffix}`)
}

export const updateLibraryVoice = (voiceId: string, body: {
  name?: string
  language?: string
  tags?: string[]
  notes?: string
  favorite?: boolean
  consent?: { confirmed: boolean; basis?: string; statement?: string; provenance?: string }
}) => apiJson<LibraryVoice>(`/api/voice-library/voices/${encodeURIComponent(voiceId)}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const importLibraryAudio = (body: {
  name: string
  source: 'imported' | 'cloned'
  language: string
  audio_path: string
  reference_text?: string
  tags?: string[]
  notes?: string
  consent?: { confirmed: boolean; basis?: string; statement?: string; provenance?: string }
}) => apiJson<LibraryVoice>('/api/voice-library/voices/import-audio', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const createDesignedVoice = (body: {
  name: string
  language: string
  instruction: string
  tags?: string[]
  notes?: string
}) => apiJson<LibraryVoice>('/api/voice-library/voices/design', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const deleteLibraryVoice = (voiceId: string, force = false) =>
  apiJson<{ ok: boolean }>(`/api/voice-library/voices/${encodeURIComponent(voiceId)}?force=${force}`, { method: 'DELETE' })

export const exportLibraryVoice = (voiceId: string, outputPath: string) =>
  apiJson<{ path: string }>(`/api/voice-library/voices/${encodeURIComponent(voiceId)}/export`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ output_path: outputPath }),
  })

export const importLibraryBundle = (bundlePath: string) => apiJson<LibraryVoice>('/api/voice-library/import', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bundle_path: bundlePath }),
})

export const pinLibraryVoice = (voiceId: string, projectId: string) =>
  apiJson<{ snapshot_path: string }>(`/api/voice-library/voices/${encodeURIComponent(voiceId)}/pin`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: projectId }),
  })

export const setStableSample = (voiceId: string, audioPath: string, referenceText = '') =>
  apiJson<LibraryVoice>(`/api/voice-library/voices/${encodeURIComponent(voiceId)}/stable-sample`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audio_path: audioPath, reference_text: referenceText }),
  })

export function libraryVoiceRequest(voice: LibraryVoice) {
  return {
    source: voice.selection.source === 'system' ? 'auto' : voice.selection.source,
    profile_id: voice.selection.profile_id,
    reference_audio: voice.selection.reference_audio,
    reference_text: voice.selection.reference_text,
    instruction: voice.selection.instruction,
  } as const
}

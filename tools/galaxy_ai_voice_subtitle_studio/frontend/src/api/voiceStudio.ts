import { apiJson } from './client'

export interface VoiceStudioStatus {
  installed: boolean
  version: string
  message: string
  backend_online: boolean
  update_required: boolean
  missing_components: string[]
  backend_url?: string
}

export interface VoiceStudioInstallResponse {
  task_id: string
}

export interface VoiceStudioLaunchResponse {
  result: 'attached' | 'local'
  url: string
}

export function fetchVoiceStudioStatus(): Promise<VoiceStudioStatus> {
  return apiJson<VoiceStudioStatus>('/api/voicestudio/status')
}

export function launchVoiceStudio(): Promise<VoiceStudioLaunchResponse> {
  return apiJson<VoiceStudioLaunchResponse>('/api/voicestudio/launch', { method: 'POST' })
}

export function installVoiceStudio(body: Record<string, never> = {}): Promise<VoiceStudioInstallResponse> {
  return apiJson<VoiceStudioInstallResponse>('/api/voicestudio/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function stopVoiceStudio(): Promise<{ success: boolean }> {
  return apiJson<{ success: boolean }>('/api/voicestudio/stop', { method: 'POST' })
}
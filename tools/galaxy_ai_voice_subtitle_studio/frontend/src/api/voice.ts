import { apiJson } from './client'

export interface EngineInfo {
  code: string
  label: string
  available: boolean
  unavailable_reason: string | null
}

export interface VoiceInfo {
  name: string
  culture: string
  gender: string
  age: string
}

export interface GenerateRequest {
  text: string
  output_dir: string
  project_name?: string
  engine?: string
  voice_name?: string | null
  rate?: number
  volume?: number
  pause_ms?: number
  max_chars?: number
  export_mp3?: boolean
  keep_segments?: boolean
  source_language?: string
  target_language?: string
  ai_provider?: string
  ai_model?: string
  ai_base_url?: string
  ai_api_key?: string
}

export interface ExtractAudioRequest {
  video_path: string
  output_dir: string
  project_name?: string
  export_wav?: boolean
  export_mp3?: boolean
}

export interface TranscribeRequest {
  video_path: string
  output_dir: string
  project_name?: string
  source_language?: string
  target_language?: string
  whisper_model?: string
  processing_device?: string
  ai_provider?: string
  ai_model?: string
  ai_base_url?: string
  ai_api_key?: string
  translation_batch_size?: number
  translation_workers?: number
}

export interface DraftPayload {
  task_id: string
  source_video: string
  project_name: string
  source_language: string
  target_language: string
  whisper_model: string
  ai_provider: string
  ai_model: string
  ai_base_url: string
  source_srt: string
  translated_srt: string | null
  script_text: string
  script_language: string
  warnings: string[]
}

export interface ExportResult {
  project_dir: string
  audio_path: string
  source_srt_path: string
  translated_srt_path: string | null
  manifest_path: string
  cue_count: number
  script_text: string
  script_language: string
  warnings: string[]
}

export interface GenerateResultPayload {
  project_dir: string
  wav_path: string
  srt_path: string
  mp3_path: string | null
  manifest_path: string
  cue_count: number
  total_duration_ms: number
  warnings: string[]
  translated_text?: string | null
  target_language?: string | null
}

export interface ExtractResultPayload {
  project_dir: string
  wav_path: string | null
  mp3_path: string | null
  manifest_path: string
  warnings: string[]
}

function startTask(path: string, body: unknown): Promise<{ task_id: string }> {
  return apiJson<{ task_id: string }>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function fetchEngines(): Promise<EngineInfo[]> {
  return apiJson<EngineInfo[]>('/api/voice/engines')
}

export function fetchVoices(engine: string): Promise<VoiceInfo[]> {
  return apiJson<VoiceInfo[]>(`/api/voice/voices?engine=${encodeURIComponent(engine)}`)
}

export const startGenerate = (body: GenerateRequest) => startTask('/api/voice/generate', body)
export const startExtractAudio = (body: ExtractAudioRequest) =>
  startTask('/api/voice/extract-audio', body)
export const startTranscribe = (body: TranscribeRequest) => startTask('/api/voice/transcribe', body)

export function fetchDraft(taskId: string): Promise<DraftPayload> {
  return apiJson<DraftPayload>(`/api/voice/draft/${encodeURIComponent(taskId)}`)
}

export function updateDraft(
  taskId: string,
  body: { source_srt?: string; translated_srt?: string },
): Promise<DraftPayload> {
  return apiJson<DraftPayload>(`/api/voice/draft/${encodeURIComponent(taskId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function exportDraft(
  taskId: string,
  body: { output_dir?: string; project_name?: string },
): Promise<ExportResult> {
  return apiJson<ExportResult>(`/api/voice/draft/${encodeURIComponent(taskId)}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function openPath(path: string): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>('/api/system/open-path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
}

/** URL of a file inside a finished task's result directory. */
export function taskFileUrl(taskId: string, name: string): string {
  return `/api/files/task/${encodeURIComponent(taskId)}/${encodeURIComponent(name)}`
}

import { apiJson } from './client'

export type AudioFormat = 'wav' | 'mp3' | 'flac' | 'm4a'

export interface AudioPostSource {
  source_id: string
  label: string
  path: string
  role: string
  preview_url?: string
  selected?: boolean
  gain_db?: number
}

export interface WaveformData {
  duration_ms: number
  peaks: number[]
}

export interface AudioExportResult {
  export_id: string
  project_dir: string
  files: Partial<Record<AudioFormat, string>>
  media_urls: Partial<Record<AudioFormat, string>>
  manifest_path: string
  warnings: string[]
}

export interface AudioExportPayload {
  project_id: string
  workspace: string
  project_dir: string
  title: string
  sources: Array<{
    source_id: string
    path: string
    role: string
    selected: boolean
    gain_db: number
  }>
  formats: AudioFormat[]
  chain: {
    trim_start_ms: number
    trim_end_ms: number | null
    gain_db: number
    segment_gains: Array<{ start_ms: number; end_ms: number; gain_db: number }>
    fade_in_ms: number
    fade_out_ms: number
    normalize: boolean
    target_lufs: number
    true_peak_db: number
    loudness_range: number
    preset: 'none' | 'voice_clean' | 'podcast'
    trim_silence: boolean
  }
  metadata: { title: string; artist: string; album: string; comment: string }
  sample_rate: number
  channels: number
  bitrate_kbps: number
}

export const fetchWaveform = (sourcePath: string, projectDir: string, points = 256) =>
  apiJson<WaveformData>('/api/audio-post/waveform', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: sourcePath, project_dir: projectDir, points }),
  })

export const discoverProjectAudio = (projectDir: string) =>
  apiJson<AudioPostSource[]>(`/api/audio-post/sources?project_dir=${encodeURIComponent(projectDir)}`)

export const exportAudio = (body: AudioExportPayload) =>
  apiJson<AudioExportResult>('/api/audio-post/exports', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

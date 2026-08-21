import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as editorApi from '../api/editor'
import * as settingsApi from '../api/settings'
import type { SettingsMeta } from '../api/settings'
import { EditorPage } from './EditorPage'

vi.mock('../ws/useTasks', () => ({ useTasks: () => ({ tasks: [], cancelTask: vi.fn() }) }))

const SETTINGS_META: SettingsMeta = {
  tts_engines: [], default_tts_engine: '', whisper_models: [], translation_providers: [],
  default_translation_provider: '', source_languages: [], target_languages: [], processing_devices: [],
  audio_methods: [], audio_devices: [], audio_formats: [], removal_modes: [],
  editor_resolutions: [{ code: 'original', label: 'Theo video gốc' }],
  editor_fps: [{ code: 'source', label: 'Theo video gốc' }],
  editor_encoders: [{ code: 'auto', label: 'Tự động' }],
  editor_audio_modes: [{ code: 'mix', label: 'Trộn âm thanh' }], omnivoice_devices: [],
}

afterEach(() => vi.restoreAllMocks())

describe('EditorPage', () => {
  it('keeps imported media in the bin until it is added to the timeline', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ editor_output_dir: 'D:/result', editor_timeline_zoom: 8 })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(editorApi, 'loadEditorMedia').mockResolvedValue({
      source_id: 'video-1', url: '/api/editor/source/video-1', name: 'clip.mp4', path: 'D:/clip.mp4',
      kind: 'video', duration_seconds: 30, width: 1920, height: 1080, fps: 30, has_audio: true,
    })
    vi.spyOn(settingsApi, 'updateSettings').mockRejectedValue(new Error('Không lưu được config'))
    const startExport = vi.spyOn(editorApi, 'startEditorExport')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.change(await screen.findByPlaceholderText('Đường dẫn tệp'), { target: { value: 'D:/clip.mp4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nạp' }))
    expect(await screen.findByText('clip.mp4')).toBeInTheDocument()
    expect(screen.getByText('Chưa có project')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    expect(await screen.findByText(/1920×1080/)).toBeInTheDocument()
    expect(document.querySelector('.editor-video-stage video')).toHaveAttribute('src', '/api/editor/source/video-1')

    fireEvent.click(screen.getByRole('button', { name: 'Xuất video' }))
    expect(await screen.findByText('Không lưu được config')).toBeInTheDocument()
    expect(startExport).not.toHaveBeenCalled()
  })
})

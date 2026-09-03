import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as editorApi from '../api/editor'
import * as batchApi from '../api/batch'
import * as settingsApi from '../api/settings'
import * as voiceLibraryApi from '../api/voiceLibrary'
import type { SettingsMeta } from '../api/settings'
import * as dialogs from '../lib/dialogs'
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

afterEach(() => { cleanup(); vi.restoreAllMocks() })

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

  it('starts subtitle speech generation with a selected library voice', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/result', omnivoice_device: 'auto' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(dialogs, 'pickSrtFile').mockResolvedValue('D:/captions.srt')
    vi.spyOn(editorApi, 'loadEditorCues').mockResolvedValue({
      name: 'captions.srt', path: 'D:/captions.srt', cues: [{ index: 1, start_ms: 1_000, end_ms: 2_000, text: 'Xin chào' }],
    })
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([{
      voice_id: 'son', revision: 1, name: 'Sơn', source: 'cloned', language: 'vi', engine_id: 'omnivoice',
      selection: { source: 'profile', profile_id: 'son-profile', reference_audio: '', reference_text: '', instruction: '', system_engine: '', system_voice: '' },
      tags: [], notes: '', favorite: false, consent: { confirmed: true, basis: '', statement: '', recorded_at: '', provenance: '' },
      stable_sample: true, created_at: '', updated_at: '', capabilities: [], preview_available: false, preview_url: '', usage_count: 0,
      editable: true, identity_editable: true, deletable: true, compatibility: { studio: true, batch: true, editor: true, longform: true, dubbing: true },
    }])
    const startBatch = vi.spyOn(batchApi, 'startBatchRun').mockResolvedValue({ batch_id: 'batch-1', task_id: 'task-1' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    fireEvent.change(await screen.findByLabelText('Giọng từ Thư viện'), { target: { value: 'son' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chuyển thành audio' }))

    expect(startBatch).toHaveBeenCalledWith(expect.objectContaining({
      combine: false,
      voice: expect.objectContaining({ profile_id: 'son-profile' }),
      items: [expect.objectContaining({ text: 'Xin chào' })],
    }))
  })

  it('generates subtitle audio with a selected Windows system voice', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/result', omnivoice_device: 'auto' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(dialogs, 'pickSrtFile').mockResolvedValue('D:/captions.srt')
    vi.spyOn(editorApi, 'loadEditorCues').mockResolvedValue({
      name: 'captions.srt', path: 'D:/captions.srt', cues: [{ index: 1, start_ms: 0, end_ms: 1_000, text: 'Hello' }],
    })
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([{
      voice_id: 'system:sapi:Microsoft David Desktop', revision: 1, name: 'Microsoft David Desktop', source: 'system', language: 'en-US', engine_id: 'sapi',
      selection: { source: 'system', profile_id: '', reference_audio: '', reference_text: '', instruction: '', system_engine: 'sapi', system_voice: 'Microsoft David Desktop' },
      tags: [], notes: '', favorite: false, consent: { confirmed: false, basis: '', statement: '', recorded_at: '', provenance: '' },
      stable_sample: false, created_at: '', updated_at: '', capabilities: ['sapi.tts'], preview_available: false, preview_url: '', usage_count: 0,
      editable: true, identity_editable: false, deletable: false, compatibility: { studio: false, batch: false, editor: true, longform: false, dubbing: false },
    }])
    const startBatch = vi.spyOn(batchApi, 'startBatchRun').mockResolvedValue({ batch_id: 'batch-1', task_id: 'task-1' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    const option = await screen.findByRole('option', { name: 'Microsoft David Desktop · en-US' })
    expect(option).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText('Giọng từ Thư viện'), { target: { value: 'system:sapi:Microsoft David Desktop' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chuyển thành audio' }))

    expect(startBatch).toHaveBeenCalledWith(expect.objectContaining({
      engine_id: 'sapi',
      device: 'cpu',
      engine_options: { voice_name: 'Microsoft David Desktop' },
      voice: expect.objectContaining({ source: 'auto' }),
      items: [expect.objectContaining({ text: 'Hello' })],
    }))
  })

  it('keeps SRT timestamps aligned to the video instead of offsetting them by the playhead', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ editor_output_dir: 'D:/result', editor_timeline_zoom: 10 })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([])
    vi.spyOn(editorApi, 'loadEditorMedia').mockResolvedValue({
      source_id: 'video-1', url: '/api/editor/source/video-1', name: 'clip.mp4', path: 'D:/clip.mp4',
      kind: 'video', duration_seconds: 30, width: 1920, height: 1080, fps: 30, has_audio: true,
    })
    vi.spyOn(dialogs, 'pickSrtFile').mockResolvedValue('D:/captions.srt')
    vi.spyOn(editorApi, 'loadEditorCues').mockResolvedValue({
      name: 'captions.srt', path: 'D:/captions.srt',
      cues: [{ index: 1, start_ms: 1_000, end_ms: 2_000, text: 'Khớp video' }],
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.change(await screen.findByPlaceholderText('Đường dẫn tệp'), { target: { value: 'D:/clip.mp4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nạp' }))
    const videoAsset = (await screen.findByText('clip.mp4')).closest('.editor-asset') as HTMLElement
    fireEvent.click(within(videoAsset).getByTitle('Đưa vào timeline'))

    const timeline = container.querySelector('.editor-timeline-svg') as SVGSVGElement
    fireEvent.pointerDown(timeline, { button: 0, pointerId: 1, clientX: 330 })
    fireEvent.pointerUp(timeline, { pointerId: 1, clientX: 330 })

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    const subtitleAsset = (await screen.findByText('captions.srt')).closest('.editor-asset') as HTMLElement
    fireEvent.click(within(subtitleAsset).getByTitle('Đưa vào timeline'))

    expect(await screen.findByDisplayValue('00:01.000')).toBeInTheDocument()
  })

  it('removes a populated subtitle track from its inline delete button', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/result' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([])
    vi.spyOn(dialogs, 'pickSrtFile').mockResolvedValue('D:/captions.srt')
    vi.spyOn(editorApi, 'loadEditorCues').mockResolvedValue({
      name: 'captions.srt', path: 'D:/captions.srt', cues: [
        { index: 1, start_ms: 0, end_ms: 1_000, text: 'Câu một' },
        { index: 2, start_ms: 1_000, end_ms: 2_000, text: 'Câu hai' },
      ],
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    expect((await screen.findAllByText('Câu một')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Xóa Phụ đề 1' }))

    expect(window.confirm).toHaveBeenCalledWith('Xóa Phụ đề 1 và 2 mục đang có trên track?')
    expect(screen.queryAllByText('Câu một')).toHaveLength(0)
    expect(screen.queryAllByText('Câu hai')).toHaveLength(0)
    expect(screen.queryByText('Phụ đề 1')).not.toBeInTheDocument()
  })
})

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as editorApi from '../api/editor'
import * as removalApi from '../api/removal'
import * as settingsApi from '../api/settings'
import * as videoOcrApi from '../api/videoOcr'
import * as voiceLibraryApi from '../api/voiceLibrary'
import type { SettingsMeta } from '../api/settings'
import * as dialogs from '../lib/dialogs'
import { publishEvent } from '../ws/hub'
import { EditorPage } from './EditorPage'

const taskState = vi.hoisted(() => ({ tasks: [] as Array<Record<string, unknown>>, cancelTask: vi.fn() }))

vi.mock('../ws/useTasks', () => ({ useTasks: () => taskState }))

const SETTINGS_META: SettingsMeta = {
  tts_engines: [], default_tts_engine: '', whisper_models: [], translation_providers: [],
  default_translation_provider: '', source_languages: [], target_languages: [], processing_devices: [],
  audio_methods: [], audio_devices: [], audio_formats: [], removal_modes: [],
  editor_resolutions: [{ code: 'original', label: 'Theo video gốc' }],
  editor_fps: [{ code: 'source', label: 'Theo video gốc' }],
  editor_encoders: [{ code: 'auto', label: 'Tự động' }],
  editor_audio_modes: [{ code: 'mix', label: 'Trộn âm thanh' }], omnivoice_devices: [],
}

afterEach(() => {
  cleanup()
  taskState.tasks = []
  taskState.cancelTask.mockReset()
  vi.restoreAllMocks()
})

describe('EditorPage', () => {
  it('keeps raw OCR in the media bin until the reviewed cues are explicitly placed', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ editor_output_dir: 'D:/result' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([])
    vi.spyOn(editorApi, 'loadEditorMedia').mockResolvedValue({
      source_id: 'video-ocr', url: '/api/editor/source/video-ocr', name: 'burned.mp4', path: 'D:/burned.mp4',
      kind: 'video', duration_seconds: 30, width: 1920, height: 1080, fps: 30, has_audio: true,
    })
    vi.spyOn(videoOcrApi, 'fetchVideoOcrMeta').mockResolvedValue({
      runtime_ready: true, runtime_path: 'D:/ocr/python.exe', installer_available: true,
      modes: [{ code: 'fast', label: 'Nhanh', sample_fps: 2 }],
    })
    vi.spyOn(removalApi, 'fetchRemovalMeta').mockResolvedValue({
      modes: [{ code: 'blur', label: 'Làm mờ' }],
      region_presets: [],
    })
    vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue({})
    const startRemoval = vi.spyOn(removalApi, 'startSubtitleRemoval').mockResolvedValue({ task_id: 'cleanup-task' })
    const startOcr = vi.spyOn(videoOcrApi, 'startVideoOcr').mockResolvedValue({ task_id: 'ocr-task' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.change(await screen.findByPlaceholderText('Đường dẫn tệp'), { target: { value: 'D:/burned.mp4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nạp' }))
    const asset = (await screen.findByText('burned.mp4')).closest('.editor-asset') as HTMLElement
    fireEvent.click(within(asset).getByTitle('Đưa vào timeline'))
    fireEvent.click(screen.getByRole('button', { name: 'OCR & xóa chữ' }))
    const recognizeButton = await screen.findByRole('button', { name: 'Nhận dạng phụ đề' })
    await waitFor(() => expect(recognizeButton).toBeEnabled())
    fireEvent.click(recognizeButton)
    await waitFor(() => expect(startOcr).toHaveBeenCalledWith(expect.objectContaining({
      video_path: 'D:/burned.mp4', output_dir: 'D:/result', mode: 'fast',
      region: { x: 5, y: 68, width: 90, height: 27 },
    })))

    taskState.tasks = [{
      taskId: 'ocr-task', kind: 'editor-video-ocr', status: 'done', lines: [],
      canPause: false, canResume: false, canCancel: false, updatedAt: Date.now(),
      result: {
        project_dir: 'D:/result/burned-ocr', srt_path: 'D:/result/burned-ocr/captions.srt',
        manifest_path: 'D:/result/burned-ocr/ocr_manifest.json', source_video_path: 'D:/burned.mp4',
        cues: [{ index: 1, start_ms: 0, end_ms: 1_000, text: 'Xin chào OCR', confidence: 0.95, boxes: [] }],
        sampled_frames: 20, ocr_frames: 5, reused_frames: 15, cache_hit: false,
      },
    }]
    view.rerender(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'OCR 1' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('Xin chào OCR')).toBeInTheDocument()
    expect(within(document.querySelector('.editor-timeline-panel') as HTMLElement).queryByText('Xin chào OCR')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Xóa phụ đề' }))
    await waitFor(() => expect(startRemoval).toHaveBeenCalledWith(expect.objectContaining({
      video_path: 'D:/burned.mp4',
      masks: [expect.objectContaining({
        name: 'OCR 1', region: { x: 5, y: 68, width: 90, height: 27 }, start_seconds: 0, end_seconds: 1,
      })],
    })))
    fireEvent.click(screen.getByRole('button', { name: 'Đưa SRT đã duyệt vào timeline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Phụ đề & giọng nói' }))
    expect(screen.getByDisplayValue('Xin chào OCR')).toBeInTheDocument()
  })

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
      editable: true, identity_editable: true, deletable: true, compatibility: { studio: true, batch: true, editor: true },
    }])
    const startSpeech = vi.spyOn(editorApi, 'startEditorSpeech').mockResolvedValue({ job_id: 'editor-job-1', task_id: 'task-1' })
    const startCondensation = vi.spyOn(editorApi, 'startEditorCondensation').mockResolvedValue({ task_id: 'condense-1' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    fireEvent.change(await screen.findByLabelText('Giọng từ Thư viện'), { target: { value: 'son' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chuyển thành audio' }))

    expect(startSpeech).toHaveBeenCalledWith(expect.objectContaining({
      voice: expect.objectContaining({ profile_id: 'son-profile' }),
      cues: [expect.objectContaining({ text: 'Xin chào' })],
    }))

    vi.spyOn(editorApi, 'loadEditorMedia').mockResolvedValue({
      source_id: 'audio-1', url: '/api/editor/source/audio-1', name: 'voice.wav', path: 'D:/voice.wav',
      kind: 'audio', duration_seconds: 1.4, width: 0, height: 0, fps: 0, has_audio: true,
    })
    const request = startSpeech.mock.calls[0][0]
    const cue = request.cues[0]
    publishEvent({
      type: 'event',
      kind: 'editor_speech_item',
      payload: {
        job_id: request.job_id, task_id: 'task-1', item_id: cue.item_id,
        track_id: cue.track_id, cue_id: cue.cue_id, start_ms: cue.start_ms,
        status: 'done', wav_path: 'D:/voice.wav', error: null, warnings: [],
        cue_duration_ms: 1_000, audio_duration_ms: 1_400, overflow_ms: 400,
        fit_status: 'condense', suggested_speed: null,
        completed: 1, failed: 0, total: 1,
      },
    })

    await waitFor(() => expect(editorApi.loadEditorMedia).toHaveBeenCalledWith('D:/voice.wav', 'audio'))
    expect(await screen.findByText('voice.wav')).toBeInTheDocument()
    expect(screen.getByText('Audio tràn 0,40 giây')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Đề xuất rút gọn' }))
    expect(startCondensation).toHaveBeenCalledWith({
      project_id: '',
      track_id: cue.track_id,
      cue_id: cue.cue_id,
      text: 'Xin chào',
      language: 'vi',
      cue_duration_ms: 1_000,
      audio_duration_ms: 1_400,
    })

    taskState.tasks = [{
      taskId: 'condense-1',
      status: 'done',
      result: {
        track_id: cue.track_id,
        cue_id: cue.cue_id,
        original_text: 'Xin chào',
        proposed_text: 'Chào bạn',
        target_characters: 6,
        provider: 'deepseek',
        model: 'deepseek-chat',
      },
    }]
    view.rerender(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    expect(await screen.findByText('Chào bạn')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Xin chào')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Áp dụng đề xuất' }))
    expect(screen.getByDisplayValue('Chào bạn')).toBeInTheDocument()
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
      editable: true, identity_editable: false, deletable: false, compatibility: { studio: false, batch: false, editor: true },
    }])
    const startSpeech = vi.spyOn(editorApi, 'startEditorSpeech').mockResolvedValue({ job_id: 'editor-job-1', task_id: 'task-1' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Thêm SRT' }))
    expect(await screen.findByText('captions.srt')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('Đưa vào timeline'))
    const option = await screen.findByRole('option', { name: 'Microsoft David Desktop · en-US' })
    expect(option).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText('Giọng từ Thư viện'), { target: { value: 'system:sapi:Microsoft David Desktop' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chuyển thành audio' }))

    expect(startSpeech).toHaveBeenCalledWith(expect.objectContaining({
      engine_id: 'sapi',
      device: 'cpu',
      voice_revision: 1,
      engine_options: { voice_name: 'Microsoft David Desktop' },
      voice: expect.objectContaining({ source: 'auto' }),
      cues: [expect.objectContaining({ text: 'Hello', end_ms: 1_000 })],
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

  it('plans multiple removal masks and replaces then restores the selected clip explicitly', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({
      editor_output_dir: 'D:/result',
      subtitle_removal_mode: 'blur',
      subtitle_region_x: 5,
      subtitle_region_y: 75,
      subtitle_region_width: 90,
      subtitle_region_height: 20,
    })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue({})
    vi.spyOn(voiceLibraryApi, 'fetchLibraryVoices').mockResolvedValue([])
    vi.spyOn(removalApi, 'fetchRemovalMeta').mockResolvedValue({
      modes: [{ code: 'blur', label: 'Làm mờ' }],
      region_presets: [
        { code: 'bottom', name: 'Phụ đề dưới', region: { x: 5, y: 75, width: 90, height: 20 } },
        { code: 'top', name: 'Phụ đề trên', region: { x: 5, y: 5, width: 90, height: 20 } },
      ],
    })
    vi.spyOn(editorApi, 'loadEditorMedia').mockImplementation(async (path) => path.includes('clean') ? {
      source_id: 'video-clean', url: '/api/editor/source/video-clean', name: 'clip-clean.mp4', path,
      kind: 'video', duration_seconds: 30, width: 1920, height: 1080, fps: 30, has_audio: true,
    } : {
      source_id: 'video-1', url: '/api/editor/source/video-1', name: 'clip.mp4', path,
      kind: 'video', duration_seconds: 30, width: 1920, height: 1080, fps: 30, has_audio: true,
    })
    const startRemoval = vi.spyOn(removalApi, 'startSubtitleRemoval').mockResolvedValue({ task_id: 'removal-task' })
    vi.spyOn(removalApi, 'fetchRemovalPreview').mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn()
      .mockReturnValueOnce('blob:before')
      .mockReturnValueOnce('blob:after') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'OCR & xóa chữ' }))
    expect(screen.getByText('Chọn một clip video trên timeline')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Phụ đề & giọng nói' }))

    fireEvent.change(await screen.findByPlaceholderText('Đường dẫn tệp'), { target: { value: 'D:/clip.mp4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nạp' }))
    const sourceAsset = (await screen.findByText('clip.mp4')).closest('.editor-asset') as HTMLElement
    fireEvent.click(within(sourceAsset).getByTitle('Đưa vào timeline'))
    fireEvent.click(screen.getByRole('button', { name: 'OCR & xóa chữ' }))

    await screen.findByRole('option', { name: 'Làm mờ' })
    await waitFor(() => expect(screen.getByLabelText('Chế độ xóa')).toHaveValue('blur'))
    fireEvent.click(screen.getByRole('button', { name: 'Thêm vùng' }))
    expect(screen.getByText('Có các vùng xóa chồng nhau trong cùng thời gian; hiệu ứng xử lý có thể bị cộng dồn.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Mẫu vùng'), { target: { value: 'top' } })
    fireEvent.click(screen.getByLabelText('Toàn bộ video'))
    fireEvent.change(screen.getByLabelText('Bắt đầu vùng'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Kết thúc vùng'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Xóa phụ đề' }))
    await waitFor(() => expect(startRemoval).toHaveBeenCalledWith(expect.objectContaining({
      video_path: 'D:/clip.mp4',
      output_dir: 'D:/result',
      mode: 'blur',
      masks: expect.arrayContaining([
        expect.objectContaining({ name: 'Vùng 1' }),
        expect.objectContaining({ name: 'Vùng 2', start_seconds: 3, end_seconds: 12 }),
      ]),
    })))

    taskState.tasks = [{
      taskId: 'removal-task',
      status: 'done',
      result: {
        project_dir: 'D:/result/clip-clean',
        video_path: 'D:/result/clip-clean/clip-clean.mp4',
        video_url: '/api/removal/result/video-clean',
        manifest_path: 'D:/result/clip-clean/manifest.json',
        mode: 'blur',
        source_video_path: 'D:/clip.mp4',
        masks: [],
        warnings: ['Làm mờ có thể làm mất chi tiết nền.'],
      },
    }]
    view.rerender(<QueryClientProvider client={client}><EditorPage /></QueryClientProvider>)

    expect(await screen.findByText('clip-clean.mp4')).toBeInTheDocument()
    expect(screen.getByText('Trước xử lý')).toBeInTheDocument()
    expect(screen.getByText('Sau xử lý')).toBeInTheDocument()
    expect(screen.getByText('Làm mờ có thể làm mất chi tiết nền.')).toBeInTheDocument()
    expect(document.querySelector('.editor-video-stage video')).toHaveAttribute('src', '/api/editor/source/video-1')

    fireEvent.click(screen.getByRole('button', { name: 'Thay clip đã chọn' }))
    expect(document.querySelector('.editor-video-stage video')).toHaveAttribute('src', '/api/editor/source/video-clean')
    fireEvent.click(screen.getByRole('button', { name: 'Khôi phục clip gốc' }))
    expect(document.querySelector('.editor-video-stage video')).toHaveAttribute('src', '/api/editor/source/video-1')
  })
})

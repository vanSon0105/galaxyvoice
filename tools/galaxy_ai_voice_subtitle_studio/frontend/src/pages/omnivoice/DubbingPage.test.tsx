import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSettings, fetchSettingsMeta } from '../../api/settings'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import { fetchOmniVoiceStatus } from '../../api/omnivoice'
import {
  fetchDubbingPlan,
  fetchDubbingProject,
  fetchDubbingProjects,
  saveDubbingProject,
  startDubbingTranslation,
  type DubbingProject,
  type DubbingQualityReport,
  type DubbingSegment,
} from '../../api/workspaces'
import { DubbingPage } from './DubbingPage'

vi.mock('../../api/settings', () => ({
  fetchSettings: vi.fn(),
  fetchSettingsMeta: vi.fn(),
  saveTranslationApiKey: vi.fn(),
}))
vi.mock('../../api/voiceLibrary', () => ({ fetchLibraryVoices: vi.fn() }))
vi.mock('../../api/omnivoice', () => ({ fetchOmniVoiceStatus: vi.fn() }))
vi.mock('../../api/transcripts', () => ({ fetchTranscriptHandoff: vi.fn() }))
vi.mock('../../lib/dialogs', () => ({
  pickAudioFile: vi.fn(), pickFolder: vi.fn(), pickVideoFile: vi.fn(),
}))
vi.mock('../../ws/useTasks', () => ({ useTasks: () => ({ tasks: [], cancelTask: vi.fn() }) }))
vi.mock('../../api/workspaces', async () => {
  const actual = await vi.importActual<typeof import('../../api/workspaces')>('../../api/workspaces')
  return {
    ...actual,
    fetchDubbingPlan: vi.fn(),
    fetchDubbingProjects: vi.fn(),
    fetchDubbingProject: vi.fn(),
    fetchResumeJobs: vi.fn().mockResolvedValue([]),
    saveDubbingProject: vi.fn(),
    startDubbingTranslation: vi.fn(),
  }
})

const quality: DubbingQualityReport = {
  report_id: 'qc-1', score: 95, segment_count: 1, error_count: 0, warning_count: 1,
  issues: [], measurements: [],
}

function segment(index: number): DubbingSegment {
  return {
    segment_id: `seg-${index}`,
    start_ms: index * 1_200,
    end_ms: index * 1_200 + 1_000,
    source_text: `Source sentence ${index}`,
    text: `Câu đã dịch số ${index}`,
    speaker_id: index % 2 ? 'Lan' : 'Minh',
    profile_id: '', speed: 1, volume: 1,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}><DubbingPage /></QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('native Dubbing workspace', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue({ output_dir: 'D:/out', omnivoice_language: 'vi' })
    vi.mocked(fetchSettingsMeta).mockResolvedValue({
      tts_engines: [], default_tts_engine: '', whisper_models: [],
      translation_providers: [{ code: 'deepseek', label: 'DeepSeek', default_model: 'deepseek-chat', default_base_url: 'https://api.deepseek.com', models: ['deepseek-chat'], api_key_configured: true, api_key_environment_name: 'GALAXY_DEEPSEEK_API_KEY' }],
      default_translation_provider: 'deepseek',
      source_languages: [{ code: 'auto', label: 'Tự động' }],
      target_languages: [{ code: 'vi', label: 'Tiếng Việt' }],
      processing_devices: [], audio_methods: [], audio_devices: [], audio_formats: [],
      removal_modes: [], editor_resolutions: [], editor_fps: [], editor_encoders: [],
      editor_audio_modes: [], omnivoice_devices: [],
    })
    vi.mocked(fetchOmniVoiceStatus).mockResolvedValue({
      installed: true, message: 'Sẵn sàng', python_path: '', languages: ['vi'],
      devices: [{ code: 'auto', label: 'Tự động' }], expression_tags: [],
      design_options: { gender: [], age: [], pitch: [], style: [], accent: [], dialect: [] },
    })
    vi.mocked(fetchLibraryVoices).mockResolvedValue([])
    vi.mocked(fetchDubbingProjects).mockResolvedValue([])
  })

  it('plans from source and externally translated SRT, then exposes split and merge editing', async () => {
    vi.mocked(fetchDubbingPlan).mockResolvedValue({ segments: [segment(0)], issues: [], quality })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText(/Lan: Hello/), { target: { value: '1\n00:00:00,000 --> 00:00:01,000\nHello' } })
    fireEvent.change(screen.getByPlaceholderText(/Dán SRT đã dịch/), { target: { value: '1\n00:00:00,000 --> 00:00:01,000\nXin chào' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cập nhật kế hoạch' }))

    await waitFor(() => expect(fetchDubbingPlan).toHaveBeenCalled())
    expect(vi.mocked(fetchDubbingPlan).mock.calls[0]).toEqual([
      '1\n00:00:00,000 --> 00:00:01,000\nHello',
      '1\n00:00:00,000 --> 00:00:01,000\nXin chào',
    ])
    expect(await screen.findByRole('button', { name: 'Tách' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Tách' }))
    expect(screen.getByText('Đoạn lồng tiếng (2)')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Gộp trên' })[1]).toBeEnabled()
  })

  it('virtualizes a long subtitle plan instead of mounting every segment row', async () => {
    const segments = Array.from({ length: 500 }, (_, index) => segment(index))
    vi.mocked(fetchDubbingPlan).mockResolvedValue({ segments, issues: [], quality: { ...quality, segment_count: segments.length } })
    const view = renderPage()
    fireEvent.change(screen.getByPlaceholderText(/Lan: Hello/), { target: { value: 'valid source' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cập nhật kế hoạch' }))

    expect(await screen.findByText('Đoạn lồng tiếng (500)')).toBeInTheDocument()
    expect(view.container.querySelectorAll('.dubbing-segment-row').length).toBeLessThan(20)
  })

  it('saves an ingest checkpoint before starting AI translation', async () => {
    vi.mocked(saveDubbingProject).mockResolvedValue({
      project_id: 'checkpoint-1', galaxy_project_id: '', name: 'dubbing', stage: 'ingest', revision: 1,
      source_srt: 'source', translated_srt: '', source_video: '', source_audio: '', language: 'vi',
      segment_count: 0, segments: [], options: {}, quality: {}, last_result: {},
      created_at: '2026-08-29T00:00:00Z', updated_at: '2026-08-29T00:00:00Z',
    })
    vi.mocked(startDubbingTranslation).mockResolvedValue({ task_id: 'translate-1' })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText(/Lan: Hello/), { target: { value: 'source' } })
    fireEvent.click(screen.getByRole('button', { name: 'Dịch bằng AI' }))

    await waitFor(() => expect(startDubbingTranslation).toHaveBeenCalled())
    expect(vi.mocked(saveDubbingProject).mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(startDubbingTranslation).mock.invocationCallOrder[0])
    expect(vi.mocked(saveDubbingProject).mock.calls[0][0]).toMatchObject({
      stage: 'ingest', source_srt: 'source', segments: [],
    })
    expect(vi.mocked(startDubbingTranslation).mock.calls[0][0]).toMatchObject({
      workflow_id: 'checkpoint-1', source_srt: 'source',
    })
  })

  it('restores non-secret render and translation settings from a saved checkpoint', async () => {
    vi.mocked(fetchDubbingProjects).mockResolvedValue([{
      project_id: 'saved-1', galaxy_project_id: 'project-1', name: 'Bản đã lưu', stage: 'qc', revision: 3,
      segment_count: 1, language: 'vi', updated_at: '2026-08-27T00:00:00Z',
    }])
    vi.mocked(fetchDubbingProject).mockResolvedValue({
      project_id: 'saved-1', galaxy_project_id: 'project-1', name: 'Bản đã lưu', stage: 'qc', revision: 3,
      segment_count: 1, language: 'vi', updated_at: '2026-08-27T00:00:00Z',
      source_srt: 'source', translated_srt: 'translated', source_video: '', source_audio: '',
      segments: [segment(0)], created_at: '2026-08-27T00:00:00Z', quality, last_result: {},
      options: {
        source_language: 'auto', translation_provider: 'deepseek',
        translation_model: 'deepseek-chat', output_dir: 'D:/saved', device: 'auto',
        mix_mode: 'duck', source_volume: 0.4, dub_volume: 1.2,
        fit_min: 0.75, fit_max: 1.35, fit_tolerance: 160,
        export_mp3: false, export_stems: false,
      },
    } satisfies DubbingProject)
    renderPage()
    await screen.findByRole('option', { name: /Bản đã lưu/ })
    const projectPicker = screen.getAllByRole('combobox')[0]
    fireEvent.change(projectPicker, { target: { value: 'saved-1' } })

    await waitFor(() => expect(fetchDubbingProject).toHaveBeenCalledWith('saved-1'))
    expect(await screen.findByDisplayValue('Hạ nền nguồn khi có voice')).toBeInTheDocument()
    expect(screen.getByDisplayValue('D:/saved')).toBeInTheDocument()
    expect(screen.getByDisplayValue('160')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('••••••••')).toHaveValue('')
  })
})

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSettings } from '../../api/settings'
import { fetchOmniVoiceStatus, fetchProfiles } from '../../api/omnivoice'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import { fetchStudioTakes, setStudioTakePrimary } from '../../api/studio'
import type { StudioTake } from '../../api/studio'
import { VoiceProjectContext } from './VoiceProjectContext'
import { StudioPage } from './StudioPage'

vi.mock('../../api/settings', () => ({ fetchSettings: vi.fn() }))
vi.mock('../../api/omnivoice', () => ({
  fetchOmniVoiceStatus: vi.fn(),
  fetchProfiles: vi.fn(),
  installOmniVoiceRuntime: vi.fn(),
}))
vi.mock('../../api/voiceLibrary', () => ({ fetchLibraryVoices: vi.fn(), libraryVoiceRequest: vi.fn() }))
vi.mock('../../api/studio', async () => {
  const actual = await vi.importActual<typeof import('../../api/studio')>('../../api/studio')
  return {
    ...actual,
    fetchStudioTakes: vi.fn(),
    setStudioTakePrimary: vi.fn(),
    setStudioTakeStarred: vi.fn(),
    deleteStudioTake: vi.fn(),
    rerunStudioTake: vi.fn(),
    startStudioGeneration: vi.fn(),
  }
})

const takes: StudioTake[] = [
  {
    take_id: 'take-a', project_id: 'project-1', title: 'Giọng A', engine_id: 'omnivoice',
    text: 'Xin chào', language: 'vi', voice_source: 'auto', voice_profile_id: '', speed: 1,
    formats: ['wav'], project_dir: 'D:/out/a', wav_path: 'D:/out/a/voice.wav', mp3_path: null,
    manifest_path: 'D:/out/a/manifest.json', profile_id: '', warnings: [], generation_run_id: 'run-a', starred: false,
    primary: false, rerun_of: '', created_at: '2026-08-26T10:00:00Z',
    audio_url: '/api/studio/takes/take-a/audio',
  },
  {
    take_id: 'take-b', project_id: 'project-1', title: 'Giọng B', engine_id: 'omnivoice',
    text: 'Xin chào', language: 'vi', voice_source: 'profile', voice_profile_id: 'son', speed: 1.1,
    formats: ['wav', 'mp3'], project_dir: 'D:/out/b', wav_path: 'D:/out/b/voice.wav',
    mp3_path: 'D:/out/b/voice.mp3', manifest_path: 'D:/out/b/manifest.json', profile_id: 'son',
    warnings: [], generation_run_id: 'run-b', starred: true, primary: false, rerun_of: '', created_at: '2026-08-26T11:00:00Z',
    audio_url: '/api/studio/takes/take-b/audio',
  },
]

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <VoiceProjectContext.Provider value={{ project: null, projectId: 'project-1' }}>
          <StudioPage />
        </VoiceProjectContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('native Studio', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue({ output_dir: 'D:/out' })
    vi.mocked(fetchOmniVoiceStatus).mockResolvedValue({
      installed: true, message: 'Sẵn sàng', python_path: '', languages: ['vi'],
      devices: [{ code: 'auto', label: 'Tự động' }], expression_tags: [],
      design_options: { gender: [], age: [], pitch: [], style: [], accent: [], dialect: [] },
    })
    vi.mocked(fetchProfiles).mockResolvedValue([])
    vi.mocked(fetchLibraryVoices).mockResolvedValue([])
    vi.mocked(fetchStudioTakes).mockResolvedValue(takes)
    vi.mocked(setStudioTakePrimary).mockResolvedValue({ ...takes[1], primary: true })
  })

  it('compares two saved takes and promotes one as the project primary', async () => {
    renderPage()

    expect(await screen.findByText('Giọng A')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('So sánh Giọng A'))
    fireEvent.click(screen.getByLabelText('So sánh Giọng B'))
    expect(screen.getByRole('heading', { name: 'So sánh A/B' })).toBeInTheDocument()
    expect(screen.getAllByText(/Giọng [AB]/)).toHaveLength(4)

    fireEvent.click(screen.getByRole('button', { name: 'Chọn Giọng B làm bản chính' }))
    await waitFor(() => expect(setStudioTakePrimary).toHaveBeenCalledWith('take-b', true))
  })
})

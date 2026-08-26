import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  editTranscriptCue,
  createTranscriptHandoff,
  fetchTranscriptProject,
  fetchTranscriptProjects,
  importTextTranscript,
  saveTranscriptDocument,
} from '../../api/transcripts'
import type { TranscriptProject } from '../../api/transcripts'
import { VoiceProjectContext } from './VoiceProjectContext'
import { TranscriptsPage } from './TranscriptsPage'

vi.mock('../../api/transcripts', async () => {
  const actual = await vi.importActual<typeof import('../../api/transcripts')>(
    '../../api/transcripts',
  )
  return {
    ...actual,
    fetchTranscriptProjects: vi.fn(),
    fetchTranscriptProject: vi.fn(),
    importTextTranscript: vi.fn(),
    editTranscriptCue: vi.fn(),
    saveTranscriptDocument: vi.fn(),
    createTranscriptHandoff: vi.fn(),
    deleteTranscriptCue: vi.fn(),
    deleteTranscriptProject: vi.fn(),
  }
})
vi.mock('../../ws/useTasks', () => ({ useTasks: () => ({ tasks: [], cancelTask: vi.fn() }) }))
vi.mock('../../lib/dialogs', () => ({ pickMediaFile: vi.fn() }))

const mockProject: TranscriptProject = {
  schema_version: 1,
  transcript_id: 't-1',
  project_id: 'project-1',
  name: 'Giới thiệu sản phẩm',
  status: 'ready',
  revision: 1,
  source_path: 'intro.mp4',
  source_kind: 'video',
  requested_language: 'vi',
  detected_language: 'vi',
  model_id: 'base',
  requested_device: 'auto',
  resolved_device: 'cpu',
  diarization_requested: false,
  diarization_state: 'disabled',
  created_at: '2026-08-26T00:00:00Z',
  updated_at: '2026-08-26T00:00:00Z',
  duration_ms: 5000,
  speakers: [{ speaker_id: 'speaker-1', label: 'Người nói 1', color: '#d08ca1' }],
  cue_count: 2,
  warnings: [],
  provenance: {},
  handoffs: [],
  cues: [
    {
      cue_id: 'cue-1',
      position: 0,
      start_ms: 1000,
      end_ms: 3000,
      text: 'Xin chào các bạn',
      speaker_id: 'speaker-1',
      confidence: 0.95,
      words: [],
    },
    {
      cue_id: 'cue-2',
      position: 1,
      start_ms: 3500,
      end_ms: 5000,
      text: 'Hôm nay chúng ta cùng test',
      speaker_id: 'speaker-1',
      confidence: 0.98,
      words: [],
    },
  ],
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <VoiceProjectContext.Provider value={{ project: null, projectId: 'project-1' }}>
          <TranscriptsPage />
        </VoiceProjectContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('native Transcripts Page', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(fetchTranscriptProjects).mockResolvedValue([mockProject])
    vi.mocked(fetchTranscriptProject).mockResolvedValue(mockProject)
    vi.mocked(editTranscriptCue).mockResolvedValue({
      ...mockProject,
      revision: 2,
    })
    vi.mocked(saveTranscriptDocument).mockResolvedValue({ ...mockProject, revision: 2 })
    vi.mocked(createTranscriptHandoff).mockResolvedValue({
      schema_version: 1,
      kind: 'transcript_handoff',
      target: 'dubbing',
      transcript_id: mockProject.transcript_id,
      project_id: mockProject.project_id,
      source_revision: 1,
      source_path: mockProject.source_path,
      language: 'vi',
      segments: [],
    })
  })

  it('renders transcript project list and editor cues', async () => {
    renderPage()
    expect(await screen.findByText('Giới thiệu sản phẩm')).toBeInTheDocument()
    expect(await screen.findByText('Xin chào các bạn')).toBeInTheDocument()
    expect(screen.getByText('Hôm nay chúng ta cùng test')).toBeInTheDocument()
  })

  it('opens text import modal and allows creating transcript from SRT text', async () => {
    vi.mocked(importTextTranscript).mockResolvedValue(mockProject)
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Nhập SRT / văn bản' }))
    expect(screen.getByText('Nhập phụ đề hoặc văn bản')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Dán nội dung SRT, VTT hoặc text tại đây...'), {
      target: { value: '1\n00:00:01,000 --> 00:00:03,000\nHello' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Lưu transcript' }))

    await waitFor(() =>
      expect(importTextTranscript).toHaveBeenCalledWith(
        expect.objectContaining({
          project_id: 'project-1',
          content: '1\n00:00:01,000 --> 00:00:03,000\nHello',
        }),
      ),
    )
  })

  it('virtualizes a transcript with 1000 cues', async () => {
    const cues = Array.from({ length: 1000 }, (_, index) => ({
      ...mockProject.cues![0],
      cue_id: `cue-${index}`,
      position: index,
      start_ms: index * 3000,
      end_ms: index * 3000 + 2500,
      text: `Cue ${index}`,
    }))
    const longProject = { ...mockProject, cue_count: cues.length, cues, duration_ms: 3_000_000 }
    vi.mocked(fetchTranscriptProjects).mockResolvedValue([longProject])
    vi.mocked(fetchTranscriptProject).mockResolvedValue(longProject)
    renderPage()

    expect(await screen.findByDisplayValue('Cue 0')).toBeInTheDocument()
    expect(screen.getAllByRole('textbox').length).toBeLessThan(50)
    expect(screen.queryByDisplayValue('Cue 999')).not.toBeInTheDocument()
  })

  it('saves local cue edits as one revision', async () => {
    renderPage()
    const cue = await screen.findByDisplayValue('Xin chào các bạn')
    fireEvent.change(cue, { target: { value: 'Xin chào Galaxy' } })
    fireEvent.blur(cue)
    expect(screen.getByRole('button', { name: 'SRT' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))

    await waitFor(() => expect(saveTranscriptDocument).toHaveBeenCalledWith(
      't-1',
      expect.objectContaining({
        expected_revision: 1,
        cues: expect.arrayContaining([expect.objectContaining({ text: 'Xin chào Galaxy' })]),
      }),
    ))
  })
})

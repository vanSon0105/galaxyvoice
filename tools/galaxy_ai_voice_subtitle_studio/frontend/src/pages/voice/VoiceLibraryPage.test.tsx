import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchLibraryVoices, updateLibraryVoice } from '../../api/voiceLibrary'
import type { LibraryVoice } from '../../api/voiceLibrary'
import { VoiceProjectContext } from './VoiceProjectContext'
import { VoiceLibraryPage } from './VoiceLibraryPage'

vi.mock('../../api/voiceLibrary', async () => {
  const actual = await vi.importActual<typeof import('../../api/voiceLibrary')>('../../api/voiceLibrary')
  return { ...actual, fetchLibraryVoices: vi.fn(), updateLibraryVoice: vi.fn() }
})
vi.mock('../../lib/dialogs', () => ({ pickAudioFile: vi.fn(), pickFolder: vi.fn(), pickVoiceBundleFile: vi.fn() }))

const voice: LibraryVoice = {
  voice_id: 'omnivoice:son', revision: 2, name: 'Sơn', source: 'cloned', language: 'vi', engine_id: 'omnivoice',
  selection: { source: 'profile', profile_id: 'son', reference_audio: '', reference_text: 'Xin chào', instruction: '', system_engine: '', system_voice: '' },
  tags: ['review'], notes: 'Giọng chính', favorite: false,
  consent: { confirmed: true, basis: 'owner', statement: 'Đã xác nhận', recorded_at: '2026-01-01', provenance: '' },
  stable_sample: true, created_at: '2026-01-01', updated_at: '2026-01-02', capabilities: ['omnivoice.profile'],
  preview_available: false, preview_url: '/preview', usage_count: 1, editable: true, identity_editable: true, deletable: true,
  compatibility: { studio: true, batch: true, longform: true, dubbing: true },
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<MemoryRouter><QueryClientProvider client={queryClient}><VoiceProjectContext.Provider value={{ project: null, projectId: 'project-1' }}><VoiceLibraryPage /></VoiceProjectContext.Provider></QueryClientProvider></MemoryRouter>)
}

describe('native Voice Library', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.mocked(fetchLibraryVoices).mockResolvedValue([voice])
    vi.mocked(updateLibraryVoice).mockImplementation(async (_id, changes) => ({
      ...voice,
      ...changes,
      consent: changes.consent ? { ...voice.consent, ...changes.consent } : voice.consent,
    }))
  })

  it('shows unified profile metadata and persists favorites', async () => {
    renderPage()
    expect((await screen.findAllByText('Sơn')).length).toBeGreaterThan(0)
    expect(screen.getByText('Đã xác nhận quyền sử dụng')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Yêu thích Sơn' }))
    await waitFor(() => expect(updateLibraryVoice).toHaveBeenCalledWith('omnivoice:son', { favorite: true }))
  })

  it('opens the guided import form with consent', async () => {
    renderPage()
    await screen.findAllByText('Sơn')
    fireEvent.click(screen.getByRole('button', { name: 'Nhập audio' }))
    expect(screen.getByText('Nhập audio tham chiếu')).toBeInTheDocument()
    expect(screen.getByText('Tôi có quyền sử dụng giọng nói này')).toBeInTheDocument()
  })
})

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchBatchRuns, parseBatchSource, startBatchRun } from '../../api/batch'
import { fetchOmniVoiceStatus, fetchProfiles } from '../../api/omnivoice'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import { fetchSettings } from '../../api/settings'
import { VoiceProjectContext } from './VoiceProjectContext'
import { BatchPage } from './BatchPage'


vi.mock('../../api/settings', () => ({ fetchSettings: vi.fn() }))
vi.mock('../../api/omnivoice', () => ({ fetchOmniVoiceStatus: vi.fn(), fetchProfiles: vi.fn() }))
vi.mock('../../api/voiceLibrary', () => ({ fetchLibraryVoices: vi.fn(), libraryVoiceRequest: vi.fn() }))
vi.mock('../../ws/useTasks', () => ({ useTasks: () => ({ tasks: [], cancelTask: vi.fn() }) }))
vi.mock('../../api/batch', async () => {
  const actual = await vi.importActual<typeof import('../../api/batch')>('../../api/batch')
  return {
    ...actual,
    fetchBatchRuns: vi.fn(),
    fetchBatchRun: vi.fn(),
    parseBatchSource: vi.fn(),
    startBatchRun: vi.fn(),
    retryBatchRun: vi.fn(),
    resumeBatchRun: vi.fn(),
  }
})

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <VoiceProjectContext.Provider value={{ project: null, projectId: 'project-1' }}>
        <BatchPage />
      </VoiceProjectContext.Provider>
    </QueryClientProvider>,
  )
}

describe('native Batch', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue({ output_dir: 'D:/out' })
    vi.mocked(fetchOmniVoiceStatus).mockResolvedValue({
      installed: true, message: 'Sẵn sàng', python_path: '', languages: ['vi', 'en'],
      devices: [{ code: 'auto', label: 'Tự động' }], expression_tags: [],
      design_options: { gender: [], age: [], pitch: [], style: [], accent: [], dialect: [] },
    })
    vi.mocked(fetchProfiles).mockResolvedValue([])
    vi.mocked(fetchLibraryVoices).mockResolvedValue([])
    vi.mocked(fetchBatchRuns).mockResolvedValue([])
    vi.mocked(parseBatchSource).mockResolvedValue([
      { item_id: 'one', text: 'Một', language: 'vi', speed: null, duration: null, voice_source: '', profile_id: '', instruction: '', formats: [] },
      { item_id: 'two', text: 'Two', language: 'en', speed: 1.1, duration: null, voice_source: '', profile_id: '', instruction: '', formats: [] },
    ])
    vi.mocked(startBatchRun).mockResolvedValue({ batch_id: 'batch-1', task_id: 'task-1' })
  })

  it('parses input into editable items and starts a project-scoped run', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Nguồn Batch'), { target: { value: 'Một\nTwo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Phân tích' }))
    expect(await screen.findByDisplayValue('one')).toBeInTheDocument()
    expect(screen.getByDisplayValue('two')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Chạy Batch' }))
    await waitFor(() => expect(startBatchRun).toHaveBeenCalled())
    expect(vi.mocked(startBatchRun).mock.calls[0][0]).toMatchObject({
      project_id: 'project-1',
      output_dir: 'D:/out',
      items: [{ item_id: 'one' }, { item_id: 'two', speed: 1.1 }],
    })
  })
})

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSettings } from '../../api/settings'
import { fetchOmniVoiceStatus } from '../../api/omnivoice'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import {
  createDocument,
  fetchHistory,
  fetchLongformProjects,
  type DocumentItem,
  type LongformDocument,
} from '../../api/workspaces'
import { WorkspacesPage } from './WorkspacesPage'

vi.mock('../../api/settings', () => ({ fetchSettings: vi.fn() }))
vi.mock('../../api/omnivoice', () => ({ fetchOmniVoiceStatus: vi.fn() }))
vi.mock('../../api/voiceLibrary', () => ({ fetchLibraryVoices: vi.fn() }))
vi.mock('../../api/transcripts', () => ({ fetchTranscriptHandoff: vi.fn() }))
vi.mock('../../lib/dialogs', () => ({ pickBookFile: vi.fn(), pickFolder: vi.fn() }))
vi.mock('../../components/TaskButton', () => ({
  TaskButton: ({ label }: { label: string }) => <button>{label}</button>,
}))
vi.mock('../../api/workspaces', async () => {
  const actual = await vi.importActual<typeof import('../../api/workspaces')>('../../api/workspaces')
  return {
    ...actual,
    createDocument: vi.fn(),
    fetchHistory: vi.fn(),
    fetchLongformProjects: vi.fn(),
    fetchResumeJobs: vi.fn().mockResolvedValue([]),
  }
})

function item(index: number): DocumentItem {
  return {
    item_id: `line-${index}`,
    chapter: 'Chương 1',
    speaker: 'Người kể',
    text: `Nội dung dòng ${index}`,
    profile_id: '',
    speed: 1,
    volume: 1,
    pause_after_ms: 0,
    preview_path: '',
    spoken_text: '',
    emotion: '',
    emphasis: false,
    spell: false,
  }
}

function documentWithRows(count: number): LongformDocument {
  return {
    doc_id: 'doc-1',
    kind: 'stories',
    document: {
      chapters: ['Chương 1'],
      language: 'vi',
      items: Array.from({ length: count }, (_, index) => item(index)),
      pronunciation_rules: [],
    },
    script: 'Người kể: Nội dung',
    voice_names: ['Người kể'],
    issues: [],
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}><WorkspacesPage /></QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('longform stories and audiobook workspace', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue({ output_dir: 'D:/out', omnivoice_language: 'vi' })
    vi.mocked(fetchOmniVoiceStatus).mockResolvedValue({
      installed: true,
      message: 'Sẵn sàng',
      python_path: '',
      languages: ['vi', 'en'],
      devices: [{ code: 'auto', label: 'Tự động' }],
      expression_tags: [],
      design_options: { gender: [], age: [], pitch: [], style: [], accent: [], dialect: [] },
    })
    vi.mocked(fetchLibraryVoices).mockResolvedValue([])
    vi.mocked(fetchHistory).mockResolvedValue([])
    vi.mocked(fetchLongformProjects).mockResolvedValue([])
  })

  it('virtualizes a long book plan and exposes pronunciation, expression, preview, and mastering controls', async () => {
    vi.mocked(createDocument).mockResolvedValue(documentWithRows(600))
    const view = renderPage()
    fireEvent.change(screen.getByPlaceholderText(/Người kể:/), { target: { value: 'Người kể: Nội dung' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tạo kế hoạch' }))

    expect(await screen.findByText('Kế hoạch (600 đoạn)')).toBeInTheDocument()
    await waitFor(() => expect(createDocument).toHaveBeenCalledWith(
      'stories',
      'Người kể: Nội dung',
      undefined,
      'vi',
    ))
    expect(view.container.querySelectorAll('.longform-plan-table tbody tr').length).toBeLessThan(20)
    expect(screen.getByRole('button', { name: 'Thêm quy tắc' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Nghe thử' }).length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Mastering âm lượng')).toBeChecked()
    expect(screen.getByDisplayValue('-16')).toBeInTheDocument()
  })
})

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchProjects, saveProject } from '../../api/workspaces'
import type { WorkspaceProject } from '../../api/workspaces'
import { VoiceWorkspace } from './VoiceWorkspace'

vi.mock('../../api/workspaces', () => ({
  fetchProjects: vi.fn(),
  saveProject: vi.fn(),
}))

const project: WorkspaceProject = {
  project_id: 'project-1',
  workspace: 'studio',
  name: 'Kênh review',
  payload: {},
  created_at: '2026-08-26T01:00:00Z',
  updated_at: '2026-08-26T02:00:00Z',
}

function renderWorkspace(path = '/voice') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/voice" element={<VoiceWorkspace />}>
            <Route index element={<div>Studio body</div>} />
            <Route path="batch" element={<div>Batch body</div>} />
            <Route path="reference" element={<div>Reference body</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('VoiceWorkspace', () => {
  afterEach(cleanup)

  beforeEach(() => {
    window.localStorage.clear()
    vi.mocked(fetchProjects).mockResolvedValue([project])
    vi.mocked(saveProject).mockReset()
  })

  it('shows the six stable surfaces and selects the newest local project', async () => {
    renderWorkspace()

    expect(screen.getByRole('navigation', { name: 'Khu vực Voice' })).toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(6)
    expect(await screen.findByRole('option', { name: 'Kênh review' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByLabelText('Dự án đang mở')).toHaveValue('project-1')
      expect(window.localStorage.getItem('galaxy.voice.activeProject')).toBe('project-1')
    })
  })

  it('creates a project in the active Voice surface', async () => {
    const created = { ...project, project_id: 'project-2', name: 'Sách mới' }
    vi.mocked(saveProject).mockResolvedValue(created)
    renderWorkspace('/voice/batch')

    fireEvent.click(screen.getByRole('button', { name: 'Tạo dự án' }))
    fireEvent.change(screen.getByLabelText('Tên dự án mới'), { target: { value: 'Sách mới' } })
    fireEvent.click(screen.getByRole('button', { name: /^Tạo$/ }))

    await waitFor(() => {
      expect(saveProject).toHaveBeenCalledWith({
        workspace: 'batch',
        name: 'Sách mới',
        payload: { native_voice_workspace: true },
      })
    })
  })

  it('keeps VoiceStudio behind the explicit comparison action', async () => {
    renderWorkspace()
    fireEvent.click(screen.getByRole('button', { name: 'Bản đối chiếu' }))
    expect(await screen.findByText('Reference body')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'VoiceStudio đối chiếu' })).toBeInTheDocument()
  })
})

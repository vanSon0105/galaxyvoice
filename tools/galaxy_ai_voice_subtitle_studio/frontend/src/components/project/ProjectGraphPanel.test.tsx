import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ProjectGraphPanel } from './ProjectGraphPanel'
import * as api from '../../api/projectGraph'
import type { ProjectGraph } from '../../api/projectGraph'

vi.mock('../../api/projectGraph', () => ({
  fetchProjectGraph: vi.fn(),
  fetchProjectWorkspaces: vi.fn(),
  openProjectHandoff: vi.fn(),
  returnProjectHandoff: vi.fn(),
  upsertProjectNode: vi.fn(),
  createProjectHandoff: vi.fn(),
}))

const graph = {
  project_id: 'project-1',
  updated_at: '2026-08-28T00:00:00Z',
  nodes: [{
    node_id: 'transcripts:transcript-1',
    project_id: 'project-1',
    workspace: 'transcripts',
    owner_id: 'transcript-1',
    label: 'Phỏng vấn',
    route: '/voice/transcripts',
    revision: 2,
    assets: [{ asset_id: 'doc-1', role: 'transcript_document', ownership: 'managed', path_hint: '', fingerprint: '', derived_from: [], metadata: {} }],
    metadata: {},
    created_at: '2026-08-28T00:00:00Z',
    updated_at: '2026-08-28T00:00:00Z',
  }, {
    node_id: 'dubbing:dub-1',
    project_id: 'project-1',
    workspace: 'dubbing',
    owner_id: 'dub-1',
    label: 'Bản lồng tiếng',
    route: '/voice/dubbing',
    revision: 1,
    assets: [{ asset_id: 'dub-output', role: 'dubbed_audio', ownership: 'generated', path_hint: '', fingerprint: '', derived_from: ['doc-1'], metadata: {} }],
    metadata: {},
    created_at: '2026-08-28T00:02:00Z',
    updated_at: '2026-08-28T00:02:00Z',
  }],
  handoffs: [{
    handoff_id: 'handoff-1',
    project_id: 'project-1',
    source_node_id: 'transcripts:transcript-1',
    source_workspace: 'transcripts',
    source_revision: 2,
    source_route: '/voice/transcripts',
    target_workspace: 'dubbing',
    target_route: '/voice/dubbing',
    target_node_id: '',
    status: 'opened',
    input_asset_ids: ['doc-1'],
    output_asset_ids: [],
    payload: { transcript_id: 'transcript-1' },
    created_at: '2026-08-28T00:00:00Z',
    opened_at: '2026-08-28T00:01:00Z',
    returned_at: '',
  }],
} satisfies ProjectGraph

describe('ProjectGraphPanel', () => {
  beforeEach(() => {
    vi.mocked(api.fetchProjectGraph).mockResolvedValue(graph)
    vi.mocked(api.fetchProjectWorkspaces).mockResolvedValue([
      { id: 'transcripts', label: 'Transcripts', route: '/voice/transcripts', targets: ['dubbing'] },
      { id: 'dubbing', label: 'Dubbing', route: '/voice/dubbing', targets: ['editor'] },
    ])
    vi.mocked(api.upsertProjectNode).mockResolvedValue(graph.nodes[0])
    vi.mocked(api.returnProjectHandoff).mockResolvedValue({ ...graph.handoffs[0], status: 'returned' })
  })

  it('shows ownership and returns to the immutable source', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/voice/dubbing']}>
          <ProjectGraphPanel projectId="project-1" />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: /Luồng dự án/i }))
    expect(await screen.findByText('Phỏng vấn')).toBeInTheDocument()
    expect(screen.getByText('1 asset · revision 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Quyền sở hữu asset')).toHaveTextContent(
      '1 managed0 linked1 generated',
    )
    expect(screen.getByText('Transcripts → Dubbing')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hoàn tất & quay lại' }))
    await waitFor(() => expect(api.returnProjectHandoff).toHaveBeenCalledWith('handoff-1', {
      target_node_id: 'dubbing:dub-1',
      output_asset_ids: ['dub-output'],
    }))
  })
})

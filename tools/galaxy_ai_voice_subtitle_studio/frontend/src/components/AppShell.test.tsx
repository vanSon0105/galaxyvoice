import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from './AppShell'

vi.mock('../hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'project-1' }))
vi.mock('./DiagnosticsPanel', () => ({ DiagnosticsPanel: () => null }))
vi.mock('./project/ProjectGraphPanel', () => ({ ProjectGraphPanel: () => null }))
vi.mock('./ProgressPanel', () => ({
  ProgressPanel: ({ open }: { open: boolean }) => open ? <div aria-label="Nhật ký tác vụ">Log</div> : null,
}))

afterEach(cleanup)

describe('AppShell task log', () => {
  it('keeps the task log hidden by default and toggles it from the titlebar', () => {
    render(<MemoryRouter><AppShell wsState="open"><div>Nội dung</div></AppShell></MemoryRouter>)

    expect(screen.queryByLabelText('Nhật ký tác vụ')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hiện log' }))
    expect(screen.getByLabelText('Nhật ký tác vụ')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ẩn log' }))
    expect(screen.queryByLabelText('Nhật ký tác vụ')).not.toBeInTheDocument()
  })
})

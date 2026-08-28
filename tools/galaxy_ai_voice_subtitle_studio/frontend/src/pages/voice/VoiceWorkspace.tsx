import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { fetchProjects, saveProject } from '../../api/workspaces'
import { WorkspaceLoading } from '../../components/WorkspaceState'
import { ACTIVE_PROJECT_CHANGED_EVENT, ACTIVE_PROJECT_KEY } from '../../hooks/useActiveProjectId'
import { VOICE_NAV_ITEMS } from '../../nav'
import { VoiceProjectContext } from './VoiceProjectContext'

function currentWorkspace(pathname: string): string {
  return VOICE_NAV_ITEMS.find((item) =>
    item.route === '/voice' ? pathname === '/voice' : pathname.startsWith(item.route),
  )?.id ?? 'studio'
}

export function VoiceWorkspace() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState(
    () => window.localStorage.getItem(ACTIVE_PROJECT_KEY) ?? '',
  )
  const [creating, setCreating] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [formError, setFormError] = useState('')

  const projectsQuery = useQuery({
    queryKey: ['workspace-projects'],
    queryFn: () => fetchProjects(),
  })
  const projects = useMemo(
    () => [...(projectsQuery.data ?? [])].sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    [projectsQuery.data],
  )
  const project = projects.find((item) => item.project_id === projectId) ?? null

  useEffect(() => {
    if (projectsQuery.isPending) return
    if (projects.length === 0) {
      if (projectId) setProjectId('')
      return
    }
    if (!projects.some((item) => item.project_id === projectId)) {
      setProjectId(projects[0].project_id)
    }
  }, [projectId, projects, projectsQuery.isPending])

  useEffect(() => {
    if (projectId) window.localStorage.setItem(ACTIVE_PROJECT_KEY, projectId)
    else window.localStorage.removeItem(ACTIVE_PROJECT_KEY)
    window.dispatchEvent(new Event(ACTIVE_PROJECT_CHANGED_EVENT))
  }, [projectId])

  const createProject = useMutation({
    mutationFn: (name: string) => saveProject({
      workspace: currentWorkspace(location.pathname),
      name,
      payload: { native_voice_workspace: true },
    }),
    onSuccess: async (created) => {
      setProjectId(created.project_id)
      setProjectName('')
      setCreating(false)
      setFormError('')
      await queryClient.invalidateQueries({ queryKey: ['workspace-projects'] })
    },
    onError: (cause) => setFormError(cause instanceof Error ? cause.message : String(cause)),
  })

  const activeSurface = VOICE_NAV_ITEMS.find((item) =>
    item.route === '/voice' ? location.pathname === '/voice' : location.pathname.startsWith(item.route),
  )
  const isReference = location.pathname === '/voice/reference'

  return (
    <VoiceProjectContext.Provider value={{ project, projectId }}>
      <div className="voice-workspace">
        <header className="voice-workspace-header">
          <div className="voice-workspace-heading">
            <span className="workspace-kicker">Voice Workspace</span>
            <div>
              <h1>{isReference ? 'VoiceStudio đối chiếu' : activeSurface?.label ?? 'Voice'}</h1>
              <p>
                {isReference
                  ? 'Bản tham chiếu tách biệt, được giữ lại cho đến khi hoàn tất kiểm tra tương đương.'
                  : activeSurface?.description}
              </p>
            </div>
          </div>

          <div className="voice-project-tools">
            <label htmlFor="voice-project-select">Dự án đang mở</label>
            <div className="voice-project-row">
              {projectsQuery.isPending ? (
                <WorkspaceLoading label="Đang đọc dự án..." />
              ) : (
                <select
                  id="voice-project-select"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  aria-invalid={projectsQuery.isError}
                >
                  <option value="">Chưa chọn dự án</option>
                  {projects.map((item) => (
                    <option key={item.project_id} value={item.project_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              )}
              <button className="btn" type="button" onClick={() => setCreating((value) => !value)}>
                Tạo dự án
              </button>
              <button
                className="btn quiet"
                type="button"
                onClick={() => void projectsQuery.refetch()}
                disabled={projectsQuery.isFetching}
              >
                Làm mới
              </button>
            </div>
            {projectsQuery.isError && <span className="project-error">Không đọc được danh sách dự án.</span>}
            {creating && (
              <form
                className="voice-project-create"
                onSubmit={(event) => {
                  event.preventDefault()
                  const name = projectName.trim()
                  if (!name) {
                    setFormError('Nhập tên dự án trước khi tạo.')
                    return
                  }
                  createProject.mutate(name)
                }}
              >
                <input
                  autoFocus
                  type="text"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="Tên dự án mới"
                  aria-label="Tên dự án mới"
                />
                <button className="btn accent" type="submit" disabled={createProject.isPending}>Tạo</button>
                <button className="btn quiet" type="button" onClick={() => setCreating(false)}>Hủy</button>
                {formError && <span className="project-error">{formError}</span>}
              </form>
            )}
          </div>
        </header>

        <div className="voice-navigation-row">
          <nav className="voice-navigation" aria-label="Khu vực Voice">
            {VOICE_NAV_ITEMS.map((item) => (
              <NavLink
                key={item.id}
                to={item.route}
                end={item.id === 'studio'}
                className={({ isActive }) => `voice-navigation-item${isActive ? ' active' : ''}`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button className="reference-link" type="button" onClick={() => navigate('/voice/reference')}>
            Bản đối chiếu
          </button>
        </div>

        <div className="voice-workspace-content">
          <Outlet />
        </div>
      </div>
    </VoiceProjectContext.Provider>
  )
}

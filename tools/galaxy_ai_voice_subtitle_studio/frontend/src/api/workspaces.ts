import { apiJson } from './client'

export interface WorkspaceProject {
  project_id: string
  workspace: string
  name: string
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface HistoryItem {
  history_id: string
  workspace: string
  title: string
  summary: string
  artifact_path: string
  metadata: Record<string, unknown>
  starred: boolean
  created_at: string
}

export interface Archetype {
  archetype_id: string
  name: string
  language: string
  use_case: string
  instruct: string
  sample_text: string
  gender: string
  age: string
  pitch: string
  accent: string
  style: string
  featured: boolean
}

export interface GalleryPageData {
  total: number
  page: number
  page_size: number
  items: Archetype[]
}

// Projects
export const fetchProjects = (workspace = '') =>
  apiJson<WorkspaceProject[]>(`/api/workspaces/projects?workspace=${encodeURIComponent(workspace)}`)
export const saveProject = (body: {
  workspace: string
  name: string
  payload?: Record<string, unknown>
  project_id?: string
}) =>
  apiJson<WorkspaceProject>('/api/workspaces/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
export const deleteProject = (projectId: string) =>
  apiJson<{ ok: boolean }>(`/api/workspaces/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  })

// History
export const fetchHistory = (params: { workspace?: string; query?: string; starred_only?: boolean } = {}) => {
  const search = new URLSearchParams()
  if (params.workspace) search.set('workspace', params.workspace)
  if (params.query) search.set('query', params.query)
  if (params.starred_only) search.set('starred_only', 'true')
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return apiJson<HistoryItem[]>(`/api/workspaces/history${suffix}`)
}
export const addHistory = (body: {
  workspace: string
  title: string
  summary?: string
  artifact_path?: string
  metadata?: Record<string, unknown>
}) =>
  apiJson<HistoryItem>('/api/workspaces/history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

// Gallery
export const fetchGalleryCategories = () => apiJson<string[]>('/api/workspaces/gallery/categories')
export const fetchGallery = (params: {
  query?: string
  use_case?: string
  language?: string
  gender?: string
  age?: string
  pitch?: string
  style?: string
  page?: number
} = {}) => {
  const search = new URLSearchParams({ page: String(params.page ?? 1) })
  if (params.query) search.set('query', params.query)
  if (params.use_case) search.set('use_case', params.use_case)
  if (params.language) search.set('language', params.language)
  if (params.gender) search.set('gender', params.gender)
  if (params.age) search.set('age', params.age)
  if (params.pitch) search.set('pitch', params.pitch)
  if (params.style) search.set('style', params.style)
  return apiJson<GalleryPageData>(`/api/workspaces/gallery?${search.toString()}`)
}

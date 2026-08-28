import { apiJson } from './client'

export type AssetOwnership = 'managed' | 'linked' | 'generated'
export type HandoffStatus = 'pending' | 'opened' | 'returned'

export interface ProjectAssetReference {
  asset_id: string
  role: string
  path_hint: string
  ownership: AssetOwnership
  fingerprint: string
  derived_from: string[]
  metadata: Record<string, unknown>
}

export interface ProjectGraphNode {
  node_id: string
  project_id: string
  workspace: string
  owner_id: string
  label: string
  route: string
  revision: number
  assets: ProjectAssetReference[]
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ProjectHandoff {
  handoff_id: string
  project_id: string
  source_node_id: string
  source_workspace: string
  source_revision: number
  source_route: string
  target_workspace: string
  target_route: string
  target_node_id: string
  status: HandoffStatus
  input_asset_ids: string[]
  output_asset_ids: string[]
  payload: Record<string, unknown>
  created_at: string
  opened_at: string
  returned_at: string
}

export interface ProjectGraph {
  project_id: string
  nodes: ProjectGraphNode[]
  handoffs: ProjectHandoff[]
  updated_at: string
}

export interface ProjectWorkspaceSpec {
  id: string
  label: string
  route: string
  targets: string[]
}

export interface ProjectNodeInput {
  project_id: string
  workspace: string
  owner_id: string
  label: string
  revision?: number
  assets?: ProjectAssetReference[]
  metadata?: Record<string, unknown>
}

export const fetchProjectGraph = (projectId: string) =>
  apiJson<ProjectGraph>(`/api/project-graph/projects/${encodeURIComponent(projectId)}`)

export const fetchProjectWorkspaces = () =>
  apiJson<ProjectWorkspaceSpec[]>('/api/project-graph/workspaces')

export const upsertProjectNode = (body: ProjectNodeInput) =>
  apiJson<ProjectGraphNode>('/api/project-graph/nodes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const createProjectHandoff = (body: {
  project_id: string
  source_node_id: string
  target_workspace: string
  input_asset_ids?: string[]
  payload?: Record<string, unknown>
}) => apiJson<ProjectHandoff>('/api/project-graph/handoffs', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const openProjectHandoff = (handoffId: string) =>
  apiJson<ProjectHandoff>(`/api/project-graph/handoffs/${encodeURIComponent(handoffId)}/open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })

export const returnProjectHandoff = (
  handoffId: string,
  body: { target_node_id?: string; output_asset_ids: string[] },
) => apiJson<ProjectHandoff>(
  `/api/project-graph/handoffs/${encodeURIComponent(handoffId)}/return`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  },
)

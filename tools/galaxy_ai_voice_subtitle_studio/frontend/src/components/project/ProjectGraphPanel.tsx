import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  createProjectHandoff,
  fetchProjectGraph,
  fetchProjectWorkspaces,
  openProjectHandoff,
  returnProjectHandoff,
  upsertProjectNode,
  type ProjectHandoff,
  type ProjectWorkspaceSpec,
} from '../../api/projectGraph'

export function ProjectGraphPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false)
  const [sourceNodeId, setSourceNodeId] = useState('')
  const [targetWorkspace, setTargetWorkspace] = useState('')
  const [error, setError] = useState('')
  const registeredKey = useRef('')
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const catalogQuery = useQuery({
    queryKey: ['project-graph-workspaces'],
    queryFn: fetchProjectWorkspaces,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const graphQuery = useQuery({
    queryKey: ['project-graph', projectId],
    queryFn: () => fetchProjectGraph(projectId),
    enabled: Boolean(projectId),
  })
  const catalog = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data])
  const graph = graphQuery.data
  const currentWorkspace = workspaceForRoute(catalog, location.pathname)
  const activeCount = graph?.handoffs.filter((item) => item.status !== 'returned').length ?? 0
  const ownershipCounts = useMemo(() => {
    const counts = { managed: 0, linked: 0, generated: 0 }
    graph?.nodes.forEach((node) => node.assets.forEach((asset) => {
      counts[asset.ownership] += 1
    }))
    return counts
  }, [graph?.nodes])

  useEffect(() => {
    setSourceNodeId('')
    setTargetWorkspace('')
    setError('')
    registeredKey.current = ''
  }, [projectId])

  useEffect(() => {
    if (!open || !projectId || !currentWorkspace) return
    const registrationKey = `${projectId}:${currentWorkspace.id}`
    if (registeredKey.current === registrationKey) return
    registeredKey.current = registrationKey
    void upsertProjectNode({
      project_id: projectId,
      workspace: currentWorkspace.id,
      owner_id: `${projectId}:workspace-root`,
      label: `${currentWorkspace.label} · ngữ cảnh dự án`,
      metadata: { context_node: true },
    }).then(async (node) => {
      setSourceNodeId((value) => value || node.node_id)
      await queryClient.invalidateQueries({ queryKey: ['project-graph', projectId] })
    }).catch((cause) => {
      registeredKey.current = ''
      setError(cause instanceof Error ? cause.message : String(cause))
    })
  }, [currentWorkspace, open, projectId, queryClient])

  const sourceNode = graph?.nodes.find((item) => item.node_id === sourceNodeId)
  const targetOptions = useMemo(() => {
    if (!sourceNode) return []
    const allowed = catalog.find((item) => item.id === sourceNode.workspace)?.targets ?? []
    return catalog.filter((item) => allowed.includes(item.id))
  }, [catalog, sourceNode])

  useEffect(() => {
    if (!sourceNodeId && graph?.nodes.length) setSourceNodeId(graph.nodes[0].node_id)
  }, [graph?.nodes, sourceNodeId])

  useEffect(() => {
    if (!targetOptions.some((item) => item.id === targetWorkspace)) {
      setTargetWorkspace(targetOptions[0]?.id ?? '')
    }
  }, [targetOptions, targetWorkspace])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['project-graph', projectId] })

  const createHandoff = async () => {
    if (!sourceNode || !targetWorkspace) return
    setError('')
    try {
      await createProjectHandoff({
        project_id: projectId,
        source_node_id: sourceNode.node_id,
        target_workspace: targetWorkspace,
        input_asset_ids: sourceNode.assets.map((item) => item.asset_id),
        payload: { context_only: sourceNode.assets.length === 0 },
      })
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const openDestination = async (handoff: ProjectHandoff) => {
    setError('')
    try {
      if (handoff.status === 'pending') await openProjectHandoff(handoff.handoff_id)
      await refresh()
      const params = new URLSearchParams({ handoff: handoff.handoff_id })
      const transcriptId = String(handoff.payload.transcript_id ?? '')
      if (transcriptId) params.set('transcript', transcriptId)
      navigate(`${handoff.target_route}?${params.toString()}`)
      setOpen(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const returnToSource = async (handoff: ProjectHandoff) => {
    setError('')
    try {
      if (handoff.status !== 'returned') {
        const targetNode = graph?.nodes.find(
          (node) => node.workspace === handoff.target_workspace
            && node.metadata.context_node !== true
            && node.assets.length > 0,
        )
        await returnProjectHandoff(handoff.handoff_id, {
          target_node_id: targetNode?.node_id,
          output_asset_ids: targetNode?.assets.map((asset) => asset.asset_id) ?? [],
        })
      }
      await refresh()
      navigate(`${handoff.source_route}?handoff_return=${encodeURIComponent(handoff.handoff_id)}`)
      setOpen(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="project-graph-control">
      <button
        className="project-graph-trigger"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        Luồng dự án{activeCount ? ` · ${activeCount}` : ''}
      </button>
      {open && (
        <aside className="project-graph-panel" aria-label="Luồng dự án">
          <div className="project-graph-heading">
            <div>
              <span className="workspace-kicker">Active Project</span>
              <h2>Luồng và nguồn dữ liệu</h2>
            </div>
            <button className="btn quiet" type="button" onClick={() => setOpen(false)} aria-label="Đóng">×</button>
          </div>

          {!projectId && <p className="project-graph-empty">Chọn một dự án để theo dõi luồng.</p>}
          {projectId && graphQuery.isPending && <p className="project-graph-empty">Đang đọc project graph...</p>}
          {error && <div className="project-error" role="alert">{error}</div>}

          {graph && (
            <>
              <section className="project-graph-section">
                <div className="section-header compact"><h3 className="section-title">Thành phần</h3><span>{graph.nodes.length}</span></div>
                <div className="project-ownership-summary" aria-label="Quyền sở hữu asset">
                  <span><strong>{ownershipCounts.managed}</strong> managed</span>
                  <span><strong>{ownershipCounts.linked}</strong> linked</span>
                  <span><strong>{ownershipCounts.generated}</strong> generated</span>
                </div>
                <div className="project-node-list">
                  {graph.nodes.map((node) => (
                    <button
                      key={node.node_id}
                      type="button"
                      className={`project-node${sourceNodeId === node.node_id ? ' selected' : ''}`}
                      onClick={() => setSourceNodeId(node.node_id)}
                    >
                      <span>{node.label}</span>
                      <small>{node.assets.length} asset · revision {node.revision}</small>
                    </button>
                  ))}
                </div>
              </section>

              {sourceNode && targetOptions.length > 0 && (
                <section className="project-handoff-create">
                  <label htmlFor="project-handoff-target">Mở thành phần đang chọn trong</label>
                  <div className="project-handoff-create-row">
                    <select id="project-handoff-target" value={targetWorkspace} onChange={(event) => setTargetWorkspace(event.target.value)}>
                      {targetOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                    <button className="btn accent" type="button" onClick={() => void createHandoff()}>Tạo handoff</button>
                  </div>
                </section>
              )}

              <section className="project-graph-section">
                <div className="section-header compact"><h3 className="section-title">Lịch sử handoff</h3><span>{graph.handoffs.length}</span></div>
                {graph.handoffs.length === 0 ? <p className="project-graph-empty">Chưa có handoff.</p> : (
                  <div className="project-handoff-list">
                    {graph.handoffs.map((handoff) => (
                      <article className="project-handoff" key={handoff.handoff_id}>
                        <div>
                          <strong>{labelFor(catalog, handoff.source_workspace)} → {labelFor(catalog, handoff.target_workspace)}</strong>
                          <span className={`handoff-status ${handoff.status}`}>{statusLabel(handoff.status)}</span>
                          <small>{handoff.input_asset_ids.length} đầu vào · {handoff.output_asset_ids.length} đầu ra</small>
                        </div>
                        <div className="project-handoff-actions">
                          <button className="btn" type="button" onClick={() => void openDestination(handoff)}>Mở đích</button>
                          <button className="btn quiet" type="button" onClick={() => void returnToSource(handoff)}>
                            {handoff.status === 'returned' ? 'Mở nguồn' : 'Hoàn tất & quay lại'}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </aside>
      )}
    </div>
  )
}

function workspaceForRoute(catalog: ProjectWorkspaceSpec[], pathname: string) {
  return [...catalog]
    .sort((left, right) => right.route.length - left.route.length)
    .find((item) => item.route === '/voice' ? pathname === '/voice' : pathname.startsWith(item.route))
}

function labelFor(catalog: ProjectWorkspaceSpec[], workspace: string) {
  return catalog.find((item) => item.id === workspace)?.label ?? workspace
}

function statusLabel(status: ProjectHandoff['status']) {
  if (status === 'opened') return 'Đang xử lý'
  if (status === 'returned') return 'Đã quay lại'
  return 'Chờ mở'
}

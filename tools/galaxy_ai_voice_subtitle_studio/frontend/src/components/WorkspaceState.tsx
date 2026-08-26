import type { ReactNode } from 'react'

interface WorkspaceStateProps {
  title: string
  description?: string
  action?: ReactNode
  tone?: 'default' | 'error'
}

export function WorkspaceState({ title, description, action, tone = 'default' }: WorkspaceStateProps) {
  return (
    <div
      className={`workspace-state${tone === 'error' ? ' error' : ''}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <div className="workspace-state-mark" aria-hidden="true" />
      <strong>{title}</strong>
      {description && <p>{description}</p>}
      {action}
    </div>
  )
}

export function WorkspaceLoading({ label = 'Đang tải dữ liệu...' }: { label?: string }) {
  return (
    <div className="workspace-loading" role="status">
      <span className="workspace-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

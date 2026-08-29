import { useRef, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { useT } from '../i18n/useT'
import { useActiveProjectId } from '../hooks/useActiveProjectId'
import { NAV_ITEMS } from '../nav'
import type { WsState } from '../ws/useEvents'
import { ProgressPanel } from './ProgressPanel'
import { DiagnosticsPanel } from './DiagnosticsPanel'
import { ProjectGraphPanel } from './project/ProjectGraphPanel'

interface AppShellProps {
  wsState: WsState
  children: ReactNode
}

export function AppShell({ wsState, children }: AppShellProps) {
  const t = useT()
  const projectId = useActiveProjectId()
  const location = useLocation()
  const diagnosticsTriggerRef = useRef<HTMLButtonElement>(null)
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const [setupSeen, setSetupSeen] = useState(() => {
    try {
      return window.localStorage.getItem('galaxy.setup.seen') === '1'
    } catch {
      return true
    }
  })
  const closeDiagnostics = () => {
    setDiagnosticsOpen(false)
    window.requestAnimationFrame(() => diagnosticsTriggerRef.current?.focus())
  }
  const completeSetup = () => {
    if (!setupSeen) {
      try {
        window.localStorage.setItem('galaxy.setup.seen', '1')
      } catch {
        // Storage may be disabled; the setup entry remains harmless.
      }
      setSetupSeen(true)
    }
  }
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Bỏ qua tới nội dung chính</a>
      <header className="titlebar">
        <div className="brand">
          <span className="brand-name">Galaxy</span>
          <span className="brand-sub"> AI Voice &amp; Subtitle Studio</span>
        </div>
        <nav className="tabs" role="tablist">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.id}
              to={item.route}
              role="tab"
              aria-selected={location.pathname === item.route || location.pathname.startsWith(`${item.route}/`)}
              className={({ isActive }) => `tab${isActive ? ' active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="titlebar-status">
          <button
            ref={diagnosticsTriggerRef}
            className="diagnostics-trigger"
            aria-expanded={diagnosticsOpen}
            data-first-run={!setupSeen || undefined}
            onClick={() => setDiagnosticsOpen((value) => !value)}
          >
            {setupSeen ? 'Chẩn đoán' : 'Thiết lập máy'}
          </button>
          <ProjectGraphPanel projectId={projectId} />
          <span className={`status-dot ${wsState === 'open' ? 'open' : wsState === 'closed' ? 'closed' : ''}`} />
          <span>
            {wsState === 'open'
              ? t('ws.open')
              : wsState === 'closed'
                ? t('ws.closed')
                : t('ws.connecting')}
          </span>
        </div>
      </header>
      <main className="content" id="main-content" tabIndex={-1}>{children}</main>
      <DiagnosticsPanel open={diagnosticsOpen} onClose={closeDiagnostics} onSetupComplete={completeSetup} />
      <ProgressPanel />
    </div>
  )
}

import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { useT } from '../i18n/useT'
import { NAV_ITEMS } from '../nav'
import type { WsState } from '../ws/useEvents'
import { ProgressPanel } from './ProgressPanel'

interface AppShellProps {
  wsState: WsState
  children: ReactNode
}

export function AppShell({ wsState, children }: AppShellProps) {
  const t = useT()
  const location = useLocation()
  return (
    <div className="shell">
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
              className={() => {
                const voiceStudioActive = location.pathname === '/omnivoice/voicestudio'
                const active =
                  item.id === 'voicestudio'
                    ? voiceStudioActive
                    : item.id === 'omnivoice'
                      ? location.pathname.startsWith('/omnivoice') && !voiceStudioActive
                      : location.pathname.startsWith(item.route)
                return `tab${active ? ' active' : ''}`
              }}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="titlebar-status">
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
      <main className="content">{children}</main>
      <ProgressPanel />
    </div>
  )
}

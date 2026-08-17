import { NavLink, Outlet } from 'react-router-dom'

/** OmniVoice workspace shell with its own sub-tabs. */
export function OmniVoiceWorkspace() {
  const subTabs = [
    { id: 'studio', label: 'Studio', route: '/omnivoice' },
    { id: 'batch', label: 'Batch', route: '/omnivoice/batch' },
    { id: 'profiles', label: 'Thư viện giọng', route: '/omnivoice/profiles' },
    { id: 'gallery', label: 'Gallery', route: '/omnivoice/gallery' },
    { id: 'transcripts', label: 'Transcripts', route: '/omnivoice/transcripts' },
    { id: 'workspaces', label: 'Truyện & Sách nói', route: '/omnivoice/workspaces' },
  ]
  return (
    <div>
      <nav className="sub-tabs" role="tablist">
        {subTabs.map((tab) => (
          <NavLink
            key={tab.id}
            to={tab.route}
            role="tab"
            end={tab.id === 'studio'}
            className={({ isActive }) => `sub-tab${isActive ? ' active' : ''}`}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ marginTop: 14 }}>
        <Outlet />
      </div>
    </div>
  )
}

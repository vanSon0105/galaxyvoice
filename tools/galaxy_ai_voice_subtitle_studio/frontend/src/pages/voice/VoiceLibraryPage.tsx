import { NavLink, Outlet } from 'react-router-dom'

export function VoiceLibraryPage() {
  return (
    <div className="voice-library-layout">
      <nav className="view-switcher" aria-label="Chế độ xem thư viện giọng">
        <NavLink
          to="/voice/library"
          end
          className={({ isActive }) => `view-switch${isActive ? ' active' : ''}`}
        >
          Giọng đã lưu
        </NavLink>
        <NavLink
          to="/voice/library/gallery"
          className={({ isActive }) => `view-switch${isActive ? ' active' : ''}`}
        >
          Mẫu thiết kế
        </NavLink>
      </nav>
      <Outlet />
    </div>
  )
}

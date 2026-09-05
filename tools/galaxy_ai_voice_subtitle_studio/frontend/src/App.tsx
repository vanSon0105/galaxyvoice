import { lazy, Suspense, useEffect, type ComponentType } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { DEFAULT_ROUTE } from './nav'
import { VoiceWorkspace } from './pages/voice/VoiceWorkspace'
import { subscribeEvents } from './ws/hub'
import { useEvents } from './ws/useEvents'

const page = <T extends object, K extends keyof T>(
  loader: () => Promise<T>,
  exportName: K,
) => lazy(async () => ({ default: (await loader())[exportName] as ComponentType }))

const DubPage = page(() => import('./pages/dubbing/DubPage'), 'DubPage')
const BatchPage = page(() => import('./pages/voice/BatchPage'), 'BatchPage')
const GalleryPage = page(() => import('./pages/omnivoice/GalleryPage'), 'GalleryPage')
const StudioPage = page(() => import('./pages/voice/StudioPage'), 'StudioPage')
const VoiceStudioPage = page(() => import('./pages/omnivoice/VoiceStudioPage'), 'VoiceStudioPage')
const EditorPage = page(() => import('./pages/EditorPage'), 'EditorPage')
const SeparationPage = page(() => import('./pages/SeparationPage'), 'SeparationPage')
const SettingsPage = page(() => import('./pages/SettingsPage'), 'SettingsPage')
const ParityPage = page(() => import('./pages/ParityPage'), 'ParityPage')
const VoiceLibraryPage = page(() => import('./pages/voice/VoiceLibraryPage'), 'VoiceLibraryPage')

export function LegacyVoiceRedirect({ to }: { to: string }) {
  const location = useLocation()
  return <Navigate to={{ pathname: to, search: location.search }} replace />
}

export function AppRoutes() {
  return (
    <Suspense fallback={<div className="workspace-loading" role="status">Đang mở workspace...</div>}>
      <Routes>
        <Route path="/dubbing" element={<DubPage />} />
        <Route path="/voice" element={<VoiceWorkspace />}>
          <Route index element={<StudioPage />} />
          <Route path="batch" element={<BatchPage />} />
          <Route path="library" element={<VoiceLibraryPage />} />
          <Route path="library/gallery" element={<GalleryPage />} />
          <Route path="reference" element={<VoiceStudioPage />} />
        </Route>
        <Route path="/omnivoice" element={<LegacyVoiceRedirect to="/voice" />} />
        <Route path="/omnivoice/batch" element={<LegacyVoiceRedirect to="/voice/batch" />} />
        <Route path="/omnivoice/profiles" element={<LegacyVoiceRedirect to="/voice/library" />} />
        <Route path="/omnivoice/gallery" element={<LegacyVoiceRedirect to="/voice/library/gallery" />} />
        <Route path="/omnivoice/voicestudio" element={<LegacyVoiceRedirect to="/voice/reference" />} />
        <Route path="/editor" element={<EditorPage />} />
        <Route path="/separation" element={<SeparationPage />} />
        <Route path="/removal" element={<Navigate to="/editor" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/parity" element={<ParityPage />} />
        <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  const wsState = useEvents()
  const queryClient = useQueryClient()

  useEffect(() => {
    // Server events are refetch signals.
    const unsubscribe = subscribeEvents((event) => {
      if (event.type === 'event') {
        void queryClient.invalidateQueries()
      }
    })
    // Watchdog heartbeat: the shell exits if no health ping arrives for 60 s.
    const interval = window.setInterval(() => {
      fetch('/api/health').catch(() => undefined)
    }, 5000)
    return () => {
      unsubscribe()
      window.clearInterval(interval)
    }
  }, [queryClient])

  return (
    <AppShell wsState={wsState}>
      <AppRoutes />
    </AppShell>
  )
}

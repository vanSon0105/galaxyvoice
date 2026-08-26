import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { DEFAULT_ROUTE } from './nav'
import { DubPage } from './pages/dubbing/DubPage'
import { BatchPage } from './pages/omnivoice/BatchPage'
import { DubbingPage } from './pages/omnivoice/DubbingPage'
import { GalleryPage } from './pages/omnivoice/GalleryPage'
import { ProfilesPage } from './pages/omnivoice/ProfilesPage'
import { StudioPage } from './pages/omnivoice/StudioPage'
import { TranscriptsPage } from './pages/omnivoice/TranscriptsPage'
import { VoiceStudioPage } from './pages/omnivoice/VoiceStudioPage'
import { WorkspacesPage } from './pages/omnivoice/WorkspacesPage'
import { EditorPage } from './pages/EditorPage'
import { SeparationPage } from './pages/SeparationPage'
import { RemovalPage } from './pages/RemovalPage'
import { SettingsPage } from './pages/SettingsPage'
import { VoiceLibraryPage } from './pages/voice/VoiceLibraryPage'
import { VoiceWorkspace } from './pages/voice/VoiceWorkspace'
import { subscribeEvents } from './ws/hub'
import { useEvents } from './ws/useEvents'

export function LegacyVoiceRedirect({ to }: { to: string }) {
  const location = useLocation()
  return <Navigate to={{ pathname: to, search: location.search }} replace />
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
      <Routes>
        <Route path="/dubbing" element={<DubPage />} />
        <Route path="/voice" element={<VoiceWorkspace />}>
          <Route index element={<StudioPage />} />
          <Route path="batch" element={<BatchPage />} />
          <Route path="library" element={<VoiceLibraryPage />}>
            <Route index element={<ProfilesPage />} />
            <Route path="gallery" element={<GalleryPage />} />
          </Route>
          <Route path="transcripts" element={<TranscriptsPage />} />
          <Route path="longform" element={<WorkspacesPage />} />
          <Route path="dubbing" element={<DubbingPage />} />
          <Route path="reference" element={<VoiceStudioPage />} />
        </Route>
        <Route path="/omnivoice" element={<LegacyVoiceRedirect to="/voice" />} />
        <Route path="/omnivoice/batch" element={<LegacyVoiceRedirect to="/voice/batch" />} />
        <Route path="/omnivoice/profiles" element={<LegacyVoiceRedirect to="/voice/library" />} />
        <Route path="/omnivoice/gallery" element={<LegacyVoiceRedirect to="/voice/library/gallery" />} />
        <Route path="/omnivoice/transcripts" element={<LegacyVoiceRedirect to="/voice/transcripts" />} />
        <Route path="/omnivoice/workspaces" element={<LegacyVoiceRedirect to="/voice/longform" />} />
        <Route path="/omnivoice/dubbing" element={<LegacyVoiceRedirect to="/voice/dubbing" />} />
        <Route path="/omnivoice/voicestudio" element={<LegacyVoiceRedirect to="/voice/reference" />} />
        <Route path="/editor" element={<EditorPage />} />
        <Route path="/separation" element={<SeparationPage />} />
        <Route path="/removal" element={<RemovalPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
      </Routes>
    </AppShell>
  )
}

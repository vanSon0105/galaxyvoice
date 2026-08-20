import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { DEFAULT_ROUTE } from './nav'
import { DubPage } from './pages/dubbing/DubPage'
import { BatchPage } from './pages/omnivoice/BatchPage'
import { DubbingPage } from './pages/omnivoice/DubbingPage'
import { GalleryPage } from './pages/omnivoice/GalleryPage'
import { OmniVoiceWorkspace } from './pages/omnivoice/OmniVoiceWorkspace'
import { ProfilesPage } from './pages/omnivoice/ProfilesPage'
import { StudioPage } from './pages/omnivoice/StudioPage'
import { TranscriptsPage } from './pages/omnivoice/TranscriptsPage'
import { VoiceStudioPage } from './pages/omnivoice/VoiceStudioPage'
import { WorkspacesPage } from './pages/omnivoice/WorkspacesPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { SeparationPage } from './pages/SeparationPage'
import { RemovalPage } from './pages/RemovalPage'
import { SettingsPage } from './pages/SettingsPage'
import { subscribeEvents } from './ws/hub'
import { useEvents } from './ws/useEvents'

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
        <Route path="/omnivoice" element={<OmniVoiceWorkspace />}>
          <Route index element={<StudioPage />} />
          <Route path="batch" element={<BatchPage />} />
          <Route path="profiles" element={<ProfilesPage />} />
          <Route path="gallery" element={<GalleryPage />} />
          <Route path="transcripts" element={<TranscriptsPage />} />
          <Route path="workspaces" element={<WorkspacesPage />} />
          <Route path="dubbing" element={<DubbingPage />} />
          <Route path="voicestudio" element={<VoiceStudioPage />} />
        </Route>
        <Route path="/editor" element={<PlaceholderPage title="Dựng video" phase="Pha 7" />} />
        <Route path="/separation" element={<SeparationPage />} />
        <Route path="/removal" element={<RemovalPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
      </Routes>
    </AppShell>
  )
}

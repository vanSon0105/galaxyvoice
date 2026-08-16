import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { DEFAULT_ROUTE } from './nav'
import { DubPage } from './pages/dubbing/DubPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
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
        <Route path="/omnivoice" element={<PlaceholderPage title="OmniVoice" phase="Pha 3" />} />
        <Route path="/voicestudio" element={<PlaceholderPage title="VoiceStudio" phase="Pha 4" />} />
        <Route path="/editor" element={<PlaceholderPage title="Dựng video" phase="Pha 7" />} />
        <Route path="/separation" element={<PlaceholderPage title="Tách âm thanh" phase="Pha 5" />} />
        <Route path="/removal" element={<PlaceholderPage title="Xóa phụ đề" phase="Pha 6" />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
      </Routes>
    </AppShell>
  )
}

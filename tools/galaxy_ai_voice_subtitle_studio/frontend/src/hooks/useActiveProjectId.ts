import { useEffect, useState } from 'react'

export const ACTIVE_PROJECT_KEY = 'galaxy.voice.activeProject'
export const ACTIVE_PROJECT_CHANGED_EVENT = 'galaxy:active-project-changed'

export function useActiveProjectId(): string {
  const [projectId, setProjectId] = useState(
    () => window.localStorage.getItem(ACTIVE_PROJECT_KEY) ?? '',
  )

  useEffect(() => {
    const sync = () => setProjectId(window.localStorage.getItem(ACTIVE_PROJECT_KEY) ?? '')
    window.addEventListener('storage', sync)
    window.addEventListener(ACTIVE_PROJECT_CHANGED_EVENT, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(ACTIVE_PROJECT_CHANGED_EVENT, sync)
    }
  }, [])

  return projectId
}

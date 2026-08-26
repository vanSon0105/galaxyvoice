import { createContext, useContext } from 'react'

import type { WorkspaceProject } from '../../api/workspaces'

export interface VoiceProjectContextValue {
  project: WorkspaceProject | null
  projectId: string
}

export const VoiceProjectContext = createContext<VoiceProjectContextValue>({
  project: null,
  projectId: '',
})

export function useVoiceProject() {
  return useContext(VoiceProjectContext)
}

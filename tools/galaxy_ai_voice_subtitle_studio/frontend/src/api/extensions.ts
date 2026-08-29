import { apiJson } from './client'

export type ExtensionCapabilityDisposition =
  | 'extension'
  | 'deferred'
  | 'optional_adapter'
  | 'non_goal'

export interface ExtensionCapability {
  capability_id: string
  label: string
  category: string
  disposition: ExtensionCapabilityDisposition
  summary: string
  boundary: string
  constraints: string[]
  revisit_triggers: string[]
  extension_capability_ids: string[]
  default_enabled: boolean
}

export interface ExtensionCapabilitiesResponse {
  capabilities: ExtensionCapability[]
}

export function fetchExtensionCapabilities(): Promise<ExtensionCapabilitiesResponse> {
  return apiJson<ExtensionCapabilitiesResponse>('/api/extensions/capabilities')
}

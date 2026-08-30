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

const DISPOSITIONS = new Set<ExtensionCapabilityDisposition>([
  'extension',
  'deferred',
  'optional_adapter',
  'non_goal',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  if (typeof value !== 'string') throw new Error(`Invalid extension capability field: ${key}`)
  return value
}

function readStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key]
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new Error(`Invalid extension capability field: ${key}`)
  }
  return value
}

function parseCapability(value: unknown): ExtensionCapability {
  if (!isRecord(value)) throw new Error('Invalid extension capability entry')
  const disposition = readString(value, 'disposition')
  if (!DISPOSITIONS.has(disposition as ExtensionCapabilityDisposition)) {
    throw new Error('Invalid extension capability disposition')
  }
  if (typeof value.default_enabled !== 'boolean') {
    throw new Error('Invalid extension capability field: default_enabled')
  }
  return {
    capability_id: readString(value, 'capability_id'),
    label: readString(value, 'label'),
    category: readString(value, 'category'),
    disposition: disposition as ExtensionCapabilityDisposition,
    summary: readString(value, 'summary'),
    boundary: readString(value, 'boundary'),
    constraints: readStringArray(value, 'constraints'),
    revisit_triggers: readStringArray(value, 'revisit_triggers'),
    extension_capability_ids: readStringArray(value, 'extension_capability_ids'),
    default_enabled: value.default_enabled,
  }
}

function parseCapabilitiesResponse(value: unknown): ExtensionCapabilitiesResponse {
  if (!isRecord(value) || !Array.isArray(value.capabilities)) {
    throw new Error('Invalid extension capabilities response')
  }
  return { capabilities: value.capabilities.map(parseCapability) }
}

export async function fetchExtensionCapabilities(): Promise<ExtensionCapabilitiesResponse> {
  const response = await apiJson<unknown>('/api/extensions/capabilities')
  return parseCapabilitiesResponse(response)
}

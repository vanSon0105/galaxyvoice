import { apiJson } from './client'

export interface DiskCheck {
  path: string
  total_bytes: number
  available_bytes: number
  required_bytes: number
  reserve_bytes: number
  ready: boolean
  message: string
}

export interface SystemReport {
  cpu_count: number
  total_memory_bytes: number
  nvidia_gpu: boolean
  cuda_device_count: number
  recommended_device: string
  disks: DiskCheck[]
  log_path: string
}

export interface CapabilityDescriptor {
  capability_id: string
  kind: string
  label: string
  provider: string
  devices: string[]
  default_device: string
}

export interface OperationAudit {
  capability_id: string
  ready: boolean
  state: string
  requested_device: string
  resolved_device: string
  fallback_used: boolean
  recommended_model_id: string
  message: string
  checks: Array<{ code: string; state: string; message: string; remediation: string }>
  disk: DiskCheck | null
}

export const fetchSystemReport = () => apiJson<SystemReport>('/api/reliability/report')
export const fetchCapabilities = () => apiJson<CapabilityDescriptor[]>('/api/runtime/capabilities')
export const auditOperation = (
  capabilityId: string,
  device: string,
  options: { model_id?: string; options?: Record<string, string>; output_path?: string; required_disk_bytes?: number } = {},
) =>
  apiJson<OperationAudit>('/api/reliability/audit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capability_id: capabilityId, device, ...options }),
  })
export const fetchDiagnosticLogs = (limit = 200) =>
  apiJson<{ path: string; lines: string[] }>(`/api/reliability/logs?limit=${limit}`)

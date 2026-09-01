import { ApiError, apiFetch, apiJson } from './client'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type CheckStatus = 'pass' | 'fail' | 'blocked' | 'manual_pending' | 'not_applicable'
export type RunStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export type AssetReadiness = 'ready' | 'missing' | 'checksum_mismatch' | 'unsupported' | 'unsafe_path'
export type MigrationAssetState = 'managed' | 'linked' | 'missing' | 'unsafe'
export type ReportFormat = 'json' | 'markdown'

export interface SourceFingerprint {
  kind: 'file' | 'directory'
  sha256: string
  byte_size: number
  entry_count: number
}

export interface ParityCase {
  case_id: string
  area: string
  title: string
  required: boolean
  fixture_roles: string[]
  checks: string[]
  manual_prompts: string[]
  thresholds: Record<string, JsonValue>
}

export interface CatalogueResponse {
  version: string
  cases: ParityCase[]
}

export interface Finding {
  code: string
  message: string
}

export interface MediaExpectation {
  extension: string | null
  container: string | null
  audio_codec: string | null
  video_codec: string | null
  audio_streams: number | null
  video_streams: number | null
  subtitle_streams: number | null
  channels: number | null
  sample_rate: number | null
  duration_seconds: number | null
}

export interface ManifestAsset {
  role: string
  path: string
  sha256: string
  byte_size: number
  media: MediaExpectation | null
}

export interface FixtureManifest {
  schema_version: number
  corpus_id: string
  created_at: string
  cases: Array<{ case_id: string; assets: ManifestAsset[] }>
}

export interface MediaInfo {
  container: string
  audio_codec: string | null
  video_codec: string | null
  audio_streams: number
  video_streams: number
  subtitle_streams: number
  channels: number | null
  sample_rate: number | null
  duration_seconds: number | null
}

export interface AssetInspection {
  role: string
  path: string | null
  status: AssetReadiness
  findings: Finding[]
  media: MediaInfo | null
}

export interface CorpusInspection {
  manifest: FixtureManifest
  assets_by_role: Record<string, AssetInspection>
  roles_by_case: Record<string, string[]>
}

export interface ConsentEvidence {
  confirmed: boolean
  basis: string
  statement: string
  recorded_at: string
  provenance: string
}

export interface MigrationAsset {
  role: string
  hint: string
  state: MigrationAssetState
  expected_sha256: string
  byte_size: number
}

export interface MigrationCandidate {
  source_id: string
  target: string
  data: Record<string, JsonValue>
  assets: MigrationAsset[]
  warnings: string[]
  consent: ConsentEvidence
}

export interface MigrationInspection {
  source_before: SourceFingerprint
  source_after: SourceFingerprint
  voice_profiles: MigrationCandidate[]
  persona_bundles: MigrationCandidate[]
  generation_history: MigrationCandidate[]
  dub_history: MigrationCandidate[]
  studio_projects: MigrationCandidate[]
  export_history: MigrationCandidate[]
  glossary_terms: MigrationCandidate[]
  pronunciation_entries: MigrationCandidate[]
  discovered_documents: MigrationCandidate[]
  assets: MigrationAsset[]
  unsupported: Array<{ source: string; reason: string }>
  warnings: string[]
}

export interface CheckResult {
  check_id: string
  status: CheckStatus
  message: string
  measurements: Record<string, JsonValue>
}

export interface CaseResult {
  case_id: string
  status: CheckStatus
  checks: CheckResult[]
}

export interface ManualItem {
  item_id: string
  case_id: string
  prompt: string
  required: boolean
}

export interface ManualAnswer {
  item_id: string
  accepted: boolean
  note: string
  answered_at: string
}

export interface ThresholdOverride {
  case_id: string
  threshold_id: string
  catalogue_value: JsonValue
  override_value: JsonValue
  provenance: string
  note: string
  relaxation: boolean
}

export interface Acceptance {
  note: string
  accepted_at: string
  catalogue_hash: string
  manifest_hash: string
  run_revision: string
  manual_revision: string
  input_revision: string
}

export interface ParityRun {
  run_id: string
  task_id: string
  status: RunStatus
  ready_for_acceptance: boolean
  catalogue_version: string
  catalogue_hash: string
  manifest_path: string
  manifest_hash: string
  manifest_snapshot_path: string
  app_version: string
  created_at: string
  completed_at: string | null
  report_json_path: string
  report_markdown_path: string
  required_case_ids: string[]
  manual_items: ManualItem[]
  thresholds: Record<string, Record<string, JsonValue>>
  threshold_overrides: ThresholdOverride[]
  source_fingerprints: Record<string, SourceFingerprint>
  reference_fingerprints: Record<string, SourceFingerprint>
  case_results: CaseResult[]
  warnings: string[]
  manual_answers: Record<string, ManualAnswer>
  acceptance: Acceptance | null
}

export interface ParityRunSummary {
  run_id: string
  task_id: string
  status: RunStatus
  catalogue_version: string
  app_version: string
  created_at: string
  completed_at: string | null
  accepted: boolean
}

export interface StartParityRunRequest {
  manifest_path: string
  approved_roots: string[]
  measurements_by_case?: Record<string, Record<string, JsonValue>>
  threshold_overrides?: Array<{
    case_id: string
    threshold_id: string
    value: JsonValue
    provenance: string
    note: string
  }>
  source_fingerprints?: Record<string, SourceFingerprint>
  reference_fingerprints?: Record<string, SourceFingerprint>
}

const jsonRequest = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const fetchParityCatalogue = (): Promise<CatalogueResponse> =>
  apiJson<CatalogueResponse>('/api/parity/catalogue')

export const inspectParityCorpus = (request: {
  manifest_path: string
  approved_roots: string[]
}): Promise<CorpusInspection> =>
  apiJson<CorpusInspection>('/api/parity/corpus/inspect', jsonRequest(request))

export const inspectParityMigration = (request: {
  source: string
  approved_roots: string[]
  copied_source_confirmed: boolean
}): Promise<MigrationInspection> =>
  apiJson<MigrationInspection>('/api/parity/migration/inspect', jsonRequest(request))

export const startParityRun = (
  request: StartParityRunRequest,
): Promise<{ task_id: string; run_id: string }> =>
  apiJson<{ task_id: string; run_id: string }>('/api/parity/runs', jsonRequest(request))

export const listParityRuns = (): Promise<{ runs: ParityRunSummary[] }> =>
  apiJson<{ runs: ParityRunSummary[] }>('/api/parity/runs')

export const getParityRun = (runId: string): Promise<ParityRun> =>
  apiJson<ParityRun>(`/api/parity/runs/${encodeURIComponent(runId)}`)

export const recordParityManualAnswer = (
  runId: string,
  itemId: string,
  request: { accepted: boolean; note: string },
): Promise<ParityRun> =>
  apiJson<ParityRun>(
    `/api/parity/runs/${encodeURIComponent(runId)}/manual-items/${encodeURIComponent(itemId)}`,
    jsonRequest(request),
  )

export const acceptParityRun = (
  runId: string,
  request: { note: string },
): Promise<ParityRun> =>
  apiJson<ParityRun>(
    `/api/parity/runs/${encodeURIComponent(runId)}/accept`,
    jsonRequest(request),
  )

export const cancelParityTask = (taskId: string): Promise<{ ok: boolean }> =>
  apiJson<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })

export async function downloadParityReport(
  runId: string,
  format: ReportFormat,
): Promise<Blob> {
  const response = await apiFetch(
    `/api/parity/runs/${encodeURIComponent(runId)}/report?format=${format}`,
  )
  if (!response.ok) {
    throw new ApiError(`Không tải được báo cáo parity (${response.status}).`, response.status)
  }
  return response.blob()
}

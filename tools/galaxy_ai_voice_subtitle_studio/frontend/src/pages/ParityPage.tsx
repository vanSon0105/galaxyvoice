import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import {
  acceptParityRun,
  cancelParityTask,
  downloadParityReport,
  fetchParityCatalogue,
  getParityRun,
  inspectParityCorpus,
  inspectParityMigration,
  listParityRuns,
  recordParityManualAnswer,
  startParityRun,
} from '../api/parity'
import type {
  AssetReadiness,
  CheckStatus,
  CorpusInspection,
  JsonValue,
  MigrationCandidate,
  MigrationInspection,
  ReportFormat,
  RunStatus,
} from '../api/parity'
import { useT } from '../i18n/useT'

const MIGRATION_GROUPS = [
  'voice_profiles',
  'persona_bundles',
  'generation_history',
  'dub_history',
  'studio_projects',
  'export_history',
  'glossary_terms',
  'pronunciation_entries',
  'discovered_documents',
] as const

type Status = CheckStatus | RunStatus | AssetReadiness
type CorpusRequest = Parameters<typeof inspectParityCorpus>[0]
type MigrationRequest = Parameters<typeof inspectParityMigration>[0]

interface RunDraft {
  runId: string
  manualNotes: Record<string, string>
  acceptanceNote: string
}

function StatusLabel({ status }: { status: Status }) {
  const t = useT()
  return <span className={`parity-status ${status}`}>{t(`parity.status.${status}`)}</span>
}

function ErrorState({ children }: { children: string }) {
  return <p className="parity-error" role="alert">{children}</p>
}

function renderValue(value: JsonValue): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function saveReport(blob: Blob, runId: string, format: ReportFormat) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `parity-${runId}.${format === 'json' ? 'json' : 'md'}`
  link.click()
  URL.revokeObjectURL(url)
}

export function ParityPage() {
  const t = useT()
  const queryClient = useQueryClient()
  const [manifestPath, setManifestPath] = useState('')
  const [approvedRoot, setApprovedRoot] = useState('')
  const [migrationSource, setMigrationSource] = useState('')
  const [copiedSourceConfirmed, setCopiedSourceConfirmed] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState('')
  const [runDraft, setRunDraft] = useState<RunDraft>({
    runId: '',
    manualNotes: {},
    acceptanceNote: '',
  })
  const [corpusInspection, setCorpusInspection] = useState<{
    request: CorpusRequest
    result: CorpusInspection
  } | null>(null)
  const [migrationInspection, setMigrationInspection] = useState<{
    request: MigrationRequest
    result: MigrationInspection
  } | null>(null)
  const [reportError, setReportError] = useState<{ runId: string; message: string } | null>(null)
  const [commandMessage, setCommandMessage] = useState('')

  const catalogueQuery = useQuery({
    queryKey: ['parity', 'catalogue'],
    queryFn: fetchParityCatalogue,
  })
  const runsQuery = useQuery({
    queryKey: ['parity', 'runs'],
    queryFn: listParityRuns,
  })
  const runQuery = useQuery({
    queryKey: ['parity', 'run', selectedRunId],
    queryFn: () => getParityRun(selectedRunId),
    enabled: selectedRunId.length > 0,
    refetchInterval: (query) => query.state.data?.status === 'running' ? 1500 : false,
  })

  useEffect(() => {
    if (!selectedRunId && runsQuery.data?.runs[0]) {
      setSelectedRunId(runsQuery.data.runs[0].run_id)
    }
  }, [runsQuery.data, selectedRunId])

  const corpusMutation = useMutation({
    mutationFn: (request: CorpusRequest) => inspectParityCorpus(request),
    onSuccess: (result, request) => setCorpusInspection({ request, result }),
  })
  const migrationMutation = useMutation({
    mutationFn: (request: MigrationRequest) => inspectParityMigration(request),
    onSuccess: (result, request) => setMigrationInspection({ request, result }),
  })
  const startMutation = useMutation({
    mutationFn: (request: Parameters<typeof startParityRun>[0]) => startParityRun(request),
    onSuccess: async (started) => {
      setCommandMessage(t('parity.message.started'))
      setSelectedRunId(started.run_id)
      await queryClient.invalidateQueries({ queryKey: ['parity', 'runs'] })
    },
  })
  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelParityTask(taskId),
    onSuccess: async () => {
      setCommandMessage(t('parity.message.cancelled'))
      await queryClient.invalidateQueries({ queryKey: ['parity'] })
    },
  })
  const manualMutation = useMutation({
    scope: { id: 'parity-manual-evidence' },
    mutationFn: ({ runId, itemId, accepted, note }: {
      runId: string
      itemId: string
      accepted: boolean
      note: string
    }) => recordParityManualAnswer(runId, itemId, { accepted, note }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['parity', 'run', updated.run_id], updated)
    },
  })
  const acceptMutation = useMutation({
    mutationFn: ({ runId, note }: { runId: string; note: string }) =>
      acceptParityRun(runId, { note }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['parity', 'run', updated.run_id], updated)
      setCommandMessage(t('parity.message.accepted'))
      void queryClient.invalidateQueries({ queryKey: ['parity', 'runs'] })
    },
  })
  const reportMutation = useMutation({
    mutationFn: ({ runId, format }: { runId: string; format: ReportFormat }) =>
      downloadParityReport(runId, format),
    onMutate: () => setReportError(null),
    onSuccess: (blob, variables) => saveReport(blob, variables.runId, variables.format),
    onError: (_error, variables) => setReportError({
      runId: variables.runId,
      message: t('parity.error.report'),
    }),
  })
  const { reset: resetManualMutation } = manualMutation
  const { reset: resetAcceptMutation } = acceptMutation
  const { reset: resetReportMutation } = reportMutation

  useEffect(() => {
    setRunDraft({ runId: selectedRunId, manualNotes: {}, acceptanceNote: '' })
    setReportError(null)
    resetManualMutation()
    resetAcceptMutation()
    resetReportMutation()
  }, [selectedRunId, resetAcceptMutation, resetManualMutation, resetReportMutation])

  const caseTitles = useMemo(
    () => new Map(catalogueQuery.data?.cases.map((item) => [item.case_id, item.title]) ?? []),
    [catalogueQuery.data],
  )
  const run = runQuery.data
  const approvedRoots = approvedRoot.trim() ? [approvedRoot.trim()] : []
  const corpusResult = corpusInspection
    && corpusInspection.request.manifest_path === manifestPath.trim()
    && corpusInspection.request.approved_roots.length === approvedRoots.length
    && corpusInspection.request.approved_roots.every((root, index) => root === approvedRoots[index])
    ? corpusInspection.result
    : null
  const migrationResult = migrationInspection
    && migrationInspection.request.source === migrationSource.trim()
    && migrationInspection.request.copied_source_confirmed === copiedSourceConfirmed
    && migrationInspection.request.approved_roots.length === approvedRoots.length
    && migrationInspection.request.approved_roots.every((root, index) => root === approvedRoots[index])
    ? migrationInspection.result
    : null
  const activeDraft = runDraft.runId === selectedRunId
    ? runDraft
    : { runId: selectedRunId, manualNotes: {}, acceptanceNote: '' }
  const corpusCounts = useMemo(() => {
    const counts: Record<AssetReadiness, number> = {
      ready: 0,
      missing: 0,
      checksum_mismatch: 0,
      unsupported: 0,
      unsafe_path: 0,
    }
    Object.values(corpusResult?.assets_by_role ?? {}).forEach((asset) => {
      counts[asset.status] += 1
    })
    return counts
  }, [corpusResult])
  const migrationTotals = useMemo(() => {
    const result = migrationResult
    if (!result) return null
    const candidates = MIGRATION_GROUPS.flatMap((key) => result[key])
    return {
      importable: candidates.length,
      relink: result.assets.filter((asset) => asset.state === 'missing').length,
      unsafe: result.assets.filter((asset) => asset.state === 'unsafe').length,
      unsupported: result.unsupported.length,
      warnings: result.warnings.length + candidates.reduce(
        (total, candidate: MigrationCandidate) => total + candidate.warnings.length,
        0,
      ),
    }
  }, [migrationResult])

  const refresh = async () => {
    setCommandMessage('')
    const requests: Array<Promise<unknown>> = [catalogueQuery.refetch(), runsQuery.refetch()]
    if (selectedRunId) requests.push(runQuery.refetch())
    await Promise.all(requests)
  }

  const requestReport = (format: ReportFormat) => {
    if (run) reportMutation.mutate({ runId: run.run_id, format })
  }

  return (
    <div className="parity-page">
      <header className="workspace-heading parity-heading">
        <div>
          <span className="workspace-kicker">{t('parity.kicker')}</span>
          <h1>{t('parity.title')}</h1>
          <p>{t('parity.subtitle')}</p>
        </div>
        <Link className="btn" to="/settings">{t('parity.back')}</Link>
      </header>

      <section className="parity-section" aria-labelledby="parity-source-title">
        <div className="parity-section-header">
          <div>
            <h2 id="parity-source-title">{t('parity.source.title')}</h2>
            <p>{t('parity.source.detail')}</p>
          </div>
        </div>
        <div className="parity-source-grid">
          <div className="field">
            <label htmlFor="parity-manifest">{t('parity.source.manifest')}</label>
            <input
              id="parity-manifest"
              type="text"
              value={manifestPath}
              onChange={(event) => setManifestPath(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="parity-root">{t('parity.source.root')}</label>
            <input
              id="parity-root"
              type="text"
              value={approvedRoot}
              onChange={(event) => setApprovedRoot(event.target.value)}
            />
          </div>
          <button
            className="btn"
            type="button"
            disabled={!manifestPath.trim() || approvedRoots.length === 0 || corpusMutation.isPending}
            onClick={() => corpusMutation.mutate({
              manifest_path: manifestPath.trim(),
              approved_roots: approvedRoots,
            })}
          >
            {t('parity.corpus.inspect')}
          </button>
        </div>
        {corpusMutation.isError
          && corpusMutation.variables?.manifest_path === manifestPath.trim()
          && <ErrorState>{t('parity.error.corpus')}</ErrorState>}
        {corpusResult && (
          <div className="parity-result-block" aria-live="polite">
            <div className="parity-totals">
              <span className="ready">{corpusCounts.ready} {t('parity.total.ready')}</span>
              <span className="missing">{corpusCounts.missing} {t('parity.total.missing')}</span>
              <span className="checksum_mismatch">{corpusCounts.checksum_mismatch} {t('parity.total.mismatch')}</span>
              <span className="unsupported">{corpusCounts.unsupported} {t('parity.total.unsupported')}</span>
              <span className="unsafe_path">{corpusCounts.unsafe_path} {t('parity.total.unsafe')}</span>
            </div>
            <p className="parity-root-summary">
              <strong>{t('parity.source.selectedRoot')}:</strong>{' '}
              {corpusInspection?.request.approved_roots.join(', ')}
            </p>
            <div className="parity-asset-list">
              {Object.values(corpusResult.assets_by_role).map((asset) => (
                <div key={asset.role}>
                  <strong>{asset.role}</strong>
                  <StatusLabel status={asset.status} />
                  {asset.findings.map((finding) => <span key={finding.code}>{finding.message}</span>)}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="parity-section" aria-labelledby="parity-migration-title">
        <div className="parity-section-header">
          <div>
            <h2 id="parity-migration-title">{t('parity.migration.title')}</h2>
            <p>{t('parity.migration.detail')}</p>
          </div>
        </div>
        <div className="parity-source-grid migration">
          <div className="field">
            <label htmlFor="parity-migration-source">{t('parity.migration.source')}</label>
            <input
              id="parity-migration-source"
              type="text"
              value={migrationSource}
              onChange={(event) => setMigrationSource(event.target.value)}
            />
          </div>
          <label className="parity-confirmation" htmlFor="parity-copied-confirmation">
            <input
              id="parity-copied-confirmation"
              type="checkbox"
              checked={copiedSourceConfirmed}
              onChange={(event) => setCopiedSourceConfirmed(event.target.checked)}
            />
            {t('parity.migration.confirm')}
          </label>
          <button
            className="btn"
            type="button"
            disabled={
              !migrationSource.trim()
              || approvedRoots.length === 0
              || !copiedSourceConfirmed
              || migrationMutation.isPending
            }
            onClick={() => migrationMutation.mutate({
              source: migrationSource.trim(),
              approved_roots: approvedRoots,
              copied_source_confirmed: copiedSourceConfirmed,
            })}
          >
            {t('parity.migration.inspect')}
          </button>
        </div>
        {migrationMutation.isError
          && migrationMutation.variables?.source === migrationSource.trim()
          && <ErrorState>{t('parity.error.migration')}</ErrorState>}
        {migrationTotals && (
          <div className="parity-result-block" aria-live="polite">
            <div className="parity-totals migration">
              <span className="ready">{migrationTotals.importable} {t('parity.total.importable')}</span>
              <span className="missing">{migrationTotals.relink} {t('parity.total.relink')}</span>
              <span className="unsafe_path">{migrationTotals.unsafe} {t('parity.total.unsafe')}</span>
              <span className="unsupported">{migrationTotals.unsupported} {t('parity.total.notSupported')}</span>
              <span className="warning">{migrationTotals.warnings} {t('parity.total.warnings')}</span>
            </div>
            {migrationResult?.unsupported.map((finding) => (
              <p className="parity-finding" key={`${finding.source}:${finding.reason}`}>
                <strong>{finding.source}</strong>: {finding.reason}
              </p>
            ))}
          </div>
        )}
      </section>

      <section className="parity-section" aria-labelledby="parity-runs-title">
        <div className="parity-section-header run-controls">
          <div>
            <h2 id="parity-runs-title">{t('parity.runs.title')}</h2>
            <p>{t('parity.runs.detail')}</p>
          </div>
          <div className="parity-actions">
            <button
              className="btn accent"
              type="button"
              disabled={!manifestPath.trim() || approvedRoots.length === 0 || startMutation.isPending}
              onClick={() => startMutation.mutate({
                manifest_path: manifestPath.trim(),
                approved_roots: approvedRoots,
              })}
            >
              {t('parity.run.start')}
            </button>
            <button
              className="btn danger"
              type="button"
              disabled={!run || run.status !== 'running' || cancelMutation.isPending}
              onClick={() => run && cancelMutation.mutate(run.task_id)}
            >
              {t('parity.run.cancel')}
            </button>
            <button className="btn" type="button" onClick={() => void refresh()}>
              {t('parity.refresh')}
            </button>
          </div>
        </div>
        <div className="parity-run-selector">
          <label htmlFor="parity-run-select">{t('parity.runs.select')}</label>
          <select
            id="parity-run-select"
            value={selectedRunId}
            onChange={(event) => setSelectedRunId(event.target.value)}
          >
            {!selectedRunId && <option value="">{t('parity.runs.none')}</option>}
            {(runsQuery.data?.runs ?? []).map((item) => (
              <option key={item.run_id} value={item.run_id}>
                {item.run_id} - {t(`parity.status.${item.status}`)}
              </option>
            ))}
          </select>
          {run && <StatusLabel status={run.status} />}
        </div>
        {runsQuery.isError && <ErrorState>{t('parity.error.runs')}</ErrorState>}
        {runQuery.isError && <ErrorState>{t('parity.error.run')}</ErrorState>}
        {startMutation.isError && <ErrorState>{t('parity.error.start')}</ErrorState>}
        {cancelMutation.isError && <ErrorState>{t('parity.error.cancel')}</ErrorState>}
        {commandMessage && <p className="parity-command-message" role="status">{commandMessage}</p>}

        {run && (
          <div className="parity-run-body">
            <div className="parity-report-row">
              <span>{run.run_id}</span>
              <div className="parity-actions">
                <button className="btn" type="button" onClick={() => requestReport('json')}>
                  {t('parity.report.json')}
                </button>
                <button className="btn" type="button" onClick={() => requestReport('markdown')}>
                  {t('parity.report.markdown')}
                </button>
              </div>
            </div>
            {reportError?.runId === run.run_id && <ErrorState>{reportError.message}</ErrorState>}
            {catalogueQuery.isError && <ErrorState>{t('parity.error.catalogue')}</ErrorState>}

            <div className="parity-case-list">
              {run.case_results.map((result) => {
                const title = caseTitles.get(result.case_id)
                return (
                  <details className="parity-case" key={result.case_id}>
                    <summary>
                      <span>
                        <strong>{title ?? result.case_id}</strong>
                        {title && <small>{result.case_id}</small>}
                      </span>
                      <StatusLabel status={result.status} />
                    </summary>
                    <div className="parity-case-detail">
                      <table>
                        <thead>
                          <tr>
                            <th>{t('parity.case.check')}</th>
                            <th>{t('parity.case.status')}</th>
                            <th>{t('parity.case.finding')}</th>
                            <th>{t('parity.case.measurements')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.checks.map((check) => (
                            <tr key={check.check_id}>
                              <td>{check.check_id}</td>
                              <td><StatusLabel status={check.status} /></td>
                              <td>{check.message}</td>
                              <td>
                                {Object.entries(check.measurements).length === 0 ? (
                                  <span className="parity-empty">{t('parity.none')}</span>
                                ) : Object.entries(check.measurements).map(([key, value]) => (
                                  <span className="parity-measurement" key={key}>
                                    <strong>{key}</strong> {renderValue(value)}
                                  </span>
                                ))}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )
              })}
            </div>

            <div className="parity-manual-section">
              <h3>{t('parity.manual.title')}</h3>
              {run.manual_items.length === 0 && <p>{t('parity.manual.none')}</p>}
              {run.manual_items.map((item) => {
                const answer = run.manual_answers[item.item_id]
                const note = activeDraft.manualNotes[item.item_id] ?? answer?.note ?? ''
                return (
                  <fieldset className="parity-manual-item" aria-label={item.prompt} key={item.item_id}>
                    <legend>{item.prompt}</legend>
                    <span className="parity-manual-requirement">
                      {item.required ? t('parity.required') : t('parity.optional')}
                    </span>
                    {answer && (
                      <p className={answer.accepted ? 'accepted' : 'rejected'}>
                        {t('parity.manual.recorded')}: {answer.accepted
                          ? t('parity.status.pass')
                          : t('parity.status.fail')}
                      </p>
                    )}
                    <div className="field">
                      <label htmlFor={`manual-note-${item.item_id}`}>{t('parity.note')}</label>
                      <input
                        id={`manual-note-${item.item_id}`}
                        type="text"
                        value={note}
                        onChange={(event) => setRunDraft((current) => ({
                          runId: run.run_id,
                          manualNotes: {
                            ...(current.runId === run.run_id ? current.manualNotes : {}),
                            [item.item_id]: event.target.value,
                          },
                          acceptanceNote: current.runId === run.run_id
                            ? current.acceptanceNote
                            : '',
                        }))}
                      />
                    </div>
                    <div className="parity-actions">
                      <button
                        className="btn accent"
                        type="button"
                        disabled={!note.trim() || manualMutation.isPending || run.acceptance !== null}
                        onClick={() => manualMutation.mutate({
                          runId: run.run_id,
                          itemId: item.item_id,
                          accepted: true,
                          note: note.trim(),
                        })}
                      >
                        {t('parity.status.pass')}
                      </button>
                      <button
                        className="btn danger"
                        type="button"
                        disabled={!note.trim() || manualMutation.isPending || run.acceptance !== null}
                        onClick={() => manualMutation.mutate({
                          runId: run.run_id,
                          itemId: item.item_id,
                          accepted: false,
                          note: note.trim(),
                        })}
                      >
                        {t('parity.status.fail')}
                      </button>
                    </div>
                  </fieldset>
                )
              })}
              {manualMutation.isError
                && manualMutation.variables?.runId === run.run_id
                && <ErrorState>{t('parity.error.manual')}</ErrorState>}
            </div>

            <div className="parity-acceptance">
              <div>
                <h3>{t('parity.acceptance.title')}</h3>
                <p>{run.acceptance
                  ? t('parity.acceptance.complete')
                  : run.ready_for_acceptance
                    ? t('parity.acceptance.ready')
                    : t('parity.acceptance.blocked')}
                </p>
              </div>
              <div className="field">
                <label htmlFor="parity-acceptance-note">{t('parity.acceptance.note')}</label>
                <input
                  id="parity-acceptance-note"
                  type="text"
                  value={activeDraft.acceptanceNote}
                  disabled={run.acceptance !== null}
                  onChange={(event) => setRunDraft((current) => ({
                    runId: run.run_id,
                    manualNotes: current.runId === run.run_id ? current.manualNotes : {},
                    acceptanceNote: event.target.value,
                  }))}
                />
              </div>
              <button
                className="btn accent"
                type="button"
                disabled={
                  !run.ready_for_acceptance
                  || !activeDraft.acceptanceNote.trim()
                  || manualMutation.isPending
                  || acceptMutation.isPending
                  || run.acceptance !== null
                }
                onClick={() => acceptMutation.mutate({
                  runId: run.run_id,
                  note: activeDraft.acceptanceNote.trim(),
                })}
              >
                {t('parity.acceptance.action')}
              </button>
              {acceptMutation.isError
                && acceptMutation.variables?.runId === run.run_id
                && <ErrorState>{t('parity.error.acceptance')}</ErrorState>}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

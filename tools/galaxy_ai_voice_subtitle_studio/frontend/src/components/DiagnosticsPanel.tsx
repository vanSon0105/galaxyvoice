import { useEffect, useRef, useState } from 'react'

import {
  auditOperation,
  fetchCapabilities,
  fetchDiagnosticLogs,
  fetchSystemReport,
  type CapabilityDescriptor,
  type OperationAudit,
  type SystemReport,
} from '../api/reliability'

interface DiagnosticsPanelProps {
  open: boolean
  onClose: () => void
  onSetupComplete?: () => void
}

const formatSize = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`

export function DiagnosticsPanel({ open, onClose, onSetupComplete }: DiagnosticsPanelProps) {
  const panelRef = useRef<HTMLElement>(null)
  const [report, setReport] = useState<SystemReport | null>(null)
  const [capabilities, setCapabilities] = useState<CapabilityDescriptor[]>([])
  const [capabilityId, setCapabilityId] = useState('')
  const [device, setDevice] = useState('auto')
  const [audit, setAudit] = useState<OperationAudit | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setBusy(true)
    setError('')
    void Promise.all([fetchSystemReport(), fetchCapabilities(), fetchDiagnosticLogs(120)])
      .then(([nextReport, nextCapabilities, diagnosticLog]) => {
        setReport(nextReport)
        setCapabilities(nextCapabilities)
        setLogs(diagnosticLog.lines)
        const next = nextCapabilities[0]
        setCapabilityId(next?.capability_id || '')
        setDevice(next?.default_device || next?.devices[0] || 'auto')
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(false))
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab' || !panelRef.current) return
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), select:not([disabled]), input:not([disabled]), a[href], summary, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute('hidden'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  const selected = capabilities.find((item) => item.capability_id === capabilityId)
  if (!open) return null

  const runAudit = async () => {
    if (!capabilityId) return
    setBusy(true)
    setError('')
    try {
      const outputPath = report?.disks[0]?.path ?? ''
      const result = await auditOperation(capabilityId, device, {
        output_path: outputPath,
        required_disk_bytes: 512 * 1024 * 1024,
      })
      setAudit(result)
      if (result.ready && result.disk?.ready) onSetupComplete?.()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside ref={panelRef} className="diagnostics-panel" role="dialog" aria-label="Chẩn đoán hệ thống" aria-modal="true">
      <header>
        <div>
          <strong>Chẩn đoán</strong>
          <span>Phần cứng, runtime và log gần nhất</span>
        </div>
        <button className="icon-btn" aria-label="Đóng chẩn đoán" onClick={onClose} autoFocus>×</button>
      </header>

      {error && <p className="diagnostics-error" role="alert">{error}</p>}
      {busy && <progress className="diagnostics-loading" aria-label="Đang kiểm tra" />}

      {report && (
        <section className="diagnostics-summary" aria-label="Thông tin máy">
          <div><span>CPU</span><strong>{report.cpu_count} luồng</strong></div>
          <div><span>RAM</span><strong>{report.total_memory_bytes ? formatSize(report.total_memory_bytes) : 'Không rõ'}</strong></div>
          <div><span>CUDA</span><strong>{report.cuda_device_count || 'Không có'}</strong></div>
          <div><span>Khuyên dùng</span><strong>{report.recommended_device.toUpperCase()}</strong></div>
        </section>
      )}

      <section className="diagnostics-section">
        <h2>Kiểm tra tác vụ</h2>
        <div className="diagnostics-controls">
          <label>
            Runtime
            <select value={capabilityId} onChange={(event) => {
              const nextId = event.target.value
              const next = capabilities.find((item) => item.capability_id === nextId)
              setCapabilityId(nextId)
              setDevice(next?.default_device || next?.devices[0] || 'auto')
              setAudit(null)
            }}>
              {capabilities.map((item) => <option key={item.capability_id} value={item.capability_id}>{item.label}</option>)}
            </select>
          </label>
          <label>
            Thiết bị
            <select value={device} onChange={(event) => setDevice(event.target.value)}>
              {(selected?.devices ?? ['auto', 'cpu']).map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}
            </select>
          </label>
          <button className="btn primary" disabled={busy || !capabilityId} onClick={() => void runAudit()}>Kiểm tra</button>
        </div>
        {audit && (
          <div className={`audit-result ${audit.state}`}>
            <strong>{audit.ready ? 'Có thể chạy' : 'Chưa thể chạy'}</strong>
            <span>Thiết bị: {audit.resolved_device || 'không rõ'}</span>
            {audit.recommended_model_id && <span>Model đề xuất: {audit.recommended_model_id}</span>}
            {audit.checks.map((check) => (
              <p key={`${check.code}-${check.message}`} className={check.state}>
                {check.message}{check.remediation ? ` ${check.remediation}` : ''}
              </p>
            ))}
          </div>
        )}
      </section>

      {report?.disks.length ? (
        <section className="diagnostics-section">
          <h2>Dung lượng</h2>
          {report.disks.map((disk) => <p key={disk.path}>{disk.message}</p>)}
        </section>
      ) : null}

      <details className="diagnostics-section">
        <summary>Log gần nhất ({logs.length})</summary>
        <pre>{logs.length ? logs.join('\n') : 'Chưa có log.'}</pre>
      </details>
    </aside>
  )
}

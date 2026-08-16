import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { exportDraft, fetchDraft, openPath, updateDraft } from '../../api/voice'
import type { DraftPayload, ExportResult } from '../../api/voice'
import { fetchSettings } from '../../api/settings'
import { useT } from '../../i18n/useT'

interface DraftEditorProps {
  taskId: string
  currentVideoPath: string
}

/** Editable draft SRT (Sub gốc / Sub dịch) + export, mirroring the tkinter draft flow. */
export function DraftEditor({ taskId, currentVideoPath }: DraftEditorProps) {
  const t = useT()
  const draftQuery = useQuery({ queryKey: ['draft', taskId], queryFn: () => fetchDraft(taskId) })
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })

  const [sourceSrt, setSourceSrt] = useState('')
  const [translatedSrt, setTranslatedSrt] = useState('')
  const [exportDir, setExportDir] = useState('')
  const [exportName, setExportName] = useState('')
  const [status, setStatus] = useState('')
  const [exportResult, setExportResult] = useState<ExportResult | null>(null)
  const [exportError, setExportError] = useState('')

  useEffect(() => {
    const draft = draftQuery.data
    if (!draft) return
    setSourceSrt(draft.source_srt)
    setTranslatedSrt(draft.translated_srt ?? '')
    setExportName(draft.project_name)
  }, [draftQuery.data])

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings) return
    const dir = String(settings.output_dir ?? '')
    if (dir && !exportDir) setExportDir(dir)
  }, [settingsQuery.data, exportDir])

  if (draftQuery.isPending) return <div className="section-card">{t('ws.connecting')}</div>
  if (!draftQuery.data) return <div className="section-card">{t('settings.loadError')}</div>

  const draft: DraftPayload = draftQuery.data

  const handleSave = async () => {
    try {
      await updateDraft(taskId, { source_srt: sourceSrt, translated_srt: translatedSrt || undefined })
      setStatus(t('settings.saved'))
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }

  const handleExport = async () => {
    setExportError('')
    setExportResult(null)
    const normalize = (path: string) => path.replace(/\\/g, '/').toLowerCase()
    if (
      currentVideoPath.trim() &&
      normalize(currentVideoPath.trim()) !== normalize(draftQuery.data?.source_video ?? '')
    ) {
      setExportError('Bản phụ đề hiện tại thuộc video khác. Hãy tạo phụ đề cho video đang chọn trước khi export.')
      return
    }
    try {
      const result = await exportDraft(taskId, {
        output_dir: exportDir,
        project_name: exportName,
      })
      setExportResult(result)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Phụ đề nháp</h2>
        <div className="field-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <div className="field">
            <label>Sub gốc</label>
            <textarea
              className="srt-editor"
              rows={14}
              value={sourceSrt}
              onChange={(event) => setSourceSrt(event.target.value)}
              spellCheck={false}
            />
          </div>
          {draft.translated_srt !== null && (
            <div className="field">
              <label>Sub dịch</label>
              <textarea
                className="srt-editor"
                rows={14}
                value={translatedSrt}
                onChange={(event) => setTranslatedSrt(event.target.value)}
                spellCheck={false}
              />
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10 }}>
          <button className="btn" onClick={() => void handleSave()}>
            Lưu sửa
          </button>
          <span style={{ color: 'var(--color-fg-subtle)', fontSize: 12 }}>{status}</span>
          <span style={{ color: 'var(--color-fg-subtle)', fontSize: 12 }}>
            {draft.warnings.length > 0 ? `Cảnh báo: ${draft.warnings.join('; ')}` : ''}
          </span>
        </div>
      </section>

      <section className="section-card">
        <h2 className="section-title">Xuất gói phụ đề</h2>
        <div className="field-grid">
          <div className="field">
            <label>Thư mục xuất</label>
            <input type="text" value={exportDir} onChange={(event) => setExportDir(event.target.value)} />
          </div>
          <div className="field">
            <label>Tên project</label>
            <input type="text" value={exportName} onChange={(event) => setExportName(event.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <button className="btn accent" onClick={() => void handleExport()}>
            Xuất phụ đề
          </button>
          {exportError && (
            <span style={{ color: 'var(--color-danger)', fontSize: 12 }}>{exportError}</span>
          )}
        </div>
        {exportResult && (
          <div className="result-list" style={{ marginTop: 10 }}>
            <div>{exportResult.audio_path}</div>
            <div>{exportResult.source_srt_path}</div>
            {exportResult.translated_srt_path && <div>{exportResult.translated_srt_path}</div>}
            <button className="btn" onClick={() => void openPath(exportResult.project_dir)}>
              Mở thư mục
            </button>
          </div>
        )}
      </section>
    </div>
  )
}

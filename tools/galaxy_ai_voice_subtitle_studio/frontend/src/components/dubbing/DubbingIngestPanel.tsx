import { useState, type DragEvent } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchDubbingIngestMeta,
  ingestLocalDubbingMedia,
  startDubbingUrlIngest,
  type DubbingCaptionArtifact,
  type DubbingIngestResult,
} from '../../api/workspaces'
import { pickCookieFile, pickMediaFile } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'
import { TaskButton } from '../TaskButton'

interface DubbingIngestPanelProps {
  galaxyProjectId: string
  sourceLanguage: string
  targetLanguage: string
  outputDir: string
  currentSourcePath: string
  onIngest: (result: DubbingIngestResult) => void
  onUseCaption: (caption: DubbingCaptionArtifact, target: 'source' | 'translation') => void
  onTranscribe: (mediaPath: string) => void
}

type NativeDropFile = File & { pywebviewFullPath?: string; path?: string }

export function DubbingIngestPanel({
  galaxyProjectId,
  sourceLanguage,
  targetLanguage,
  outputDir,
  currentSourcePath,
  onIngest,
  onUseCaption,
  onTranscribe,
}: DubbingIngestPanelProps) {
  const metaQuery = useQuery({ queryKey: ['dubbing-ingest-meta'], queryFn: fetchDubbingIngestMeta })
  const [url, setUrl] = useState('')
  const [cookiePath, setCookiePath] = useState('')
  const [pullCaptions, setPullCaptions] = useState(true)
  const [dragActive, setDragActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [lastResult, setLastResult] = useState<DubbingIngestResult | null>(null)

  const applyResult = (result: DubbingIngestResult) => {
    setLastResult(result)
    onIngest(result)
    const captionMessage = result.captions.length
      ? `Đã nhập ${result.source_name} cùng ${result.captions.length} caption.`
      : `Đã nhập ${result.source_name}. Chưa có caption.`
    setMessage(result.warnings.length ? `${captionMessage} ${result.warnings.join(' ')}` : captionMessage)
  }

  const importLocal = async (path: string) => {
    setBusy(true)
    setMessage('')
    try {
      applyResult(await ingestLocalDubbingMedia({
        media_path: path,
        source_language: sourceLanguage,
        target_language: targetLanguage,
      }))
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const chooseLocal = async () => {
    const path = await pickMediaFile()
    if (path) await importLocal(path)
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragActive(false)
    const file = event.dataTransfer.files[0] as NativeDropFile | undefined
    const path = file?.pywebviewFullPath || file?.path || ''
    if (!path) {
      setMessage('Trình duyệt không cung cấp đường dẫn native. Hãy dùng nút Chọn media.')
      return
    }
    void importLocal(path)
  }

  const startUrlIngest = async () => {
    const activeCookiePath = cookiePath
    const response = await startDubbingUrlIngest({
      galaxy_project_id: galaxyProjectId,
      url,
      output_dir: outputDir,
      pull_captions: pullCaptions,
      source_language: sourceLanguage,
      target_language: targetLanguage,
      cookie_path: activeCookiePath,
    })
    setCookiePath('')
    return response.task_id
  }

  const finishUrlIngest = (task: TaskState) => {
    if (task.status === 'done' && task.result) applyResult(task.result as DubbingIngestResult)
    else if (task.error) setMessage(task.error)
  }

  const adapter = metaQuery.data?.url_adapter
  const formats = [
    ...(metaQuery.data?.video_extensions ?? ['.mp4', '.mov', '.mkv', '.webm']),
    ...(metaQuery.data?.audio_extensions ?? ['.mp3', '.wav', '.flac', '.m4a']),
  ].map((item) => item.slice(1).toUpperCase()).join(' · ')
  const captionSource = lastResult?.captions ?? []
  const asrPath = lastResult?.source_path || currentSourcePath

  return <section className="section-card dubbing-ingest-panel">
    <div className="section-header">
      <div><span className="workspace-kicker">MEDIA SOURCE</span><h2 className="section-title">Media cần lồng tiếng</h2></div>
      {asrPath && <button className="btn" type="button" onClick={() => onTranscribe(asrPath)}>Phiên âm bằng Whisper</button>}
    </div>

    <div className="dubbing-ingest-layout">
      <div
        className={`dubbing-drop-zone${dragActive ? ' active' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragActive(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <span className="dubbing-upload-mark" aria-hidden="true">↑</span>
        <strong>Thả video hoặc audio vào đây</strong>
        <small>{formats}</small>
        {currentSourcePath && <span className="dubbing-current-source" title={currentSourcePath}>{currentSourcePath.replace(/\\/g, '/').split('/').pop()}</span>}
        <button className="btn accent" type="button" disabled={busy} onClick={() => void chooseLocal()}>{busy ? 'Đang đọc...' : 'Chọn media'}</button>
      </div>

      <div className="dubbing-url-ingest">
        <div className="field"><label>Video URL</label><div className="input-action"><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="YouTube hoặc URL video công khai" /><TaskButton label="Nhập URL" variant="accent" disabled={!url.trim() || !adapter?.available} onStart={startUrlIngest} onFinish={finishUrlIngest} /></div></div>
        <div className="dubbing-url-options">
          <label className="field-check"><input type="checkbox" checked={pullCaptions} onChange={(event) => setPullCaptions(event.target.checked)} /><span>Lấy caption và bản dịch tự động</span></label>
          <div className="dubbing-cookie-control"><span>{cookiePath ? 'Cookie đã chọn cho lượt tải này' : 'Cookie Netscape (tùy chọn)'}</span><button className="btn quiet" type="button" onClick={() => void pickCookieFile().then((path) => path && setCookiePath(path))}>Chọn cookie</button>{cookiePath && <button className="btn quiet" type="button" aria-label="Bỏ cookie" onClick={() => setCookiePath('')}>×</button>}</div>
        </div>
        {adapter && <p className={`field-hint${adapter.available ? '' : ' danger'}`}>{adapter.message}</p>}
      </div>
    </div>

    {message && <div className="workspace-message" role="status">{message}</div>}
    {captionSource.length > 0 && <div className="dubbing-caption-artifacts">
      <span>Caption đã lấy</span>
      {captionSource.map((caption) => <div key={caption.path} className="dubbing-caption-row"><strong>{caption.language || 'und'}</strong><small title={caption.path}>{caption.path.replace(/\\/g, '/').split('/').pop()}</small><button className="btn quiet" type="button" onClick={() => onUseCaption(caption, 'source')}>Dùng làm sub gốc</button><button className="btn quiet" type="button" onClick={() => onUseCaption(caption, 'translation')}>Dùng làm bản dịch</button></div>)}
    </div>}
  </section>
}

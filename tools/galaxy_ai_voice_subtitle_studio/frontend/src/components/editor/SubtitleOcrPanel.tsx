import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { EditorMedia } from '../../api/editor'
import {
  fetchVideoOcrMeta,
  installVideoOcr,
  startVideoOcr,
  type VideoOcrRegion,
  type VideoOcrResult,
} from '../../api/videoOcr'
import { openPath } from '../../api/voice'
import type { TaskState } from '../../ws/useTasks'
import { TaskButton } from '../TaskButton'
import { sameMediaPath } from './ocrCleanup'

const DEFAULT_REGION: VideoOcrRegion = { x: 5, y: 68, width: 90, height: 27 }

interface SubtitleOcrPanelProps {
  galaxyProjectId: string
  source: EditorMedia | null
  outputDir: string
  onCompleted: (result: VideoOcrResult) => void
  onAccept?: (result: VideoOcrResult, targetTrackId: string) => void
  subtitleTracks?: Array<{ id: string; name: string }>
  region?: VideoOcrRegion
  onRegionChange?: (region: VideoOcrRegion) => void
  embedded?: boolean
}

function clampRegion(region: VideoOcrRegion): VideoOcrRegion {
  const width = Math.max(1, Math.min(100, Math.round(region.width)))
  const height = Math.max(1, Math.min(100, Math.round(region.height)))
  return {
    x: Math.max(0, Math.min(100 - width, Math.round(region.x))),
    y: Math.max(0, Math.min(100 - height, Math.round(region.y))),
    width,
    height,
  }
}

export function SubtitleOcrPanel({
  galaxyProjectId,
  source,
  outputDir,
  onCompleted,
  onAccept,
  subtitleTracks = [],
  region: controlledRegion,
  onRegionChange,
  embedded = false,
}: SubtitleOcrPanelProps) {
  const metaQuery = useQuery({ queryKey: ['video-ocr-meta'], queryFn: fetchVideoOcrMeta })
  const dragRef = useRef<{ type: 'move' | 'resize'; x: number; y: number; region: VideoOcrRegion } | null>(null)
  const [localRegion, setLocalRegion] = useState(DEFAULT_REGION)
  const [mode, setMode] = useState<'fast' | 'accurate'>('fast')
  const [language, setLanguage] = useState('vi')
  const [projectName, setProjectName] = useState('')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<VideoOcrResult | null>(null)
  const [reviewCues, setReviewCues] = useState<VideoOcrResult['cues']>([])
  const [targetTrackId, setTargetTrackId] = useState('')
  const sourceName = source?.name ?? ''
  const sourcePath = source?.path ?? ''
  const region = controlledRegion ?? localRegion
  const setRegion = (next: VideoOcrRegion) => {
    const bounded = clampRegion(next)
    if (onRegionChange) onRegionChange(bounded)
    else setLocalRegion(bounded)
  }

  useEffect(() => {
    setProjectName(sourceName ? `${sourceName.replace(/\.[^.]+$/, '')}-ocr` : '')
    setResult(null)
    setReviewCues([])
    setMessage('')
  }, [sourceName, sourcePath])

  useEffect(() => {
    if (!subtitleTracks.some((track) => track.id === targetTrackId)) {
      setTargetTrackId(subtitleTracks[0]?.id ?? '')
    }
  }, [subtitleTracks, targetTrackId])

  const matchesCurrentSource = (candidate: string) => sameMediaPath(candidate, sourcePath)

  const beginDrag = (event: React.PointerEvent<HTMLDivElement>, type: 'move' | 'resize') => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { type, x: event.clientX, y: event.clientY, region }
  }

  const moveRegion = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    const bounds = event.currentTarget.closest('.editor-removal-stage')?.getBoundingClientRect()
    if (!drag || !bounds?.width || !bounds.height) return
    const dx = (event.clientX - drag.x) * 100 / bounds.width
    const dy = (event.clientY - drag.y) * 100 / bounds.height
    setRegion(clampRegion(drag.type === 'move'
      ? { ...drag.region, x: drag.region.x + dx, y: drag.region.y + dy }
      : { ...drag.region, width: drag.region.width + dx, height: drag.region.height + dy }))
  }

  const start = async () => {
    if (!source) throw new Error('Chọn một clip video trên timeline.')
    if (!outputDir.trim()) throw new Error('Chọn thư mục xuất trong phần Xuất video.')
    if (!metaQuery.data?.runtime_ready) throw new Error('Runtime OCR local chưa được cài.')
    setResult(null)
    setMessage('Đã gửi tác vụ nhận dạng phụ đề cháy.')
    return (await startVideoOcr({
      galaxy_project_id: galaxyProjectId,
      video_path: source.path,
      output_dir: outputDir,
      project_name: projectName,
      mode,
      language,
      region,
    })).task_id
  }

  const finish = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      const completed = task.result as VideoOcrResult
      if (!matchesCurrentSource(completed.source_video_path)) {
        setResult(null)
        setReviewCues([])
        setMessage('Kết quả OCR thuộc clip khác nên chưa được áp dụng. Hãy chọn lại clip đó để chạy OCR.')
        return
      }
      setResult(completed)
      setReviewCues(completed.cues)
      onCompleted(completed)
      setMessage(`Đã nhận dạng ${completed.cues.length} câu và thêm SRT vào Tệp phương tiện.`)
    } else if (task.status === 'cancelled') {
      setMessage('Đã dừng nhận dạng phụ đề.')
    } else if (task.status === 'failed') {
      setMessage(task.error ?? 'Nhận dạng phụ đề thất bại.')
    }
  }

  if (!source) return <div className="editor-removal-empty">Chọn một clip video trên timeline</div>

  return <div className="editor-removal-tool editor-ocr-tool">
    {!embedded && <div className="editor-removal-stage" style={{ aspectRatio: `${source.width || 16}/${source.height || 9}` }}>
      <video controls preload="metadata" src={source.url} />
      <div
        className="removal-region active editor-ocr-region"
        style={{ left: `${region.x}%`, top: `${region.y}%`, width: `${region.width}%`, height: `${region.height}%` }}
        onPointerDown={(event) => beginDrag(event, 'move')}
        onPointerMove={moveRegion}
        onPointerUp={() => { dragRef.current = null }}
        onPointerCancel={() => { dragRef.current = null }}
      >
        <span>Vùng OCR</span>
        <div
          className="region-resize"
          onPointerDown={(event) => { event.stopPropagation(); beginDrag(event, 'resize') }}
          onPointerMove={moveRegion}
          onPointerUp={() => { dragRef.current = null }}
          onPointerCancel={() => { dragRef.current = null }}
        />
      </div>
    </div>}
    {!embedded && <div className="editor-removal-source" title={source.path}>
      <strong>{source.name}</strong><span>{source.width}×{source.height}</span>
    </div>}
    <div className="field-grid editor-ocr-options">
      <div className="field"><label htmlFor="editor-ocr-mode">Chế độ OCR</label><select id="editor-ocr-mode" value={mode} onChange={(event) => setMode(event.target.value as 'fast' | 'accurate')}>{(metaQuery.data?.modes ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></div>
      <div className="field"><label htmlFor="editor-ocr-language">Ngôn ngữ</label><select id="editor-ocr-language" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="vi">Tiếng Việt</option><option value="en">English</option><option value="ch">中文 / English</option><option value="japan">日本語</option></select></div>
    </div>
    {!embedded && <div className="field-grid editor-removal-region-fields">
      {(['x', 'y', 'width', 'height'] as const).map((key) => <div className="field" key={key}>
        <label>{{ x: 'X (%)', y: 'Y (%)', width: 'Rộng (%)', height: 'Cao (%)' }[key]}</label>
        <input type="number" min={key === 'x' || key === 'y' ? 0 : 1} max="100" value={region[key]} onChange={(event) => setRegion(clampRegion({ ...region, [key]: Number(event.target.value) }))} />
      </div>)}
    </div>}
    {!embedded && <div className="field"><label htmlFor="editor-ocr-project">Tên kết quả</label><input id="editor-ocr-project" value={projectName} onChange={(event) => setProjectName(event.target.value)} /></div>}
    {!metaQuery.data?.runtime_ready && <div className="editor-ocr-runtime">
      <span>OCR chạy local, cần cài một lần trước khi dùng.</span>
      <TaskButton label="Cài OCR local" disabled={!metaQuery.data?.installer_available} onStart={async () => (await installVideoOcr()).task_id} onFinish={(task) => {
        if (task.status === 'done') { setMessage('Runtime OCR đã sẵn sàng.'); void metaQuery.refetch() }
        else if (task.status === 'failed') setMessage(task.error ?? 'Cài OCR thất bại.')
      }} />
    </div>}
    <div className="editor-removal-actions">
      <TaskButton label="Nhận dạng phụ đề" variant="accent" disabled={!metaQuery.data?.runtime_ready} onStart={start} onFinish={finish} />
      {result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}
    </div>
    {message && <p className="action-message editor-removal-message">{message}</p>}
    {result && <div className="editor-ocr-stats"><span>{result.sampled_frames} mẫu</span><span>{result.probe_runs ?? 0} đoạn hình</span><span>{result.ocr_frames} frame OCR</span><span>{result.reused_frames} frame dùng lại</span>{Boolean(result.rescue_frames) && <span>{result.rescue_frames} frame cứu hộ</span>}{result.cache_hit && <span>Cache</span>}</div>}
    {result && <div className="editor-ocr-review">
      <div className="editor-ocr-review-header">
        <div><strong>Duyệt kết quả OCR</strong><small>Sửa nội dung hoặc mốc thời gian trước khi đưa vào timeline.</small></div>
        <label>Line phụ đề<select aria-label="Line phụ đề đích" value={targetTrackId} onChange={(event) => setTargetTrackId(event.target.value)}>{subtitleTracks.map((track) => <option key={track.id} value={track.id}>{track.name}</option>)}</select></label>
      </div>
      <div className="editor-ocr-cue-list">
        {reviewCues.map((cue, index) => <div className={`editor-ocr-cue${cue.confidence < 0.7 ? ' low-confidence' : ''}`} key={`${cue.index}:${index}`}>
          <span className="editor-ocr-cue-index">{index + 1}</span>
          <input aria-label={`Bắt đầu câu ${index + 1}`} type="number" min="0" step="0.1" value={(cue.start_ms / 1_000).toFixed(1)} onChange={(event) => setReviewCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, start_ms: Math.max(0, Math.round(Number(event.target.value) * 1_000)) } : item))} />
          <input aria-label={`Kết thúc câu ${index + 1}`} type="number" min="0" step="0.1" value={(cue.end_ms / 1_000).toFixed(1)} onChange={(event) => setReviewCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, end_ms: Math.max(item.start_ms + 1, Math.round(Number(event.target.value) * 1_000)) } : item))} />
          <input aria-label={`Nội dung câu ${index + 1}`} value={cue.text} onChange={(event) => setReviewCues((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item))} />
          <span title="Độ tin cậy OCR">{Math.round(cue.confidence * 100)}%</span>
        </div>)}
      </div>
      <button className="btn accent" disabled={!onAccept || !targetTrackId || !reviewCues.length} onClick={() => {
        if (!matchesCurrentSource(result.source_video_path)) {
          setMessage('Clip đang chọn không còn khớp với kết quả OCR.')
          return
        }
        onAccept?.({ ...result, cues: reviewCues }, targetTrackId)
        setMessage(`Đã đưa ${reviewCues.length} câu OCR đã duyệt vào timeline.`)
      }}>Đưa SRT đã duyệt vào timeline</button>
    </div>}
  </div>
}

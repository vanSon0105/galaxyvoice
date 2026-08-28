import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import {
  createTranscriptHandoff,
  deleteTranscriptProject,
  fetchTranscriptProject,
  fetchTranscriptProjects,
  importMediaForTranscription,
  importTextTranscript,
  saveTranscriptDocument,
  transcriptExportUrl,
  transcriptMediaUrl,
  transcriptSpeakerReferenceUrl,
  type TranscriptCue,
  type TranscriptProject,
  type TranscriptSpeaker,
} from '../../api/transcripts'
import { importLibraryAudio } from '../../api/voiceLibrary'
import { WorkspaceLoading, WorkspaceState } from '../../components/WorkspaceState'
import { pickMediaFile } from '../../lib/dialogs'
import { useTasks } from '../../ws/useTasks'
import { isTaskActive } from '../../ws/types'
import { useVoiceProject } from './VoiceProjectContext'

const ROW_HEIGHT = 108
const ROW_BUFFER = 6
const EMPTY_PROJECTS: TranscriptProject[] = []

function formatMs(ms: number) {
  const safe = Math.max(0, Math.round(ms))
  const hours = Math.floor(safe / 3_600_000)
  const minutes = Math.floor((safe % 3_600_000) / 60_000)
  const seconds = Math.floor((safe % 60_000) / 1000)
  const millis = safe % 1000
  return `${hours ? `${String(hours).padStart(2, '0')}:` : ''}${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`
}

function parseTime(value: string): number | null {
  const parts = value.trim().replace(',', '.').split(':')
  if (parts.length < 2 || parts.length > 3) return null
  const seconds = Number(parts.pop())
  const minutes = Number(parts.pop())
  const hours = parts.length ? Number(parts[0]) : 0
  if (![hours, minutes, seconds].every(Number.isFinite) || minutes < 0 || seconds < 0) return null
  return Math.round((hours * 3600 + minutes * 60 + seconds) * 1000)
}

function cloneDocument(cues: TranscriptCue[], speakers: TranscriptSpeaker[]) {
  return {
    cues: cues.map((cue) => ({ ...cue, words: cue.words.map((word) => ({ ...word })) })),
    speakers: speakers.map((speaker) => ({ ...speaker })),
  }
}

export function TranscriptsPage() {
  const { projectId } = useVoiceProject()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { tasks } = useTasks()
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [activeTaskId, setActiveTaskId] = useState('')
  const [composer, setComposer] = useState<'none' | 'media' | 'text'>('none')
  const [message, setMessage] = useState('')
  const activeTask = tasks.find((task) => task.taskId === activeTaskId)

  const listQuery = useQuery({
    queryKey: ['transcript-projects', projectId, query],
    queryFn: () => fetchTranscriptProjects(projectId, query),
  })
  const projects = listQuery.data ?? EMPTY_PROJECTS
  const detailQuery = useQuery({
    queryKey: ['transcript-project', selectedId],
    queryFn: () => fetchTranscriptProject(selectedId),
    enabled: Boolean(selectedId),
  })

  useEffect(() => {
    if (!selectedId && projects[0]) setSelectedId(projects[0].transcript_id)
  }, [projects, selectedId])

  useEffect(() => {
    if (!activeTask || isTaskActive(activeTask.status)) return
    void queryClient.invalidateQueries({ queryKey: ['transcript-projects'] })
    if (activeTask.status === 'done' && activeTask.result) {
      const result = activeTask.result as TranscriptProject
      setSelectedId(result.transcript_id)
      setMessage('Phiên âm đã hoàn tất.')
    } else if (activeTask.error) {
      setMessage(activeTask.error)
    }
    setActiveTaskId('')
  }, [activeTask, queryClient])

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['transcript-projects'] })
    await queryClient.invalidateQueries({ queryKey: ['transcript-project'] })
  }
  const deleteMutation = useMutation({
    mutationFn: deleteTranscriptProject,
    onSuccess: async () => {
      setSelectedId('')
      await refresh()
      setMessage('Đã xóa transcript.')
    },
  })

  return <div className="transcripts-native-page">
    <section className="library-toolbar">
      <div className="library-search"><label htmlFor="transcript-search">Tìm transcript</label><input id="transcript-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tên, nội dung hoặc người nói" /></div>
      <div className="library-toolbar-actions"><button className="btn accent" type="button" disabled={!projectId} onClick={() => setComposer(composer === 'media' ? 'none' : 'media')}>Phiên âm media</button><button className="btn" type="button" disabled={!projectId} onClick={() => setComposer(composer === 'text' ? 'none' : 'text')}>Nhập SRT / văn bản</button></div>
    </section>

    {!projectId && <div className="library-message" role="status">Chọn hoặc tạo một Galaxy Project trước khi nhập transcript.</div>}
    {composer === 'media' && <ImportMediaPanel projectId={projectId} onClose={() => setComposer('none')} onStarted={(taskId) => { setActiveTaskId(taskId); setComposer('none'); setMessage('Đang phiên âm trong nền...') }} />}
    {composer === 'text' && <ImportTextPanel projectId={projectId} onClose={() => setComposer('none')} onCreated={async (project) => { await refresh(); setSelectedId(project.transcript_id); setComposer('none'); setMessage('Đã nhập transcript.') }} />}
    {message && <div className="library-message" role="status">{message}<button type="button" onClick={() => setMessage('')}>Đóng</button></div>}

    <div className="transcripts-layout">
      <section className="transcripts-list-panel">
        <div className="section-header compact"><h2 className="section-title">Bản ghi</h2><span className="studio-counter">{projects.length}</span></div>
        {listQuery.isPending ? <WorkspaceLoading label="Đang đọc transcript..." /> : listQuery.isError ? <WorkspaceState tone="error" title="Không đọc được transcript" action={<button className="btn" onClick={() => void listQuery.refetch()}>Thử lại</button>} /> : projects.length === 0 ? <WorkspaceState title="Chưa có bản phiên âm" description="Phiên âm audio/video hoặc nhập nội dung có sẵn." /> : <div className="transcript-project-list">{projects.map((item) => <div key={item.transcript_id} role="button" tabIndex={0} className={`transcript-project-row${selectedId === item.transcript_id ? ' active' : ''}`} onClick={() => setSelectedId(item.transcript_id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setSelectedId(item.transcript_id) }}><span className="transcript-project-copy"><strong>{item.name}</strong><small>{item.source_kind.toUpperCase()} · {item.detected_language || item.requested_language} · {item.cue_count} cue</small></span><button className="btn danger quiet" type="button" aria-label={`Xóa ${item.name}`} onClick={(event) => { event.stopPropagation(); if (window.confirm(`Xóa transcript "${item.name}"?`)) deleteMutation.mutate(item.transcript_id) }}>×</button></div>)}</div>}
      </section>

      <section className="transcripts-editor-panel">
        {detailQuery.isPending ? <WorkspaceLoading label="Đang mở transcript..." /> : detailQuery.isError ? <WorkspaceState tone="error" title="Không mở được transcript" action={<button className="btn" onClick={() => void detailQuery.refetch()}>Thử lại</button>} /> : detailQuery.data ? <TranscriptEditor key={`${detailQuery.data.transcript_id}:${detailQuery.data.revision}`} project={detailQuery.data} onSaved={refresh} onMessage={setMessage} onHandoff={async (target) => { const payload = await createTranscriptHandoff(detailQuery.data!.transcript_id, target); const pathname = target === 'dubbing' ? '/voice/dubbing' : '/voice/longform'; const search = new URLSearchParams({ transcript: payload.transcript_id }); if (payload.handoff_id) search.set('handoff', payload.handoff_id); navigate(`${pathname}?${search.toString()}`, { state: { transcriptHandoff: payload } }) }} /> : <WorkspaceState title="Chọn một transcript" description="Cue, timing và người nói sẽ hiện ở đây." />}
      </section>
    </div>
  </div>
}

function ImportMediaPanel({ projectId, onClose, onStarted }: { projectId: string; onClose: () => void; onStarted: (taskId: string) => void }) {
  const [mediaPath, setMediaPath] = useState('')
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('auto')
  const [modelSize, setModelSize] = useState('base')
  const [device, setDevice] = useState('auto')
  const [diarization, setDiarization] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submit = async () => {
    setSubmitting(true); setError('')
    try {
      if (!mediaPath) throw new Error('Hãy chọn file audio hoặc video.')
      const result = await importMediaForTranscription({ project_id: projectId, media_path: mediaPath, name: name || undefined, language, model_size: modelSize, device, diarization })
      onStarted(result.task_id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) } finally { setSubmitting(false) }
  }
  return <section className="section-card library-composer">
    <div className="section-header compact"><div><span className="workspace-kicker">Faster Whisper</span><h2 className="section-title">Phiên âm audio / video</h2></div><button className="btn quiet" onClick={onClose}>Đóng</button></div>
    <div className="field-grid">
      <div className="field field-wide"><label>Media nguồn</label><div className="input-action"><input value={mediaPath} onChange={(event) => setMediaPath(event.target.value)} /><button className="btn" onClick={() => void pickMediaFile().then((path) => { if (!path) return; setMediaPath(path); setName(path.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? '') })}>Chọn</button></div></div>
      <div className="field"><label>Tên bản ghi</label><input value={name} onChange={(event) => setName(event.target.value)} /></div>
      <div className="field"><label>Ngôn ngữ</label><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="auto">Tự nhận diện</option><option value="vi">Tiếng Việt</option><option value="en">English</option><option value="zh">中文</option><option value="ja">日本語</option><option value="ko">한국어</option></select></div>
      <div className="field"><label>Model Whisper</label><select value={modelSize} onChange={(event) => setModelSize(event.target.value)}>{['tiny', 'base', 'small', 'medium', 'large-v3'].map((model) => <option key={model}>{model}</option>)}</select></div>
      <div className="field"><label>Thiết bị</label><select value={device} onChange={(event) => setDevice(event.target.value)}><option value="auto">Tự động</option><option value="cuda">NVIDIA CUDA</option><option value="cpu">CPU</option></select></div>
      <label className="field-check"><input type="checkbox" checked={diarization} onChange={(event) => setDiarization(event.target.checked)} /><span>Phân tách người nói bằng pyannote</span></label>
    </div>
    {diarization && <p className="field-hint">Cài requirements-diarization.txt, đặt GALAXY_HF_TOKEN và cấp quyền model. Nếu thiếu, transcript vẫn được tạo để gán người nói thủ công.</p>}
    {error && <div className="studio-error">{error}</div>}
    <div className="composer-actions"><button className="btn accent" disabled={submitting || !mediaPath} onClick={() => void submit()}>{submitting ? 'Đang gửi...' : 'Bắt đầu phiên âm'}</button></div>
  </section>
}

function ImportTextPanel({ projectId, onClose, onCreated }: { projectId: string; onClose: () => void; onCreated: (project: TranscriptProject) => void }) {
  const [name, setName] = useState('')
  const [formatType, setFormatType] = useState<'srt' | 'vtt' | 'txt'>('srt')
  const [language, setLanguage] = useState('vi')
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submit = async () => {
    setSubmitting(true); setError('')
    try { onCreated(await importTextTranscript({ project_id: projectId, name: name || 'Transcript', content, format_type: formatType, language })) }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setSubmitting(false) }
  }
  return <section className="section-card library-composer">
    <div className="section-header compact"><div><span className="workspace-kicker">Nguồn có sẵn</span><h2 className="section-title">Nhập phụ đề hoặc văn bản</h2></div><button className="btn quiet" onClick={onClose}>Đóng</button></div>
    <div className="field-grid"><div className="field"><label>Tên</label><input value={name} onChange={(event) => setName(event.target.value)} /></div><div className="field"><label>Định dạng</label><select value={formatType} onChange={(event) => setFormatType(event.target.value as 'srt' | 'vtt' | 'txt')}><option value="srt">SRT</option><option value="vtt">WebVTT</option><option value="txt">Văn bản, mỗi dòng một cue</option></select></div><div className="field"><label>Ngôn ngữ</label><input value={language} onChange={(event) => setLanguage(event.target.value)} /></div><div className="field field-wide"><label>Nội dung</label><textarea rows={7} value={content} onChange={(event) => setContent(event.target.value)} placeholder="Dán nội dung SRT, VTT hoặc text tại đây..." /></div></div>
    {error && <div className="studio-error">{error}</div>}<div className="composer-actions"><button className="btn accent" disabled={submitting || !content.trim()} onClick={() => void submit()}>{submitting ? 'Đang lưu...' : 'Lưu transcript'}</button></div>
  </section>
}

interface DocumentSnapshot { cues: TranscriptCue[]; speakers: TranscriptSpeaker[] }

function TranscriptEditor({ project, onSaved, onMessage, onHandoff }: { project: TranscriptProject; onSaved: () => Promise<void>; onMessage: (message: string) => void; onHandoff: (target: 'dubbing' | 'longform') => Promise<void> }) {
  const initial = cloneDocument(project.cues ?? [], project.speakers)
  const [document, setDocument] = useState<DocumentSnapshot>(initial)
  const [undo, setUndo] = useState<DocumentSnapshot[]>([])
  const [redo, setRedo] = useState<DocumentSnapshot[]>([])
  const [selectedCueId, setSelectedCueId] = useState(initial.cues[0]?.cue_id ?? '')
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(520)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const apply = (next: DocumentSnapshot) => {
    setUndo((items) => [...items.slice(-49), cloneDocument(document.cues, document.speakers)])
    setRedo([]); setDocument(next); setDirty(true)
  }
  const stepUndo = () => {
    const previous = undo.at(-1); if (!previous) return
    setRedo((items) => [...items, cloneDocument(document.cues, document.speakers)])
    setUndo((items) => items.slice(0, -1)); setDocument(previous); setDirty(true)
  }
  const stepRedo = () => {
    const next = redo.at(-1); if (!next) return
    setUndo((items) => [...items, cloneDocument(document.cues, document.speakers)])
    setRedo((items) => items.slice(0, -1)); setDocument(next); setDirty(true)
  }

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    setViewportHeight(element.clientHeight || 520)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setViewportHeight(element.clientHeight))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      if (event.key.toLowerCase() === 'z') { event.preventDefault(); if (event.shiftKey) stepRedo(); else stepUndo() }
      if (event.key.toLowerCase() === 'y') { event.preventDefault(); stepRedo() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  })

  const updateCue = (cueId: string, changes: Partial<TranscriptCue>) => apply({ ...document, cues: document.cues.map((cue) => cue.cue_id === cueId ? { ...cue, ...changes } : cue) })
  const moveCue = (cueId: string, delta: number) => {
    const index = document.cues.findIndex((cue) => cue.cue_id === cueId); const target = index + delta
    if (index < 0 || target < 0 || target >= document.cues.length) return
    const cues = [...document.cues]; const [moved] = cues.splice(index, 1); cues.splice(target, 0, moved)
    apply({ ...document, cues: cues.map((cue, position) => ({ ...cue, position })) })
  }
  const splitCue = (cueId: string) => {
    const index = document.cues.findIndex((cue) => cue.cue_id === cueId); const cue = document.cues[index]; if (!cue) return
    const splitAt = Math.max(1, Math.floor(cue.text.length / 2)); const space = cue.text.indexOf(' ', splitAt); const textAt = space > 0 ? space : splitAt
    const splitMs = cue.start_ms + Math.round((cue.end_ms - cue.start_ms) / 2)
    const firstWords = cue.words.filter((word) => (word.start_ms + word.end_ms) / 2 < splitMs); const secondWords = cue.words.filter((word) => (word.start_ms + word.end_ms) / 2 >= splitMs)
    const cues = [...document.cues]; cues.splice(index, 1, { ...cue, end_ms: splitMs, text: cue.text.slice(0, textAt).trim(), words: firstWords }, { ...cue, cue_id: crypto.randomUUID(), start_ms: splitMs, text: cue.text.slice(textAt).trim(), words: secondWords })
    apply({ ...document, cues: cues.map((item, position) => ({ ...item, position })) })
  }
  const mergeNext = (cueId: string) => {
    const index = document.cues.findIndex((cue) => cue.cue_id === cueId); const cue = document.cues[index]; const next = document.cues[index + 1]
    if (!cue || !next) return
    const cues = [...document.cues]; cues.splice(index, 2, { ...cue, end_ms: Math.max(cue.end_ms, next.end_ms), text: `${cue.text} ${next.text}`.trim(), words: [...cue.words, ...next.words] })
    apply({ ...document, cues: cues.map((item, position) => ({ ...item, position })) })
  }
  const deleteCue = (cueId: string) => {
    if (document.cues.length <= 1) { onMessage('Transcript phải còn ít nhất một cue.'); return }
    apply({ ...document, cues: document.cues.filter((cue) => cue.cue_id !== cueId).map((cue, position) => ({ ...cue, position })) })
  }
  const addSpeaker = () => {
    const index = document.speakers.length + 1
    apply({ ...document, speakers: [...document.speakers, { speaker_id: `speaker-${crypto.randomUUID()}`, label: `Người nói ${index}`, color: '#7db196' }] })
  }
  const save = async () => {
    setSaving(true)
    try { await saveTranscriptDocument(project.transcript_id, { cues: document.cues, speakers: document.speakers, expected_revision: project.revision }); setDirty(false); setUndo([]); setRedo([]); await onSaved(); onMessage('Đã lưu transcript.') }
    catch (cause) { onMessage(cause instanceof Error ? cause.message : String(cause)) }
    finally { setSaving(false) }
  }
  const handoff = async (target: 'dubbing' | 'longform') => {
    if (dirty) { onMessage('Hãy lưu thay đổi trước khi chuyển workspace.'); return }
    try { await onHandoff(target) } catch (cause) { onMessage(cause instanceof Error ? cause.message : String(cause)) }
  }

  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - ROW_BUFFER)
  const endIndex = Math.min(document.cues.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + ROW_BUFFER)
  const selected = document.cues.find((cue) => cue.cue_id === selectedCueId)

  return <div className="transcript-editor-container">
    <header className="transcript-editor-header"><div><span className="workspace-kicker">Revision {project.revision} · {project.detected_language || project.requested_language}</span><h2>{project.name}</h2><small>{project.model_id} · {project.resolved_device || project.requested_device} · {document.cues.length} cue</small></div><div className="transcript-header-actions"><button className="btn" disabled={!undo.length} onClick={stepUndo}>Hoàn tác</button><button className="btn" disabled={!redo.length} onClick={stepRedo}>Làm lại</button><button className="btn accent" disabled={!dirty || saving} onClick={() => void save()}>{saving ? 'Đang lưu...' : 'Lưu'}</button></div></header>
    {project.warnings.length > 0 && <div className="transcript-warning" role="status">{project.warnings.join(' · ')}</div>}
    <MediaTimeline project={project} cues={document.cues} selectedCueId={selectedCueId} onSelect={setSelectedCueId} />
    <section className="transcript-speaker-panel"><div className="section-header compact"><h3 className="section-title">Người nói</h3><button className="btn quiet" onClick={addSpeaker}>Thêm</button></div><div className="transcript-speakers-list">{document.speakers.map((speaker) => <SpeakerEditor key={speaker.speaker_id} speaker={speaker} project={project} onCommit={(label) => apply({ ...document, speakers: document.speakers.map((item) => item.speaker_id === speaker.speaker_id ? { ...item, label } : item) })} onMessage={onMessage} />)}</div></section>
    <div className="transcript-edit-toolbar"><span>{selected ? `Đang chọn cue #${selected.position + 1}` : 'Chọn một cue để thao tác'}</span><button className="btn" disabled={!selected} onClick={() => selected && moveCue(selected.cue_id, -1)}>Lên</button><button className="btn" disabled={!selected} onClick={() => selected && moveCue(selected.cue_id, 1)}>Xuống</button><button className="btn" disabled={!selected} onClick={() => selected && splitCue(selected.cue_id)}>Tách</button><button className="btn" disabled={!selected || selected.position >= document.cues.length - 1} onClick={() => selected && mergeNext(selected.cue_id)}>Gộp cue sau</button><button className="btn danger" disabled={!selected} onClick={() => selected && deleteCue(selected.cue_id)}>Xóa</button></div>
    <div ref={scrollRef} className="transcript-cue-scroll virtual" onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}><div className="transcript-cue-virtual-space" style={{ height: document.cues.length * ROW_HEIGHT }}><div style={{ transform: `translateY(${startIndex * ROW_HEIGHT}px)` }}>{document.cues.slice(startIndex, endIndex).map((cue) => <CueRow key={cue.cue_id} cue={cue} speakers={document.speakers} selected={cue.cue_id === selectedCueId} onSelect={() => setSelectedCueId(cue.cue_id)} onChange={(changes) => updateCue(cue.cue_id, changes)} />)}</div></div></div>
    <footer className="transcript-export-bar"><span>{dirty ? 'Có thay đổi chưa lưu' : 'Đã đồng bộ'}</span>{(['srt', 'vtt', 'txt'] as const).map((format) => dirty ? <button key={format} className="btn" disabled title="Lưu thay đổi trước khi xuất">{format.toUpperCase()}</button> : <a key={format} className="btn" href={transcriptExportUrl(project.transcript_id, format)}>{format.toUpperCase()}</a>)}<button className="btn" onClick={() => void handoff('longform')}>Đưa sang Truyện & Sách nói</button><button className="btn accent" onClick={() => void handoff('dubbing')}>Đưa sang Dubbing</button></footer>
  </div>
}

function SpeakerEditor({ speaker, project, onCommit, onMessage }: { speaker: TranscriptSpeaker; project: TranscriptProject; onCommit: (label: string) => void; onMessage: (message: string) => void }) {
  const [label, setLabel] = useState(speaker.label)
  useEffect(() => setLabel(speaker.label), [speaker.label])
  return <div className="transcript-speaker-editor" style={{ borderLeftColor: speaker.color }}><input value={label} onChange={(event) => setLabel(event.target.value)} onBlur={() => { const normalized = label.trim() || speaker.label; setLabel(normalized); if (normalized !== speaker.label) onCommit(normalized) }} />{speaker.reference_path && <><audio controls preload="none" src={transcriptSpeakerReferenceUrl(project.transcript_id, speaker.speaker_id)} /><button className="btn quiet" onClick={() => { if (!window.confirm(`Xác nhận bạn có quyền sử dụng giọng của ${label}?`)) return; void importLibraryAudio({ name: label, source: 'cloned', language: project.detected_language || project.requested_language, audio_path: speaker.reference_path!, consent: { confirmed: true, basis: 'owner_or_permission', statement: 'Xác nhận khi trích từ transcript', provenance: project.source_path } }).then(() => onMessage(`Đã lưu ${label} vào Thư viện giọng.`)).catch((cause) => onMessage(cause instanceof Error ? cause.message : String(cause))) }}>Lưu giọng</button></>}</div>
}

function CueRow({ cue, speakers, selected, onSelect, onChange }: { cue: TranscriptCue; speakers: TranscriptSpeaker[]; selected: boolean; onSelect: () => void; onChange: (changes: Partial<TranscriptCue>) => void }) {
  const [text, setText] = useState(cue.text)
  useEffect(() => setText(cue.text), [cue.text])
  return <div className={`transcript-cue-row${selected ? ' selected' : ''}`} style={{ height: ROW_HEIGHT - 8 }} onClick={onSelect}><div className="transcript-cue-meta"><span className="cue-index">#{cue.position + 1}</span><div className="cue-time-inputs"><input aria-label={`Bắt đầu cue ${cue.position + 1}`} defaultValue={formatMs(cue.start_ms)} onBlur={(event) => { const value = parseTime(event.target.value); if (value !== null && value < cue.end_ms && value !== cue.start_ms) onChange({ start_ms: value }) }} /><input aria-label={`Kết thúc cue ${cue.position + 1}`} defaultValue={formatMs(cue.end_ms)} onBlur={(event) => { const value = parseTime(event.target.value); if (value !== null && value > cue.start_ms && value !== cue.end_ms) onChange({ end_ms: value }) }} /></div><select value={cue.speaker_id} onChange={(event) => onChange({ speaker_id: event.target.value })}>{speakers.map((speaker) => <option key={speaker.speaker_id} value={speaker.speaker_id}>{speaker.label}</option>)}</select></div><textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} onBlur={() => { if (text !== cue.text) onChange({ text }) }} onClick={(event) => event.stopPropagation()} /><div className="cue-word-meta"><strong>{cue.words.length}</strong><span>từ có timing</span>{cue.confidence !== null && <small>{Math.round(cue.confidence * 100)}%</small>}</div></div>
}

function MediaTimeline({ project, cues, selectedCueId, onSelect }: { project: TranscriptProject; cues: TranscriptCue[]; selectedCueId: string; onSelect: (cueId: string) => void }) {
  const mediaRef = useRef<HTMLMediaElement | null>(null)
  const duration = Math.max(project.duration_ms, ...cues.map((cue) => cue.end_ms), 1)
  const stride = Math.max(1, Math.ceil(cues.length / 500))
  const visibleCues = cues.filter((cue, index) => index % stride === 0 || cue.cue_id === selectedCueId)
  const seek = (cue: TranscriptCue) => { onSelect(cue.cue_id); if (mediaRef.current) mediaRef.current.currentTime = cue.start_ms / 1000 }
  return <section className="transcript-media-panel"><div className="transcript-media-player">{project.source_kind === 'video' ? <video ref={(node) => { mediaRef.current = node }} controls preload="metadata" src={transcriptMediaUrl(project.transcript_id)} /> : project.source_kind === 'audio' ? <audio ref={(node) => { mediaRef.current = node }} controls preload="metadata" src={transcriptMediaUrl(project.transcript_id)} /> : <span>Transcript nhập từ văn bản, không có media nguồn.</span>}</div><div className="transcript-timeline" aria-label="Timeline transcript">{visibleCues.map((cue) => <button key={cue.cue_id} className={cue.cue_id === selectedCueId ? 'active' : ''} style={{ left: `${(cue.start_ms / duration) * 100}%`, width: `${Math.max(0.18, ((cue.end_ms - cue.start_ms) / duration) * 100)}%` }} title={`#${cue.position + 1} ${formatMs(cue.start_ms)}`} onClick={() => seek(cue)} />)}</div></section>
}

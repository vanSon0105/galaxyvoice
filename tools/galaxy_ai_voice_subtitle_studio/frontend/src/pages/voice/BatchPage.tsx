import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  batchCombinedAudioUrl,
  batchItemAudioUrl,
  batchManifestUrl,
  cancelTask,
  fetchBatchRun,
  fetchBatchRuns,
  parseBatchSource,
  pauseTask,
  resumeBatchRun,
  resumeTask,
  retryBatchRun,
  startBatchRun,
  type BatchItemInput,
  type BatchRun,
} from '../../api/batch'
import { fetchOmniVoiceStatus } from '../../api/omnivoice'
import { fetchSettings } from '../../api/settings'
import type { StudioVoiceSource } from '../../api/studio'
import { openPath } from '../../api/voice'
import { fetchLibraryVoices, libraryVoiceRequest } from '../../api/voiceLibrary'
import { WorkspaceLoading, WorkspaceState } from '../../components/WorkspaceState'
import { pickAudioFile, pickFolder } from '../../lib/dialogs'
import { useTasks } from '../../ws/useTasks'
import { isTaskActive } from '../../ws/types'
import { useVoiceProject } from './VoiceProjectContext'


const SOURCES: { value: StudioVoiceSource; label: string }[] = [
  { value: 'auto', label: 'Tự động' },
  { value: 'profile', label: 'Thư viện' },
  { value: 'reference', label: 'Audio mẫu' },
  { value: 'design', label: 'Thiết kế' },
]
const ACTIVE_RUN_STATUSES = new Set<BatchRun['status']>(['queued', 'running', 'paused'])

const emptyItem = (index: number): BatchItemInput => ({
  item_id: `voice-${String(index).padStart(3, '0')}`,
  text: '',
  language: '',
  speed: null,
  duration: null,
  voice_source: '',
  profile_id: '',
  instruction: '',
  formats: [],
})

function displayTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('vi-VN')
}

function statusLabel(status: BatchRun['status']) {
  return ({
    queued: 'Đang chờ', running: 'Đang chạy', paused: 'Tạm dừng', completed: 'Hoàn tất',
    partial: 'Một phần', failed: 'Thất bại', cancelled: 'Đã hủy', interrupted: 'Bị gián đoạn',
  } as const)[status]
}

export function BatchPage() {
  const { projectId, project } = useVoiceProject()
  const queryClient = useQueryClient()
  const { tasks } = useTasks()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const voicesQuery = useQuery({ queryKey: ['voice-library-picker'], queryFn: () => fetchLibraryVoices() })
  const [activeTaskId, setActiveTaskId] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState('')
  const activeTask = tasks.find((task) => task.taskId === activeTaskId)
  const runsQuery = useQuery({
    queryKey: ['batch-runs', projectId],
    queryFn: () => fetchBatchRuns(projectId),
    refetchInterval: (query) => {
      const runs = query.state.data as BatchRun[] | undefined
      return runs?.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) ? 1000 : false
    },
  })
  const selectedQuery = useQuery({
    queryKey: ['batch-run', selectedBatchId],
    queryFn: () => fetchBatchRun(selectedBatchId),
    enabled: Boolean(selectedBatchId),
    refetchInterval: (query) => {
      const run = query.state.data as BatchRun | undefined
      return run && ACTIVE_RUN_STATUSES.has(run.status) ? 1000 : false
    },
  })

  const [sourceText, setSourceText] = useState('')
  const [longForm, setLongForm] = useState(false)
  const [items, setItems] = useState<BatchItemInput[]>([])
  const [title, setTitle] = useState('Batch mới')
  const [outputDir, setOutputDir] = useState('')
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1)
  const [source, setSource] = useState<StudioVoiceSource>('auto')
  const [profileId, setProfileId] = useState('')
  const [referenceAudio, setReferenceAudio] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [instruction, setInstruction] = useState('')
  const [combine, setCombine] = useState(true)
  const [gapMs, setGapMs] = useState(250)
  const [exportWav, setExportWav] = useState(true)
  const [exportMp3, setExportMp3] = useState(true)
  const [parsing, setParsing] = useState(false)
  const [starting, setStarting] = useState(false)
  const [formError, setFormError] = useState('')
  const selectedLibraryVoice = (voicesQuery.data ?? []).find((voice) => voice.voice_id === profileId)
  const fileRef = useRef<HTMLInputElement>(null)
  const seeded = useRef(false)

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings || seeded.current) return
    seeded.current = true
    setOutputDir(String(settings.omnivoice_output_dir ?? settings.output_dir ?? ''))
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    setLanguage(String(settings.omnivoice_language ?? 'vi'))
    setSpeed(Number(settings.omnivoice_speed ?? 1))
  }, [settingsQuery.data])

  useEffect(() => {
    setSelectedBatchId('')
    setActiveTaskId('')
  }, [projectId])

  useEffect(() => {
    const first = runsQuery.data?.find((run) => run.project_id === projectId)
    if (!selectedBatchId && first) setSelectedBatchId(first.batch_id)
  }, [projectId, runsQuery.data, selectedBatchId])

  useEffect(() => {
    if (!activeTask || isTaskActive(activeTask.status)) return
    void queryClient.invalidateQueries({ queryKey: ['batch-runs'] })
    void queryClient.invalidateQueries({ queryKey: ['batch-run'] })
  }, [activeTask, queryClient])

  const selectedRun = selectedQuery.data ?? runsQuery.data?.find((run) => run.batch_id === selectedBatchId)
  const selectedTask = selectedRun ? tasks.find((task) => task.taskId === selectedRun.task_id) : undefined
  const controlTask = selectedTask ?? (activeTask?.taskId === selectedRun?.task_id ? activeTask : undefined)
  const controlTaskId = controlTask?.taskId ?? (
    selectedRun && ACTIVE_RUN_STATUSES.has(selectedRun.status) ? selectedRun.task_id : ''
  )
  const controlStatus = controlTask?.status ?? selectedRun?.status
  const active = Boolean(
    (controlTask && isTaskActive(controlTask.status))
    || (selectedRun && ACTIVE_RUN_STATUSES.has(selectedRun.status)),
  )
  const displayedRunStatus = controlStatus === 'paused' ? 'paused' : selectedRun?.status
  const parseItems = async () => {
    setFormError('')
    setParsing(true)
    try {
      const parsed = await parseBatchSource(sourceText, longForm)
      setItems(parsed)
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setParsing(false)
    }
  }

  const updateItem = (index: number, patch: Partial<BatchItemInput>) => {
    setItems((values) => values.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  }

  const start = async () => {
    setFormError('')
    setStarting(true)
    try {
      if (!projectId) throw new Error('Hãy chọn hoặc tạo một dự án trước khi chạy Batch.')
      if (!exportWav && !exportMp3) throw new Error('Chọn ít nhất một định dạng đầu ra.')
      if (source === 'profile' && !selectedLibraryVoice) throw new Error('Chọn một giọng tương thích trong thư viện.')
      if (source === 'reference' && !referenceAudio) throw new Error('Chọn audio tham chiếu.')
      if (source === 'design' && !instruction.trim()) throw new Error('Nhập mô tả giọng cần thiết kế.')
      const prepared = items.length ? items : await parseBatchSource(sourceText, longForm)
      const selectedRequest = selectedLibraryVoice ? libraryVoiceRequest(selectedLibraryVoice) : null
      const response = await startBatchRun({
        project_id: projectId,
        title: title.trim() || 'Batch mới',
        output_dir: outputDir,
        device,
        language,
        speed,
        formats: [exportWav ? 'wav' : null, exportMp3 ? 'mp3' : null].filter(Boolean) as ('wav' | 'mp3')[],
        voice: {
          source: source === 'profile' && selectedRequest ? selectedRequest.source : source,
          profile_id: source === 'profile' ? selectedRequest?.profile_id : profileId,
          reference_audio: source === 'profile' ? selectedRequest?.reference_audio : referenceAudio,
          reference_text: source === 'profile' ? selectedRequest?.reference_text : referenceText,
          instruction: source === 'profile' ? selectedRequest?.instruction : instruction,
        },
        combine,
        gap_ms: gapMs,
        items: prepared,
      })
      setItems(prepared)
      setActiveTaskId(response.task_id)
      setSelectedBatchId(response.batch_id)
      await queryClient.invalidateQueries({ queryKey: ['batch-runs'] })
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setStarting(false)
    }
  }

  const startExisting = async (operation: (batchId: string) => Promise<{ batch_id: string; task_id: string }>) => {
    if (!selectedRun) return
    try {
      const response = await operation(selectedRun.batch_id)
      setActiveTaskId(response.task_id)
      setSelectedBatchId(response.batch_id)
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const progress = selectedRun?.total_count
    ? Math.round(((selectedRun.completed_count + selectedRun.failed_count) / selectedRun.total_count) * 100)
    : 0

  return (
    <div className="batch-page">
      <div className="batch-layout">
        <main className="batch-compose">
          <section className="section-card studio-runtime-bar">
            <div><span className={`status-dot ${statusQuery.data?.installed ? 'open' : 'closed'}`} /><strong>OmniVoice Batch</strong><small>{statusQuery.data?.message ?? 'Đang kiểm tra runtime...'}</small></div>
            <span className="studio-counter">{items.length} mục</span>
          </section>

          <section className="section-card">
            <div className="section-header compact">
              <h2 className="section-title">Danh sách đầu vào</h2>
              <div className="batch-header-actions">
                <input ref={fileRef} hidden type="file" accept=".jsonl,.txt,application/json,text/plain" onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void file.text().then((text) => { setSourceText(text); setItems([]) })
                  event.target.value = ''
                }} />
                <button className="btn" type="button" onClick={() => fileRef.current?.click()}>Mở file</button>
                <button className="btn" type="button" disabled={parsing} onClick={() => void parseItems()}>{parsing ? 'Đang đọc...' : 'Phân tích'}</button>
              </div>
            </div>
            <textarea aria-label="Nguồn Batch" className="batch-source" value={sourceText} onChange={(event) => { setSourceText(event.target.value); setItems([]) }} placeholder={'Mỗi dòng là một nội dung hoặc JSONL: {"id":"intro","text":"Xin chào","language":"vi","speed":1.0}'} />
            <div className="batch-source-footer">
              <label><input type="checkbox" checked={longForm} onChange={(event) => setLongForm(event.target.checked)} /> Tách văn bản dài theo đoạn</label>
              <button className="btn quiet" type="button" onClick={() => setItems((values) => [...values, emptyItem(values.length + 1)])}>Thêm mục thủ công</button>
            </div>
          </section>

          {items.length > 0 && (
            <section className="section-card batch-item-editor">
              <div className="batch-item-grid batch-item-head"><span>ID</span><span>Nội dung</span><span>Ngôn ngữ</span><span>Tốc độ</span><span>Profile</span><span /></div>
              <div className="batch-item-scroll">
                {items.map((item, index) => (
                  <div className="batch-item-grid" key={`${item.item_id}-${index}`}>
                    <input value={item.item_id} onChange={(event) => updateItem(index, { item_id: event.target.value })} />
                    <textarea rows={2} value={item.text} onChange={(event) => updateItem(index, { text: event.target.value })} />
                    <input value={item.language} placeholder={language} onChange={(event) => updateItem(index, { language: event.target.value })} />
                    <input type="number" min={0.5} max={1.5} step={0.1} value={item.speed ?? ''} placeholder={String(speed)} onChange={(event) => updateItem(index, { speed: event.target.value ? Number(event.target.value) : null })} />
                    <select value={item.profile_id} onChange={(event) => updateItem(index, { profile_id: event.target.value, voice_source: event.target.value ? 'profile' : '' })}>
                      <option value="">Mặc định</option>
                      {(voicesQuery.data ?? []).filter((voice) => voice.selection.profile_id).map((voice) => <option key={voice.voice_id} value={voice.selection.profile_id}>{voice.name}</option>)}
                    </select>
                    <button className="btn danger" type="button" aria-label={`Xóa ${item.item_id}`} onClick={() => setItems((values) => values.filter((_, itemIndex) => itemIndex !== index))}>Xóa</button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="section-card">
            <h2 className="section-title">Thiết lập Batch</h2>
            <div className="field-grid">
              <div className="field"><label>Tên Batch</label><input value={title} onChange={(event) => setTitle(event.target.value)} /></div>
              <div className="field"><label>Ngôn ngữ mặc định</label><select value={language} onChange={(event) => setLanguage(event.target.value)}>{(statusQuery.data?.languages ?? ['vi']).map((code) => <option key={code}>{code}</option>)}</select></div>
              <div className="field field-wide"><label>Thư mục xuất</label><div className="input-action"><input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} /><button className="btn" type="button" onClick={() => void pickFolder().then((path) => path && setOutputDir(path))}>Chọn</button></div></div>
              <div className="field"><label>Thiết bị</label><select value={device} onChange={(event) => setDevice(event.target.value)}>{(statusQuery.data?.devices ?? []).map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}</select></div>
              <div className="field"><label>Tốc độ <output>{speed.toFixed(1)}x</output></label><input type="range" min={0.5} max={1.5} step={0.1} value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></div>
            </div>
            <div className="seg-control studio-source-tabs batch-source-tabs">
              {SOURCES.map((option) => <button key={option.value} type="button" className={`seg-item${source === option.value ? ' active' : ''}`} onClick={() => setSource(option.value)}>{option.label}</button>)}
            </div>
            {source === 'profile' && <div className="field batch-voice-field"><label>Giọng mặc định</label><select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">Chọn giọng</option>{(voicesQuery.data ?? []).map((voice) => <option key={voice.voice_id} value={voice.voice_id} disabled={!voice.compatibility.batch}>{voice.name} · {voice.language}{voice.compatibility.batch ? '' : ' · không tương thích'}</option>)}</select></div>}
            {source === 'reference' && <div className="field-grid batch-voice-field"><div className="field field-wide"><label>Audio tham chiếu</label><div className="input-action"><input value={referenceAudio} onChange={(event) => setReferenceAudio(event.target.value)} /><button className="btn" type="button" onClick={() => void pickAudioFile().then((path) => path && setReferenceAudio(path))}>Chọn</button></div></div><div className="field field-wide"><label>Transcript audio mẫu</label><textarea rows={2} value={referenceText} onChange={(event) => setReferenceText(event.target.value)} /></div></div>}
            {source === 'design' && <div className="field batch-voice-field"><label>Mô tả giọng</label><textarea rows={2} value={instruction} onChange={(event) => setInstruction(event.target.value)} /></div>}
            <div className="batch-output-row">
              <label><input type="checkbox" checked={combine} onChange={(event) => setCombine(event.target.checked)} /> Ghép đầu ra</label>
              <label>Khoảng nghỉ <input type="number" min={0} max={5000} value={gapMs} onChange={(event) => setGapMs(Number(event.target.value))} /> ms</label>
              <label><input type="checkbox" checked={exportWav} onChange={(event) => setExportWav(event.target.checked)} /> WAV</label>
              <label><input type="checkbox" checked={exportMp3} onChange={(event) => setExportMp3(event.target.checked)} /> MP3</label>
            </div>
          </section>

          {formError && <div className="studio-error">{formError}</div>}
          <div className="studio-generate-bar batch-run-bar">
            <button className="btn accent" type="button" disabled={active || starting || !projectId} onClick={() => void start()}>{starting ? 'Đang chuẩn bị...' : 'Chạy Batch'}</button>
            {(controlStatus === 'running' || controlStatus === 'queued') && controlTaskId && <button className="btn" type="button" onClick={() => void pauseTask(controlTaskId)}>Tạm dừng</button>}
            {controlStatus === 'paused' && controlTaskId && <button className="btn" type="button" onClick={() => void resumeTask(controlTaskId)}>Tiếp tục</button>}
            {active && controlTaskId && <button className="btn danger" type="button" onClick={() => void cancelTask(controlTaskId)}>Hủy</button>}
            <span>{projectId ? `Đang ghi vào ${project?.name ?? 'dự án hiện tại'}` : 'Chưa chọn dự án'}</span>
          </div>
        </main>

        <aside className="batch-results">
          <section className="section-card batch-current">
            <div className="section-header compact"><h2 className="section-title">Run đang chọn</h2>{displayedRunStatus && <span className={`batch-status ${displayedRunStatus}`}>{statusLabel(displayedRunStatus)}</span>}</div>
            {!selectedRun ? <WorkspaceState title="Chưa có Batch" /> : (
              <>
                <strong>{selectedRun.title}</strong><small>{selectedRun.completed_count}/{selectedRun.total_count} mục · {selectedRun.failed_count} lỗi</small>
                <div className="batch-progress"><span style={{ width: `${progress}%` }} /></div>
                {controlTask?.lines.at(-1) && <p className="batch-live-message">{controlTask.lines.at(-1)}</p>}
                {selectedRun.combined_wav_path && <audio controls preload="metadata" src={batchCombinedAudioUrl(selectedRun)} />}
                <div className="studio-result-actions">
                  <button className="btn" type="button" onClick={() => void openPath(selectedRun.root_dir)}>Mở thư mục</button>
                  <a className="btn" href={batchManifestUrl(selectedRun.batch_id)}>Manifest</a>
                  {selectedRun.combined_wav_path && <a className="btn" href={batchCombinedAudioUrl(selectedRun, 'wav', true)}>Tải WAV</a>}
                  {selectedRun.combined_mp3_path && <a className="btn" href={batchCombinedAudioUrl(selectedRun, 'mp3', true)}>Tải MP3</a>}
                  {selectedRun.status === 'partial' || selectedRun.status === 'failed' ? <button className="btn" type="button" disabled={active} onClick={() => void startExisting(retryBatchRun)}>Thử lại mục lỗi</button> : null}
                  {selectedRun.status === 'cancelled' || selectedRun.status === 'interrupted' ? <button className="btn" type="button" disabled={active} onClick={() => void startExisting(resumeBatchRun)}>Tiếp tục phần còn lại</button> : null}
                </div>
              </>
            )}
          </section>

          {selectedRun && <section className="section-card batch-item-results"><h2 className="section-title">Kết quả từng mục</h2><div className="batch-result-list">{selectedRun.items.map((item) => <article key={item.item_id} className={`batch-result-item ${item.status}`}><div><strong>{item.item_id}</strong><span>{item.status} · lần {item.attempts}</span></div><p>{item.text}</p>{item.error && <small>{item.error}</small>}{item.audio_url && <div><audio controls preload="none" src={batchItemAudioUrl(item)} /><a className="btn" href={batchItemAudioUrl(item, true)}>Tải</a></div>}</article>)}</div></section>}

          <section className="section-card batch-history">
            <div className="section-header compact"><h2 className="section-title">Lịch sử Batch</h2><span className="studio-counter">{runsQuery.data?.length ?? 0}</span></div>
            {runsQuery.isPending ? <WorkspaceLoading label="Đang đọc lịch sử..." /> : runsQuery.isError ? <WorkspaceState title="Không đọc được lịch sử" tone="error" /> : !runsQuery.data?.length ? <WorkspaceState title="Chưa có Batch" /> : <div className="batch-history-list">{runsQuery.data.map((run) => <button type="button" className={`batch-history-item${selectedBatchId === run.batch_id ? ' active' : ''}`} key={run.batch_id} onClick={() => setSelectedBatchId(run.batch_id)}><span><strong>{run.title}</strong><small>{displayTime(run.updated_at)}</small></span><span className={`batch-status ${run.status}`}>{statusLabel(run.status)}</span></button>)}</div>}
          </section>
        </aside>
      </div>
    </div>
  )
}

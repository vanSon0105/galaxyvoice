import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useSearchParams } from 'react-router-dom'

import { fetchSettings, fetchSettingsMeta, saveTranslationApiKey } from '../../api/settings'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import { openPath, taskFileUrl } from '../../api/voice'
import {
  deleteDubbingProject,
  dubbingProjectMediaUrl,
  fetchDubbingPlan,
  fetchDubbingProject,
  fetchDubbingProjects,
  fetchDubbingQuality,
  fetchResumeJobs,
  saveDubbingProject,
  startDubbingTranslation,
  startRender,
  type DubbingProject,
  type DubbingQualityReport,
  type DubbingSegment,
  type RenderResultPayload,
} from '../../api/workspaces'
import { fetchOmniVoiceStatus } from '../../api/omnivoice'
import { fetchTranscriptHandoff, type TranscriptHandoff } from '../../api/transcripts'
import { TaskButton } from '../../components/TaskButton'
import { pickAudioFile, pickFolder, pickVideoFile } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'

const STAGES = ['Nguồn', 'Bản dịch', 'Phân vai', 'Tổng hợp', 'Smart Fit', 'QC', 'Xuất']
const ROW_HEIGHT = 142
const VIEWPORT_HEIGHT = 620

export function DubbingPage() {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const handoffApplied = useRef('')
  const activeRenderProject = useRef('')
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const metaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const profilesQuery = useQuery({ queryKey: ['voice-library-picker'], queryFn: () => fetchLibraryVoices() })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const projectsQuery = useQuery({ queryKey: ['dubbing-projects'], queryFn: fetchDubbingProjects })

  const [projectId, setProjectId] = useState('')
  const [revision, setRevision] = useState(0)
  const [projectName, setProjectName] = useState('dubbing')
  const [sourceSrt, setSourceSrt] = useState('')
  const [translatedSrt, setTranslatedSrt] = useState('')
  const [segments, setSegments] = useState<DubbingSegment[]>([])
  const [quality, setQuality] = useState<DubbingQualityReport | null>(null)
  const [sourceVideo, setSourceVideo] = useState('')
  const [sourceAudio, setSourceAudio] = useState('')
  const [outputDir, setOutputDir] = useState('')
  const [device, setDevice] = useState('auto')
  const [sourceLanguage, setSourceLanguage] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [mixMode, setMixMode] = useState<'replace' | 'mix' | 'duck'>('replace')
  const [sourceVolume, setSourceVolume] = useState(0.25)
  const [dubVolume, setDubVolume] = useState(1)
  const [fitMin, setFitMin] = useState(0.8)
  const [fitMax, setFitMax] = useState(1.25)
  const [fitTolerance, setFitTolerance] = useState(120)
  const [exportMp3, setExportMp3] = useState(true)
  const [exportStems, setExportStems] = useState(true)
  const [resumeDir, setResumeDir] = useState('')
  const [result, setResult] = useState<RenderResultPayload | null>(null)
  const [resultTaskId, setResultTaskId] = useState('')
  const [dirty, setDirty] = useState(false)
  const [message, setMessage] = useState('')
  const [scrollTop, setScrollTop] = useState(0)

  function showError(cause: unknown) {
    setMessage(cause instanceof Error ? cause.message : String(cause))
  }

  useEffect(() => {
    const settings = settingsQuery.data
    const meta = metaQuery.data
    if (!settings || !meta) return
    setOutputDir((current) => current || String(settings.omnivoice_output_dir ?? settings.output_dir ?? ''))
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    if (!handoffApplied.current) setLanguage(String(settings.omnivoice_language ?? 'vi'))
    const initialProvider = String(settings.ai_provider ?? '').trim() || meta.default_translation_provider
    const providerInfo = meta.translation_providers.find((item) => item.code === initialProvider)
    setProvider((current) => current || initialProvider)
    setModel((current) => current || String(settings.ai_model ?? '').trim() || providerInfo?.default_model || '')
    setBaseUrl((current) => current || String(settings.ai_base_url ?? '').trim() || providerInfo?.default_base_url || '')
  }, [settingsQuery.data, metaQuery.data])

  useEffect(() => {
    let cancelled = false
    const applyHandoff = (handoff: TranscriptHandoff) => {
      if (cancelled || handoff.target !== 'dubbing' || handoffApplied.current === handoff.transcript_id) return
      handoffApplied.current = handoff.transcript_id
      setSourceSrt(handoff.srt_text ?? '')
      setTranslatedSrt('')
      setProjectName(`dubbing-${handoff.transcript_id.slice(0, 8)}`)
      if (handoff.language) setLanguage(handoff.language)
      if (handoff.segments) setSegments(handoff.segments as unknown as DubbingSegment[])
      setProjectId('')
      setRevision(0)
      setQuality(null)
      setDirty(true)
    }
    const stateHandoff = (location.state as { transcriptHandoff?: TranscriptHandoff } | null)?.transcriptHandoff
    if (stateHandoff) applyHandoff(stateHandoff)
    else {
      const transcriptId = searchParams.get('transcript') ?? ''
      if (transcriptId && handoffApplied.current !== transcriptId) {
        void fetchTranscriptHandoff(transcriptId, 'dubbing').then(applyHandoff).catch(showError)
      }
    }
    return () => { cancelled = true }
  }, [location.state, searchParams])

  const providerInfo = metaQuery.data?.translation_providers.find((item) => item.code === provider)
  const speakers = useMemo(() => Array.from(new Set(segments.map((item) => item.speaker_id))), [segments])
  const stageIndex = result ? 6 : quality ? 5 : segments.length && segments.every((item) => item.profile_id) ? 2 : translatedSrt ? 1 : 0
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 3)
  const endIndex = Math.min(segments.length, startIndex + Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + 6)
  const resultVideoUrl = result?.video_path
    ? resultTaskId && result.video_file ? taskFileUrl(resultTaskId, result.video_file) : projectId ? dubbingProjectMediaUrl(projectId, 'video') : ''
    : ''
  const resultAudioUrl = result && !result.video_path
    ? resultTaskId && (result.mixed_audio_file || result.wav_file)
      ? taskFileUrl(resultTaskId, result.mixed_audio_file || result.wav_file || '')
      : projectId ? dubbingProjectMediaUrl(projectId, result.mixed_audio_path ? 'mixed' : 'voice') : ''
    : ''

  function markChanged() {
    setDirty(true)
    setQuality(null)
    setResult(null)
  }

  function applyProject(project: DubbingProject) {
    const options = project.options ?? {}
    setProjectId(project.project_id)
    setRevision(project.revision)
    setProjectName(project.name)
    setSourceSrt(project.source_srt)
    setTranslatedSrt(project.translated_srt)
    setSourceVideo(project.source_video)
    setSourceAudio(project.source_audio)
    setLanguage(project.language)
    setSourceLanguage(optionString(options, 'source_language', sourceLanguage))
    setProvider(optionString(options, 'translation_provider', provider))
    setModel(optionString(options, 'translation_model', model))
    setBaseUrl(optionString(options, 'translation_base_url', baseUrl))
    setOutputDir(optionString(options, 'output_dir', outputDir))
    setDevice(optionString(options, 'device', device))
    const savedMixMode = optionString(options, 'mix_mode', mixMode)
    setMixMode(savedMixMode === 'mix' || savedMixMode === 'duck' ? savedMixMode : 'replace')
    setSourceVolume(optionNumber(options, 'source_volume', sourceVolume))
    setDubVolume(optionNumber(options, 'dub_volume', dubVolume))
    setFitMin(optionNumber(options, 'fit_min', fitMin))
    setFitMax(optionNumber(options, 'fit_max', fitMax))
    setFitTolerance(optionNumber(options, 'fit_tolerance', fitTolerance))
    setExportMp3(optionBoolean(options, 'export_mp3', exportMp3))
    setExportStems(optionBoolean(options, 'export_stems', exportStems))
    setSegments(project.segments)
    setQuality(project.quality?.report_id ? project.quality as DubbingQualityReport : null)
    setResult(project.last_result?.project_dir ? project.last_result as unknown as RenderResultPayload : null)
    setResultTaskId('')
    setDirty(false)
    setMessage(`Đã mở ${project.name}.`)
  }

  const loadProject = async (id: string) => {
    if (!id) return
    if (dirty && !window.confirm('Bỏ các thay đổi Dubbing chưa lưu?')) return
    try { applyProject(await fetchDubbingProject(id)) } catch (cause) { showError(cause) }
  }

  const handlePlan = async () => {
    try {
      const plan = await fetchDubbingPlan(sourceSrt, translatedSrt)
      setSegments(plan.segments)
      setQuality(plan.quality)
      setResult(null)
      setDirty(true)
      setMessage(`Đã lập kế hoạch ${plan.segments.length} đoạn.`)
    } catch (cause) { showError(cause) }
  }

  const handleTranslateStart = async () => {
    if (!sourceSrt.trim()) throw new Error('Hãy nhập sub gốc trước.')
    if (apiKey.trim()) await saveTranslationApiKey(provider, apiKey)
    const response = await startDubbingTranslation({
      source_srt: sourceSrt,
      source_language: sourceLanguage,
      target_language: language,
      provider,
      model,
      base_url: baseUrl,
      api_key: apiKey,
      batch_size: 10,
      max_workers: 2,
    })
    return response.task_id
  }

  const handleTranslateDone = (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const payload = task.result as { translated_srt: string; segments: DubbingSegment[]; quality: DubbingQualityReport }
    setTranslatedSrt(payload.translated_srt)
    setSegments(payload.segments)
    setQuality(payload.quality)
    setDirty(true)
    setMessage('Đã dịch và giữ nguyên timeline nguồn.')
  }

  const runQuality = async () => {
    try {
      const report = await fetchDubbingQuality(segments, {
        min_tempo: fitMin,
        max_tempo: fitMax,
        tolerance_ms: fitTolerance,
      })
      setQuality(report)
      setMessage(`QC ${report.score}/100 · ${report.error_count} lỗi · ${report.warning_count} cảnh báo.`)
      return report
    } catch (cause) { showError(cause); throw cause }
  }

  const saveProject = async () => {
    if (!segments.length) throw new Error('Hãy tạo kế hoạch trước khi lưu project.')
    const saved = await saveDubbingProject({
      project_id: projectId || undefined,
      expected_revision: revision,
      name: projectName || 'dubbing',
      stage: quality ? 'qc' : segments.every((item) => item.profile_id) ? 'cast' : translatedSrt ? 'translation' : 'ingest',
      source_srt: sourceSrt,
      translated_srt: translatedSrt,
      source_video: sourceVideo,
      source_audio: sourceAudio,
      language,
      segments,
      options: {
        output_dir: outputDir,
        device,
        source_language: sourceLanguage,
        translation_provider: provider,
        translation_model: model,
        translation_base_url: baseUrl,
        mix_mode: mixMode,
        source_volume: sourceVolume,
        dub_volume: dubVolume,
        fit_min: fitMin,
        fit_max: fitMax,
        fit_tolerance: fitTolerance,
        export_mp3: exportMp3,
        export_stems: exportStems,
      },
      quality: quality ?? {},
      last_result: result ? { ...result } : {},
    })
    applyProject(saved)
    await queryClient.invalidateQueries({ queryKey: ['dubbing-projects'] })
    return saved
  }

  const handleRenderStart = async () => {
    if (!segments.length) throw new Error('Hãy tạo kế hoạch lồng tiếng trước.')
    const report = quality ?? await runQuality()
    if (report.error_count && !window.confirm(`QC còn ${report.error_count} lỗi. Vẫn render?`)) throw new Error('Đã dừng để sửa QC.')
    const saved = dirty || !projectId ? await saveProject() : null
    const response = await startRender({
      project_id: saved?.project_id ?? projectId,
      kind: 'dubbing',
      segments,
      output_dir: outputDir,
      project_name: projectName || 'dubbing',
      device,
      language,
      export_mp3: exportMp3,
      export_stems: exportStems,
      resume_project_dir: resumeDir,
      source_video: sourceVideo,
      source_audio: sourceAudio,
      mix_mode: mixMode,
      source_volume: sourceVolume,
      dub_volume: dubVolume,
      fit_min_tempo: fitMin,
      fit_max_tempo: fitMax,
      fit_tolerance_ms: fitTolerance,
    })
    activeRenderProject.current = saved?.project_id ?? projectId
    return response.task_id
  }

  const handleRenderDone = (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const payload = task.result as unknown as RenderResultPayload
    setResult(payload)
    setResultTaskId(task.taskId)
    setQuality(payload.quality ?? quality)
    if (payload.preview_files) {
      setSegments((current) => current.map((item, index) => ({
        ...item,
        preview_path: payload.preview_files?.[index] ? taskFileUrl(task.taskId, payload.preview_files[index]) : '',
      })))
    }
    setResumeDir('')
    setDirty(false)
    setMessage('Render và QC vòng hai đã hoàn tất.')
    const renderedProjectId = activeRenderProject.current
    if (renderedProjectId) {
      void fetchDubbingProject(renderedProjectId).then((project) => {
        setRevision(project.revision)
        void queryClient.invalidateQueries({ queryKey: ['dubbing-projects'] })
      }).catch(showError)
    }
  }

  const updateSegment = (id: string, changes: Partial<DubbingSegment>) => {
    setSegments((items) => items.map((item) => item.segment_id === id ? { ...item, ...changes } : item))
    markChanged()
  }

  const mapSpeaker = (speaker: string, profileId: string) => {
    setSegments((items) => items.map((item) => item.speaker_id === speaker ? { ...item, profile_id: profileId } : item))
    markChanged()
  }

  const splitSegment = (index: number) => {
    const segment = segments[index]
    if (!segment || segment.end_ms - segment.start_ms < 200) return
    const splitAt = splitTextAtWord(segment.text)
    const sourceSplit = splitTextAtWord(segment.source_text)
    const middleMs = Math.round((segment.start_ms + segment.end_ms) / 2)
    const first = {
      ...segment,
      segment_id: newSegmentId(),
      end_ms: middleMs,
      text: splitAt[0],
      source_text: sourceSplit[0],
      preview_path: '',
    }
    const second = {
      ...segment,
      segment_id: newSegmentId(),
      start_ms: middleMs,
      text: splitAt[1],
      source_text: sourceSplit[1],
      preview_path: '',
    }
    setSegments((items) => [...items.slice(0, index), first, second, ...items.slice(index + 1)])
    markChanged()
  }

  const mergeSegment = (index: number) => {
    if (index < 1) return
    const previous = segments[index - 1]
    const current = segments[index]
    if (!previous || !current) return
    const merged = {
      ...previous,
      segment_id: newSegmentId(),
      end_ms: current.end_ms,
      text: [previous.text, current.text].filter(Boolean).join(' '),
      source_text: [previous.source_text, current.source_text].filter(Boolean).join(' '),
      preview_path: '',
    }
    setSegments((items) => [...items.slice(0, index - 1), merged, ...items.slice(index + 1)])
    markChanged()
  }

  return <div className="dubbing-workspace">
    <header className="dubbing-project-bar">
      <div className="field"><label>Project</label><input value={projectName} onChange={(event) => { setProjectName(event.target.value); markChanged() }} /></div>
      <div className="field"><label>Bản đã lưu</label><select value={projectId} onChange={(event) => void loadProject(event.target.value)}><option value="">Project mới</option>{(projectsQuery.data ?? []).map((item) => <option key={item.project_id} value={item.project_id}>{item.name} · r{item.revision}</option>)}</select></div>
      <button className="btn accent" disabled={!dirty || !segments.length} onClick={() => void saveProject().catch(showError)}>Lưu checkpoint</button>
      <button className="btn" disabled={!projectId} onClick={() => { if (!projectId || !window.confirm('Xóa Dubbing project này?')) return; void deleteDubbingProject(projectId).then(() => { setProjectId(''); setRevision(0); return queryClient.invalidateQueries({ queryKey: ['dubbing-projects'] }) }).catch(showError) }}>Xóa</button>
    </header>

    <nav className="dubbing-stage-rail">{STAGES.map((stage, index) => <span key={stage} className={index < stageIndex ? 'done' : index === stageIndex ? 'active' : ''}><b>{index + 1}</b>{stage}</span>)}</nav>
    {message && <div className="workspace-message">{message}</div>}

    <div className="dubbing-source-grid">
      <section className="section-card dubbing-source-card">
        <div className="section-header"><div><span className="workspace-kicker">INGEST</span><h2 className="section-title">Sub gốc</h2></div><button className="btn" onClick={() => void handlePlan()}>Cập nhật kế hoạch</button></div>
        <textarea rows={9} value={sourceSrt} onChange={(event) => { setSourceSrt(event.target.value); markChanged() }} placeholder={'1\n00:00:00,000 --> 00:00:03,000\nLan: Hello'} />
      </section>
      <section className="section-card dubbing-source-card">
        <div className="section-header"><div><span className="workspace-kicker">TRANSLATION</span><h2 className="section-title">Bản dịch ngoài hoặc AI</h2></div><TaskButton label="Dịch bằng AI" variant="accent" disabled={!sourceSrt.trim()} onStart={handleTranslateStart} onFinish={handleTranslateDone} /></div>
        <textarea rows={9} value={translatedSrt} onChange={(event) => { setTranslatedSrt(event.target.value); markChanged() }} placeholder="Dán SRT đã dịch tại đây để không gọi AI." />
      </section>
    </div>

    <section className="section-card">
      <div className="section-header"><div><span className="workspace-kicker">AI TRANSLATION</span><h2 className="section-title">Ngôn ngữ và nhà cung cấp</h2></div></div>
      <div className="field-grid compact">
        <div className="field"><label>Ngôn ngữ nguồn</label><select value={sourceLanguage} onChange={(event) => setSourceLanguage(event.target.value)}>{(metaQuery.data?.source_languages ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></div>
        <div className="field"><label>Dịch sang</label><select value={language} onChange={(event) => setLanguage(event.target.value)}>{(metaQuery.data?.target_languages ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></div>
        <div className="field"><label>Nhà cung cấp</label><select value={provider} onChange={(event) => { const info = metaQuery.data?.translation_providers.find((item) => item.code === event.target.value); setProvider(event.target.value); setModel(info?.default_model ?? ''); setBaseUrl(info?.default_base_url ?? ''); setApiKey('') }}>{(metaQuery.data?.translation_providers ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></div>
        <div className="field"><label>Model</label><select value={model} onChange={(event) => setModel(event.target.value)}>{Array.from(new Set([model, ...(providerInfo?.models ?? [])].filter(Boolean))).map((item) => <option key={item} value={item}>{item}</option>)}</select></div>
        <div className="field"><label>API key</label><input type="password" value={apiKey} placeholder={providerInfo?.api_key_configured ? '••••••••' : 'Chưa cấu hình'} onChange={(event) => setApiKey(event.target.value)} /></div>
      </div>
    </section>

    {segments.length > 0 && <>
      <section className="section-card">
        <div className="section-header"><div><span className="workspace-kicker">CAST</span><h2 className="section-title">Phân vai ({speakers.length} người nói)</h2></div><button className="btn" onClick={() => void runQuality()}>Chạy QC</button></div>
        <div className="dubbing-cast-grid">{speakers.map((speaker) => <label key={speaker}><span>{speaker}</span><select value={segments.find((item) => item.speaker_id === speaker)?.profile_id ?? ''} onChange={(event) => mapSpeaker(speaker, event.target.value)}><option value="">Chưa gán voice</option>{(profilesQuery.data ?? []).map((voice) => <option key={voice.voice_id} value={voice.selection.profile_id} disabled={!voice.compatibility.dubbing}>{voice.name}{voice.compatibility.dubbing ? '' : ' · không tương thích'}</option>)}</select></label>)}</div>
      </section>

      <section className="section-card dubbing-segments-card">
        <div className="section-header"><div><span className="workspace-kicker">TIMELINE</span><h2 className="section-title">Đoạn lồng tiếng ({segments.length})</h2></div>{quality && <div className={`dubbing-score${quality.error_count ? ' danger' : ''}`}><strong>{quality.score}</strong><span>QC / 100</span></div>}</div>
        {quality?.issues.length ? <div className="dubbing-issues">{quality.issues.slice(0, 8).map((issue) => <span key={`${issue.segment_id}:${issue.code}`} className={issue.severity}>{issue.message}</span>)}</div> : null}
        <div className="dubbing-segment-scroll" style={{ height: VIEWPORT_HEIGHT }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
          <div style={{ height: segments.length * ROW_HEIGHT, position: 'relative' }}>
            <div style={{ transform: `translateY(${startIndex * ROW_HEIGHT}px)` }}>{segments.slice(startIndex, endIndex).map((segment, offset) => { const index = startIndex + offset; return <SegmentRow key={segment.segment_id} index={index} segment={segment} profiles={profilesQuery.data ?? []} onChange={(changes) => updateSegment(segment.segment_id, changes)} onSplit={() => splitSegment(index)} onMerge={() => mergeSegment(index)} /> })}</div>
          </div>
        </div>
      </section>

      <section className="section-card">
        <div className="section-header"><div><span className="workspace-kicker">SMART FIT & EXPORT</span><h2 className="section-title">Khớp thời lượng và trộn media</h2></div></div>
        <div className="field-grid">
          <PathField label="Video nguồn" value={sourceVideo} onChange={(value) => { setSourceVideo(value); markChanged() }} onBrowse={() => pickVideoFile()} />
          <PathField label="Audio/stem nguồn (tùy chọn)" value={sourceAudio} onChange={(value) => { setSourceAudio(value); markChanged() }} onBrowse={() => pickAudioFile()} />
          <PathField label="Thư mục xuất" value={outputDir} onChange={setOutputDir} onBrowse={() => pickFolder()} />
          <div className="field"><label>Thiết bị</label><select value={device} onChange={(event) => setDevice(event.target.value)}>{(statusQuery.data?.devices ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></div>
          <div className="field"><label>Trộn audio</label><select value={mixMode} onChange={(event) => setMixMode(event.target.value as typeof mixMode)}><option value="replace">Thay audio nguồn</option><option value="mix">Trộn với audio/stem nguồn</option><option value="duck">Hạ nền nguồn khi có voice</option></select></div>
          <div className="field"><label>Biên tempo giữ pitch</label><div className="inline-fields"><input type="number" min="0.5" max="1" step="0.05" value={fitMin} onChange={(event) => setFitMin(Number(event.target.value))} /><span>→</span><input type="number" min="1" max="2" step="0.05" value={fitMax} onChange={(event) => setFitMax(Number(event.target.value))} /></div></div>
          <div className="field"><label>Âm nguồn {Math.round(sourceVolume * 100)}%</label><input type="range" min="0" max="1" step="0.05" value={sourceVolume} onChange={(event) => setSourceVolume(Number(event.target.value))} /></div>
          <div className="field"><label>Voice {Math.round(dubVolume * 100)}%</label><input type="range" min="0" max="2" step="0.05" value={dubVolume} onChange={(event) => setDubVolume(Number(event.target.value))} /></div>
          <div className="field"><label>Sai số QC (ms)</label><input type="number" min="0" max="1000" value={fitTolerance} onChange={(event) => setFitTolerance(Number(event.target.value))} /></div>
          <label className="field-check"><input type="checkbox" checked={exportMp3} onChange={(event) => setExportMp3(event.target.checked)} /><span>Xuất MP3</span></label>
          <label className="field-check"><input type="checkbox" checked={exportStems} onChange={(event) => setExportStems(event.target.checked)} /><span>Giữ stem từng đoạn</span></label>
        </div>
        <ResumeJobs outputDir={outputDir} selected={resumeDir} onSelect={setResumeDir} />
        <div className="dubbing-render-actions"><TaskButton label={resumeDir ? 'Tiếp tục render' : 'Render lồng tiếng'} variant="accent" onStart={handleRenderStart} onFinish={handleRenderDone} /><button className="btn" disabled={!result} onClick={() => result && void openPath(result.project_dir)}>Mở output</button></div>
      </section>
    </>}

    {result && <section className="section-card dubbing-result"><div><span className="workspace-kicker">RESULT</span><h2 className="section-title">Bản lồng tiếng hoàn chỉnh</h2></div>{resultVideoUrl && <video controls preload="metadata" src={resultVideoUrl} />}{resultAudioUrl && <audio controls preload="metadata" src={resultAudioUrl} />}<div className="dubbing-result-files">{result.video_path && <p>Video: {result.video_path}</p>}<p>WAV: {result.wav_path}</p><p>SRT: {result.srt_path}</p></div></section>}
  </div>
}

function SegmentRow({ index, segment, profiles, onChange, onSplit, onMerge }: { index: number; segment: DubbingSegment; profiles: Awaited<ReturnType<typeof fetchLibraryVoices>>; onChange: (changes: Partial<DubbingSegment>) => void; onSplit: () => void; onMerge: () => void }) {
  const [text, setText] = useState(segment.text)
  useEffect(() => setText(segment.text), [segment.text])
  return <div className="dubbing-segment-row" style={{ height: ROW_HEIGHT - 8 }}>
    <div className="dubbing-segment-time"><b>#{index + 1}</b><label>Bắt đầu<input aria-label={`Bắt đầu đoạn ${index + 1}`} type="number" min="0" value={segment.start_ms} onChange={(event) => onChange({ start_ms: Number(event.target.value) })} /></label><label>Kết thúc<input aria-label={`Kết thúc đoạn ${index + 1}`} type="number" min="1" value={segment.end_ms} onChange={(event) => onChange({ end_ms: Number(event.target.value) })} /></label><div><button className="btn quiet" type="button" onClick={onSplit}>Tách</button><button className="btn quiet" type="button" disabled={index === 0} onClick={onMerge}>Gộp trên</button></div></div>
    <div className="dubbing-segment-copy"><small>{segment.source_text}</small><textarea value={text} rows={2} onChange={(event) => setText(event.target.value)} onBlur={() => text !== segment.text && onChange({ text })} /></div>
    <div className="field"><label>{segment.speaker_id}</label><select value={segment.profile_id} onChange={(event) => onChange({ profile_id: event.target.value })}><option value="">Chưa gán</option>{profiles.map((voice) => <option key={voice.voice_id} value={voice.selection.profile_id} disabled={!voice.compatibility.dubbing}>{voice.name}</option>)}</select></div>
    <div className="dubbing-segment-controls"><label>Tốc độ<input type="number" min="0.5" max="1.5" step="0.05" value={segment.speed} onChange={(event) => onChange({ speed: Number(event.target.value) })} /></label><label>Âm lượng<input type="number" min="0" max="2" step="0.1" value={segment.volume} onChange={(event) => onChange({ volume: Number(event.target.value) })} /></label></div>
    {segment.preview_path ? <audio controls preload="none" src={segment.preview_path} /> : <span className="dubbing-preview-empty">Chưa render</span>}
  </div>
}

function PathField({ label, value, onChange, onBrowse }: { label: string; value: string; onChange: (value: string) => void; onBrowse: () => Promise<string | null> }) {
  return <div className="field"><label>{label}</label><div className="path-control"><input value={value} onChange={(event) => onChange(event.target.value)} /><button className="btn" onClick={() => void onBrowse().then((path) => path && onChange(path))}>Chọn</button></div></div>
}

function ResumeJobs({ outputDir, selected, onSelect }: { outputDir: string; selected: string; onSelect: (value: string) => void }) {
  const query = useQuery({ queryKey: ['dubbing-resume', outputDir], queryFn: () => fetchResumeJobs(outputDir), enabled: Boolean(outputDir) })
  const jobs = query.data ?? []
  if (!jobs.length) return null
  return <div className="dubbing-resume"><label>Render dở dang</label><select value={selected} onChange={(event) => onSelect(event.target.value)}><option value="">Bắt đầu bản mới</option>{jobs.map((job) => <option key={job.project_dir} value={job.project_dir}>{job.project_name} · {job.completed_spans}/{job.total_spans} · {job.status}</option>)}</select></div>
}

function splitTextAtWord(text: string): [string, string] {
  const normalized = text.trim()
  if (!normalized) return ['', '']
  const middle = Math.floor(normalized.length / 2)
  const after = normalized.indexOf(' ', middle)
  const before = normalized.lastIndexOf(' ', middle)
  const splitAt = after >= 0 && (before < 0 || after - middle <= middle - before) ? after : before
  if (splitAt <= 0) return [normalized, '']
  return [normalized.slice(0, splitAt).trim(), normalized.slice(splitAt + 1).trim()]
}

function newSegmentId(): string {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `segment-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function optionString(options: Record<string, unknown>, key: string, fallback: string): string {
  const value = options[key]
  return typeof value === 'string' ? value : fallback
}

function optionNumber(options: Record<string, unknown>, key: string, fallback: number): number {
  const value = options[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function optionBoolean(options: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const value = options[key]
  return typeof value === 'boolean' ? value : fallback
}

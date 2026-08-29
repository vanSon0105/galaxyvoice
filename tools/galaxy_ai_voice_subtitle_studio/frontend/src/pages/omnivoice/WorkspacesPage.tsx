import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useSearchParams } from 'react-router-dom'

import { fetchSettings } from '../../api/settings'
import { fetchOmniVoiceStatus } from '../../api/omnivoice'
import { fetchLibraryVoices } from '../../api/voiceLibrary'
import { openPath, taskFileUrl } from '../../api/voice'
import {
  createDocument,
  deleteLongformProject,
  documentOp,
  addHistory,
  fetchHistory,
  fetchLongformProject,
  fetchLongformProjects,
  fetchResumeJobs,
  importSource,
  longformProjectMediaUrl,
  saveLongformProject,
  startRender,
} from '../../api/workspaces'
import type {
  DocumentItem,
  LongformDocument,
  LongformProject,
  PronunciationRule,
  RenderResultPayload,
  ResumeJob,
} from '../../api/workspaces'
import { TaskButton } from '../../components/TaskButton'
import { AudioPostPanel } from '../../components/audio/AudioPostPanel'
import { pickBookFile, pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'
import { fetchTranscriptHandoff, type TranscriptHandoff } from '../../api/transcripts'
import { openProjectHandoff } from '../../api/projectGraph'
import { useVoiceProject } from '../voice/VoiceProjectContext'

type Kind = 'stories' | 'audiobook'
const LONGFORM_ROW_HEIGHT = 142
const LONGFORM_VIEWPORT_HEIGHT = 620

const STORY_SAMPLE = `# Mở đầu
Người kể: Một buổi sáng yên tĩnh bắt đầu. [pause 500ms]
Lan: [slow]Hôm nay chúng ta sẽ đi đâu?[/slow]
Minh: Đi tìm một câu chuyện mới.
`

const AUDIOBOOK_SAMPLE = `# Chương 1 - Khởi đầu
[voice:Người kể] Mỗi hành trình đều bắt đầu bằng một lựa chọn.
[pause 700ms]

# Chương 2 - Cuộc gặp
[voice:Lan] Tôi đã đợi ở đây rất lâu rồi.
`

/** Stories / audiobook longform workspace: source → document editor → render. */
export function WorkspacesPage() {
  const { projectId: galaxyProjectId } = useVoiceProject()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const handoffApplied = useRef('')
  const recoveryApplied = useRef('')
  const activeRenderProject = useRef('')
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<Kind>('stories')
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const profilesQuery = useQuery({ queryKey: ['voice-library-picker'], queryFn: () => fetchLibraryVoices() })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const projectsQuery = useQuery({
    queryKey: ['longform-projects', kind, galaxyProjectId],
    queryFn: () => fetchLongformProjects(kind, galaxyProjectId),
  })
  const historyQuery = useQuery({
    queryKey: ['workspace-history', kind],
    queryFn: () => fetchHistory({ workspace: kind }),
  })
  const [source, setSource] = useState('')
  const [doc, setDoc] = useState<LongformDocument | null>(null)
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [revision, setRevision] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1.0)
  const [castMap, setCastMap] = useState<Record<string, string>>({})
  const [gapMs, setGapMs] = useState(250)
  const [exportMp3, setExportMp3] = useState(true)
  const [exportM4b, setExportM4b] = useState(false)
  const [exportStems, setExportStems] = useState(false)
  const [mastering, setMastering] = useState(true)
  const [targetLufs, setTargetLufs] = useState(-16)
  const [truePeakDb, setTruePeakDb] = useState(-1)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [coverPath, setCoverPath] = useState('')
  const [resumeJobs, setResumeJobs] = useState<ResumeJob[]>([])
  const [result, setResult] = useState<RenderResultPayload | null>(null)
  const [resultTaskId, setResultTaskId] = useState('')
  const [error, setError] = useState('')
  const [planScrollTop, setPlanScrollTop] = useState(0)
  const sourceRef = useRef<HTMLTextAreaElement | null>(null)
  const dirtyGeneration = useRef(0)

  const markDirty = () => {
    dirtyGeneration.current += 1
    setDirty(true)
  }

  /** Insert markup at the cursor; wrap the selection for paired tokens. */
  const insertToken = (before: string, after = '') => {
    const textarea = sourceRef.current
    if (!textarea) return
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const selected = source.slice(start, end)
    const next =
      source.slice(0, start) + before + (selected || (after ? '' : ' ')) + after + source.slice(end)
    setSource(next)
    markDirty()
    requestAnimationFrame(() => {
      textarea.focus()
      const cursor = selected
        ? start + before.length + selected.length + after.length
        : start + before.length
      textarea.setSelectionRange(cursor, cursor)
    })
  }

  const wrapToken = (token: string) => {
    const textarea = sourceRef.current
    if (!textarea) return
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    if (start !== end) {
      insertToken(`[${token}]`, `[/${token}]`)
    } else {
      insertToken(`[${token}][/${token}]`)
    }
  }

  useEffect(() => {
    setSelectedProjectId('')
    setRevision(0)
    setSource('')
    setDoc(null)
    setResult(null)
    setDirty(false)
    handoffApplied.current = ''
  }, [galaxyProjectId])

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings) return
    const configuredOutput = String(settings.omnivoice_output_dir ?? settings.output_dir ?? '')
    setOutputDir(configuredOutput)
    void refreshResumeJobs(configuredOutput)
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    if (!handoffApplied.current) setLanguage(String(settings.omnivoice_language ?? 'vi'))
    setSpeed(Number(settings.omnivoice_speed ?? 1))
  }, [settingsQuery.data])

  useEffect(() => {
    let cancelled = false
    const applyHandoff = (handoff: TranscriptHandoff) => {
      if (cancelled || handoff.target !== 'longform' || handoffApplied.current === handoff.transcript_id) return
      handoffApplied.current = handoff.transcript_id
      setKind('stories')
      setSource(handoff.text ?? '')
      setProjectName(`transcript-${handoff.transcript_id.slice(0, 8)}`)
      if (handoff.language) setLanguage(handoff.language)
      setDoc(null)
      setResult(null)
      setSelectedProjectId('')
      setRevision(0)
      markDirty()
      if (handoff.handoff_id) {
        void openProjectHandoff(handoff.handoff_id).catch((cause) => {
          if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
        })
      }
    }
    const stateHandoff = (location.state as { transcriptHandoff?: TranscriptHandoff } | null)
      ?.transcriptHandoff
    if (stateHandoff) applyHandoff(stateHandoff)
    else {
      const transcriptId = searchParams.get('transcript') ?? ''
      if (transcriptId && handoffApplied.current !== transcriptId) {
        void fetchTranscriptHandoff(transcriptId, 'longform').then(applyHandoff).catch((cause) => {
          if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
        })
      }
    }
    return () => { cancelled = true }
  }, [location.state, searchParams])

  const refreshResumeJobs = async (dir: string) => {
    if (!dir.trim()) {
      setResumeJobs([])
      return
    }
    try {
      setResumeJobs(await fetchResumeJobs(dir.trim()))
    } catch {
      setResumeJobs([])
    }
  }

  const handleCreate = async () => {
    setError('')
    if (!source.trim()) {
      setError('Dán kịch bản truyện / sách trước.')
      return
    }
    try {
      const created = await createDocument(kind, source, undefined, language)
      setDoc(created)
      setResult(null)
      markDirty()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const handleImport = async () => {
    const path = await pickBookFile()
    if (!path) return
    try {
      const imported = await importSource(path)
      setSource(imported.text)
      markDirty()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const runOp = async (op: Parameters<typeof documentOp>[2]) => {
    if (!doc) return
    try {
      const updated = await documentOp(doc.doc_id, doc.kind, { ...op, document: doc.document })
      setDoc(updated)
      markDirty()
      return updated
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      return null
    }
  }

  const handleRenderStart = async (resumeProjectDir = ''): Promise<string> => {
    setError('')
    if (!doc) {
      setError('Tạo kế hoạch trước khi render.')
      throw new Error('Tạo kế hoạch trước khi render.')
    }
    const projectId = selectedProjectId && !dirty
      ? selectedProjectId
      : (await saveLongformCheckpoint()).project_id
    const response = await startRender({
      project_id: projectId,
      doc_id: doc.doc_id,
      kind: doc.kind,
      output_dir: outputDir,
      project_name: projectName || 'longform',
      device,
      language,
      speed,
      cast_map: castMap,
      gap_ms: gapMs,
      export_mp3: exportMp3,
      export_m4b: exportM4b,
      export_stems: exportStems,
      mastering,
      target_lufs: targetLufs,
      true_peak_db: truePeakDb,
      title,
      author,
      cover_path: coverPath,
      resume_project_dir: resumeProjectDir,
    })
    activeRenderProject.current = projectId
    return response.task_id
  }

  const handleRenderDone = async (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const completed = task.result as unknown as RenderResultPayload
    setResult(completed)
    setResultTaskId(task.taskId)
    try {
      await addHistory({
        workspace: kind,
        title: projectName || completed.project_dir.split(/[\\/]/).pop() || 'longform',
        summary: `${completed.span_count} đoạn`,
        artifact_path: completed.project_dir,
        metadata: { manifest_path: completed.manifest_path },
      })
      void queryClient.invalidateQueries({ queryKey: ['workspace-history', kind] })
    } catch {
      // History is optional; the rendered artifact remains valid if persistence fails.
    }
    const renderedProjectId = activeRenderProject.current
    if (renderedProjectId) {
      void fetchLongformProject(renderedProjectId).then((project) => {
        setRevision(project.revision)
        void queryClient.invalidateQueries({ queryKey: ['longform-projects', kind] })
      }).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)))
    }
    void refreshResumeJobs(outputDir)
  }

  const saveLongformCheckpoint = async () => {
    if (!doc) throw new Error('Hãy tạo kế hoạch trước khi lưu project.')
    const savingGeneration = dirtyGeneration.current
    const saved = await saveLongformProject({
      galaxy_project_id: galaxyProjectId,
      project_id: selectedProjectId || undefined,
      expected_revision: revision,
      name: projectName || 'longform',
      kind,
      stage: doc.voice_names.length && doc.voice_names.every((voice) => castMap[voice]) ? 'cast' : 'plan',
      source,
      document: {
        ...doc.document,
        items: doc.document.items.map((item) => ({ ...item, preview_path: '' })),
      },
      language,
      options: {
        output_dir: outputDir,
        device,
        speed,
        cast_map: castMap,
        gap_ms: gapMs,
        export_mp3: exportMp3,
        export_m4b: exportM4b,
        export_stems: exportStems,
        mastering,
        target_lufs: targetLufs,
        true_peak_db: truePeakDb,
      },
      metadata: { title, author, cover_path: coverPath },
    })
    setSelectedProjectId(saved.project_id)
    setRevision(saved.revision)
    setProjectName(saved.name)
    if (dirtyGeneration.current === savingGeneration) setDirty(false)
    await queryClient.invalidateQueries({ queryKey: ['longform-projects', kind] })
    return saved
  }

  const handleSaveProject = async () => {
    setError('')
    try {
      await saveLongformCheckpoint()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const applyProject = async (project: LongformProject) => {
    const options = project.options
    const metadata = project.metadata
    const loaded = await createDocument(
      project.kind,
      project.source,
      project.document,
      project.language,
    )
    setKind(project.kind)
    setSelectedProjectId(project.project_id)
    setRevision(project.revision)
    setProjectName(project.name)
    setSource(project.source)
    setDoc(loaded)
    setOutputDir(String(options.output_dir ?? outputDir))
    setDevice(String(options.device ?? device))
    setLanguage(project.language || language)
    setSpeed(Number(options.speed ?? speed))
    setCastMap(options.cast_map && typeof options.cast_map === 'object' ? options.cast_map as Record<string, string> : {})
    setGapMs(Number(options.gap_ms ?? gapMs))
    setExportMp3(Boolean(options.export_mp3 ?? exportMp3))
    setExportM4b(Boolean(options.export_m4b ?? exportM4b))
    setExportStems(Boolean(options.export_stems ?? exportStems))
    setMastering(Boolean(options.mastering ?? true))
    setTargetLufs(Number(options.target_lufs ?? -16))
    setTruePeakDb(Number(options.true_peak_db ?? -1))
    setTitle(String(metadata.title ?? ''))
    setAuthor(String(metadata.author ?? ''))
    setCoverPath(String(metadata.cover_path ?? ''))
    setResult(project.last_result?.project_dir ? project.last_result as unknown as RenderResultPayload : null)
    setResultTaskId('')
    setDirty(false)
  }

  const handleLoadProject = async (projectId: string) => {
    if (!projectId) return
    setError('')
    try {
      await applyProject(await fetchLongformProject(projectId))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const applyRecoveryProject = useRef(applyProject)
  applyRecoveryProject.current = applyProject
  useEffect(() => {
    const workflowId = searchParams.get('workflow_id') ?? ''
    const recoveryProjectId = searchParams.get('project_id') ?? ''
    if (recoveryProjectId && galaxyProjectId !== recoveryProjectId) return
    if (!workflowId || recoveryApplied.current === workflowId) return
    recoveryApplied.current = workflowId
    void fetchLongformProject(workflowId).then((project) => applyRecoveryProject.current(project)).catch((cause) => {
      recoveryApplied.current = ''
      setError(cause instanceof Error ? cause.message : String(cause))
    })
  }, [galaxyProjectId, searchParams])

  const handleDeleteProject = async () => {
    if (!selectedProjectId || !window.confirm('Xóa project Truyện & Sách nói này?')) return
    setError('')
    try {
      await deleteLongformProject(selectedProjectId)
      setSelectedProjectId('')
      setRevision(0)
      setProjectName('')
      setSource('')
      setDoc(null)
      setResult(null)
      setDirty(false)
      await queryClient.invalidateQueries({ queryKey: ['longform-projects', kind] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const updateItemLocal = (itemId: string, changes: Record<string, unknown>) => {
    if (!doc) return
    markDirty()
    setDoc({
      ...doc,
      document: {
        ...doc.document,
        items: doc.document.items.map((item) =>
          item.item_id === itemId ? { ...item, ...changes } : item,
        ),
      },
    })
  }

  const commitItem = (itemId: string) => {
    if (!doc) return
    const item = doc.document.items.find((candidate) => candidate.item_id === itemId)
    if (!item) return
    void runOp({
      op: 'update',
      item_id: itemId,
      changes: {
        chapter: item.chapter,
        speaker: item.speaker,
        text: item.text,
        speed: Number(item.speed),
        volume: Number(item.volume),
        pause_after_ms: Number(item.pause_after_ms),
        spoken_text: item.spoken_text,
        emotion: item.emotion,
        emphasis: item.emphasis,
        spell: item.spell,
      },
    })
  }

  const updatePronunciationRules = (rules: PronunciationRule[]) => {
    if (!doc) return
    setDoc({ ...doc, document: { ...doc.document, pronunciation_rules: rules } })
    markDirty()
  }

  const addPronunciationRule = () => {
    if (!doc) return
    updatePronunciationRules([
      ...doc.document.pronunciation_rules,
      {
        rule_id: `pron-${Date.now().toString(36)}`,
        source: '',
        replacement: '',
        language,
        case_sensitive: false,
        whole_word: true,
      },
    ])
  }

  const addChapter = () => {
    const name = window.prompt('Tên chương mới')?.trim()
    if (!name) return
    const after = doc?.document.chapters.at(-1) ?? ''
    void runOp({ op: 'add_chapter', chapter: after, name })
  }

  const renameChapter = (chapter: string) => {
    const name = window.prompt('Đổi tên chương', chapter)?.trim()
    if (!name || name === chapter) return
    void runOp({ op: 'rename_chapter', chapter, name })
  }

  const resultAudioUrl = result
    ? resultTaskId && result.wav_file
      ? taskFileUrl(resultTaskId, result.wav_file)
      : selectedProjectId
        ? longformProjectMediaUrl(selectedProjectId, result.mp3_path ? 'mp3' : 'wav')
        : ''
    : ''

  const handlePreviewStart = async (itemIndex: number): Promise<string> => {
    if (!doc) throw new Error('Chưa có dòng để nghe thử.')
    const projectId = selectedProjectId && !dirty
      ? selectedProjectId
      : (await saveLongformCheckpoint()).project_id
    const response = await startRender({
      project_id: projectId,
      kind: doc.kind,
      output_dir: outputDir,
      project_name: `${projectName || 'longform'}-preview-${itemIndex + 1}`,
      device,
      language,
      speed,
      cast_map: castMap,
      gap_ms: 0,
      export_mp3: false,
      export_m4b: false,
      export_stems: false,
      mastering: false,
      preview_item_index: itemIndex,
    })
    return response.task_id
  }

  const handlePreviewDone = (itemId: string, task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const payload = task.result as unknown as RenderResultPayload
    const preview = payload.wav_file
    if (!preview) return
    setDoc((current) => current ? {
      ...current,
      document: {
        ...current.document,
        items: current.document.items.map((item) => item.item_id === itemId
          ? { ...item, preview_path: taskFileUrl(task.taskId, preview) }
          : item),
      },
    } : current)
  }

  const longformStage = result && !dirty ? 4 : doc?.voice_names.length && doc.voice_names.every((voice) => castMap[voice]) ? 3 : doc ? 2 : 1
  const planStartIndex = Math.max(0, Math.floor(planScrollTop / LONGFORM_ROW_HEIGHT) - 2)
  const planEndIndex = Math.min(
    doc?.document.items.length ?? 0,
    planStartIndex + Math.ceil(LONGFORM_VIEWPORT_HEIGHT / LONGFORM_ROW_HEIGHT) + 5,
  )
  const visiblePlanItems = doc?.document.items.slice(planStartIndex, planEndIndex) ?? []

  return (
    <div className="longform-page">
      <div className="longform-stage-rail" aria-label="Tiến trình project">
        {['Nguồn', 'Kế hoạch', 'Phân vai', 'Xuất bản'].map((label, index) => (
          <span key={label} className={index + 1 === longformStage ? 'active' : index + 1 < longformStage ? 'done' : ''}>
            <b>{index + 1}</b>{label}
          </span>
        ))}
      </div>
      <section className="section-card">
        <h2 className="section-title">Project &amp; lịch sử</h2>
        <div className="toolbar-row">
          <select
            value={selectedProjectId}
            onChange={(event) => {
              if (event.target.value) void handleLoadProject(event.target.value)
            }}
          >
            <option value="">Project mới</option>
            {(projectsQuery.data ?? []).map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => void handleSaveProject()}>
            {dirty ? 'Lưu thay đổi' : 'Đã lưu'}
          </button>
          <button className="btn danger" disabled={!selectedProjectId} onClick={() => void handleDeleteProject()}>
            Xóa project
          </button>
          {(historyQuery.data ?? []).slice(0, 4).map((item) => (
            <button
              className="btn"
              key={item.history_id}
              title={item.summary}
              onClick={() => item.artifact_path && void openPath(item.artifact_path)}
            >
              {item.title}
            </button>
          ))}
        </div>
      </section>
      <section className="section-card">
        <h2 className="section-title">Kịch bản nguồn</h2>
        <div className="seg" style={{ marginBottom: 10 }}>
          <button
            className={`seg-item${kind === 'stories' ? ' active' : ''}`}
            onClick={() => {
              setKind('stories')
              setSelectedProjectId('')
              setRevision(0)
              setDoc(null)
              setResult(null)
              setDirty(false)
            }}
          >
            Truyện nhiều vai
          </button>
          <button
            className={`seg-item${kind === 'audiobook' ? ' active' : ''}`}
            onClick={() => {
              setKind('audiobook')
              setSelectedProjectId('')
              setRevision(0)
              setDoc(null)
              setResult(null)
              setDirty(false)
            }}
          >
            Sách nói
          </button>
        </div>
        <div className="markup-bar">
          <button className="btn" onClick={() => insertToken(kind === 'stories' ? STORY_SAMPLE : AUDIOBOOK_SAMPLE)}>
            Mẫu
          </button>
          <button className="btn" onClick={() => insertToken('[voice:Người kể] ')}>
            [voice:]
          </button>
          <button className="btn" onClick={() => insertToken('[pause 500ms]')}>
            [pause]
          </button>
          <button className="btn" onClick={() => wrapToken('slow')}>
            [slow]
          </button>
          <button className="btn" onClick={() => wrapToken('fast')}>
            [fast]
          </button>
          <button className="btn" onClick={() => wrapToken('emphasis')}>
            [emphasis]
          </button>
          <button className="btn" onClick={() => wrapToken('spell')}>
            [spell]
          </button>
          <select
            className="markup-expression"
            value=""
            onChange={(event) => {
              if (event.target.value) {
                insertToken(event.target.value)
                event.target.value = ''
              }
            }}
          >
            <option value="">Biểu cảm…</option>
            {(statusQuery.data?.expression_tags ?? []).map((tag) => (
              <option key={tag.value} value={tag.value}>
                {tag.label}
              </option>
            ))}
          </select>
          <span className="markup-hint">
            Bôi đen đoạn chữ rồi bấm [slow]/[fast]/… để bọc quanh đoạn đó.
          </span>
        </div>
        <textarea
          ref={sourceRef}
          className="srt-editor"
          rows={9}
          placeholder={
            kind === 'stories'
              ? 'Người kể: [slow]Một buổi sáng yên tĩnh bắt đầu.[/slow]\nLan: Hôm nay chúng ta sẽ đi đâu?\n\n# Mở đầu và [pause 500ms] để tạo nhịp'
              : '# Chương 1\n[voice:Người kể] Mỗi hành trình đều bắt đầu bằng một lựa chọn.\n[pause 700ms]'
          }
          value={source}
          onChange={(event) => { setSource(event.target.value); markDirty() }}
        />
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <button className="btn accent" onClick={() => void handleCreate()}>
            Tạo kế hoạch
          </button>
          <button className="btn" onClick={() => void handleImport()}>
            Nhập file (txt/md/epub/pdf)…
          </button>
          {error && <span style={{ color: 'var(--color-danger)', fontSize: 12 }}>{error}</span>}
        </div>
      </section>

      {doc && (
        <section className="section-card longform-pronunciation">
          <div className="longform-section-head">
            <div>
              <span className="workspace-kicker">PRONUNCIATION</span>
              <h2 className="section-title">Từ điển cách đọc</h2>
            </div>
            <button className="btn" onClick={addPronunciationRule}>Thêm quy tắc</button>
          </div>
          {doc.document.pronunciation_rules.length === 0 ? (
            <div className="longform-empty-row">Chưa có quy tắc phát âm riêng.</div>
          ) : (
            <div className="longform-rule-list">
              {doc.document.pronunciation_rules.map((rule, index) => (
                <div className="longform-rule-row" key={rule.rule_id}>
                  <input
                    aria-label={`Từ gốc ${index + 1}`}
                    placeholder="Từ gốc"
                    value={rule.source}
                    onChange={(event) => updatePronunciationRules(doc.document.pronunciation_rules.map((item) => item.rule_id === rule.rule_id ? { ...item, source: event.target.value } : item))}
                  />
                  <input
                    aria-label={`Cách đọc ${index + 1}`}
                    placeholder="Cách đọc"
                    value={rule.replacement}
                    onChange={(event) => updatePronunciationRules(doc.document.pronunciation_rules.map((item) => item.rule_id === rule.rule_id ? { ...item, replacement: event.target.value } : item))}
                  />
                  <select
                    aria-label={`Ngôn ngữ quy tắc ${index + 1}`}
                    value={rule.language}
                    onChange={(event) => updatePronunciationRules(doc.document.pronunciation_rules.map((item) => item.rule_id === rule.rule_id ? { ...item, language: event.target.value } : item))}
                  >
                    <option value="">Mọi ngôn ngữ</option>
                    {(statusQuery.data?.languages ?? []).map((code) => <option key={code} value={code}>{code}</option>)}
                  </select>
                  <label className="field-check compact"><input type="checkbox" checked={rule.case_sensitive} onChange={(event) => updatePronunciationRules(doc.document.pronunciation_rules.map((item) => item.rule_id === rule.rule_id ? { ...item, case_sensitive: event.target.checked } : item))} />Phân biệt hoa/thường</label>
                  <label className="field-check compact"><input type="checkbox" checked={rule.whole_word} onChange={(event) => updatePronunciationRules(doc.document.pronunciation_rules.map((item) => item.rule_id === rule.rule_id ? { ...item, whole_word: event.target.checked } : item))} />Nguyên từ</label>
                  <button className="btn danger" onClick={() => updatePronunciationRules(doc.document.pronunciation_rules.filter((item) => item.rule_id !== rule.rule_id))}>Xóa</button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {doc && (
        <section className="section-card">
          <div className="longform-section-head">
            <div>
              <span className="workspace-kicker">EDITOR</span>
              <h2 className="section-title">Kế hoạch ({doc.document.items.length} đoạn)</h2>
            </div>
            <span className="longform-editor-note">Nghe thử dùng đúng giọng, cách đọc và biểu cảm của từng dòng.</span>
          </div>
          {doc.issues.length > 0 && (
            <div className="longform-issues">
              {doc.issues.map((issue, index) => (
                <span key={`${issue.code}-${index}`} className={issue.severity}>{issue.message}</span>
              ))}
            </div>
          )}
          <div className="longform-chapter-bar">
            {doc.document.chapters.map((chapter, index) => (
              <div className="longform-chapter-item" key={chapter}>
                <button className="btn" onClick={() => renameChapter(chapter)}>{chapter}</button>
                <button
                  className="icon-btn"
                  title="Đưa chương lên"
                  disabled={index === 0}
                  onClick={() => void runOp({ op: 'move_chapter', chapter, delta: -1 })}
                >
                  ↑
                </button>
                <button
                  className="icon-btn"
                  title="Đưa chương xuống"
                  disabled={index === doc.document.chapters.length - 1}
                  onClick={() => void runOp({ op: 'move_chapter', chapter, delta: 1 })}
                >
                  ↓
                </button>
              </div>
            ))}
            <button className="btn accent" onClick={addChapter}>+ Chương</button>
          </div>
          <div
            className="longform-plan-scroll"
            style={{ height: LONGFORM_VIEWPORT_HEIGHT }}
            onScroll={(event) => setPlanScrollTop(event.currentTarget.scrollTop)}
          >
          <table className="data-table longform-plan-table">
            <thead>
              <tr>
                <th style={{ width: 110 }}>Chương</th>
                <th style={{ width: 120 }}>Giọng</th>
                <th>Lời thoại</th>
                <th style={{ width: 170 }}>Biểu cảm</th>
                <th style={{ width: 70 }}>Tốc độ</th>
                <th style={{ width: 70 }}>Âm lượng</th>
                <th style={{ width: 70 }}>Nghỉ (ms)</th>
                <th style={{ width: 270 }}></th>
              </tr>
            </thead>
            <tbody>
              {planStartIndex > 0 && <tr aria-hidden="true"><td colSpan={8} style={{ height: planStartIndex * LONGFORM_ROW_HEIGHT, padding: 0, border: 0 }} /></tr>}
              {visiblePlanItems.map((item: DocumentItem, visibleIndex: number) => {
                const index = planStartIndex + visibleIndex
                return (
                <tr key={item.item_id} style={{ height: LONGFORM_ROW_HEIGHT }}>
                  <td>
                    <select
                      value={item.chapter}
                      onChange={(event) => updateItemLocal(item.item_id, { chapter: event.target.value })}
                      onBlur={() => commitItem(item.item_id)}
                    >
                      {doc.document.chapters.map((chapter) => (
                        <option key={chapter} value={chapter}>
                          {chapter}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      value={item.speaker}
                      onChange={(event) => updateItemLocal(item.item_id, { speaker: event.target.value })}
                      onBlur={() => commitItem(item.item_id)}
                    />
                  </td>
                  <td>
                    <div className="longform-copy-fields">
                      <input
                        type="text"
                        value={item.text}
                        placeholder="Nội dung hiển thị"
                        onChange={(event) => updateItemLocal(item.item_id, { text: event.target.value })}
                        onBlur={() => commitItem(item.item_id)}
                      />
                      <input
                        type="text"
                        value={item.spoken_text}
                        placeholder="Cách đọc riêng (tùy chọn)"
                        onChange={(event) => updateItemLocal(item.item_id, { spoken_text: event.target.value })}
                        onBlur={() => commitItem(item.item_id)}
                      />
                      {item.preview_path && <audio controls preload="none" src={item.preview_path} />}
                    </div>
                  </td>
                  <td>
                    <div className="longform-expression-controls">
                      <select
                        value={item.emotion}
                        onChange={(event) => updateItemLocal(item.item_id, { emotion: event.target.value })}
                        onBlur={() => commitItem(item.item_id)}
                      >
                        <option value="">Tự nhiên</option>
                        <option value="calm">Bình tĩnh</option>
                        <option value="happy">Vui</option>
                        <option value="sad">Buồn</option>
                        <option value="angry">Giận dữ</option>
                        <option value="excited">Hào hứng</option>
                        <option value="whisper">Thì thầm</option>
                      </select>
                      <label><input type="checkbox" checked={item.emphasis} onChange={(event) => void runOp({ op: 'update', item_id: item.item_id, changes: { emphasis: event.target.checked } })} />Nhấn mạnh</label>
                      <label><input type="checkbox" checked={item.spell} onChange={(event) => void runOp({ op: 'update', item_id: item.item_id, changes: { spell: event.target.checked } })} />Đọc từng ký tự</label>
                    </div>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0.5}
                      max={1.5}
                      step={0.1}
                      value={item.speed}
                      onChange={(event) => updateItemLocal(item.item_id, { speed: Number(event.target.value) })}
                      onBlur={() => commitItem(item.item_id)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.1}
                      value={item.volume}
                      onChange={(event) => updateItemLocal(item.item_id, { volume: Number(event.target.value) })}
                      onBlur={() => commitItem(item.item_id)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      value={item.pause_after_ms}
                      onChange={(event) =>
                        updateItemLocal(item.item_id, { pause_after_ms: Number(event.target.value) })
                      }
                      onBlur={() => commitItem(item.item_id)}
                    />
                  </td>
                  <td>
                    <div className="longform-row-actions">
                      <TaskButton
                        label="Nghe thử"
                        onStart={() => handlePreviewStart(index)}
                        onFinish={(task) => handlePreviewDone(item.item_id, task)}
                      />
                      <button className="btn" title="Lên" onClick={() => void runOp({ op: 'move', item_id: item.item_id, delta: -1 })}>
                        ↑
                      </button>
                      <button className="btn" title="Xuống" onClick={() => void runOp({ op: 'move', item_id: item.item_id, delta: 1 })}>
                        ↓
                      </button>
                      <button className="btn" title="Tách dòng" onClick={() => void runOp({ op: 'split', item_id: item.item_id })}>
                        ⑂
                      </button>
                      <button
                        className="btn"
                        title="Gộp với dòng sau"
                        disabled={index >= doc.document.items.length - 1}
                        onClick={() =>
                          void runOp({
                            op: 'merge',
                            item_id: item.item_id,
                            second_id: doc.document.items[index + 1].item_id,
                          })
                        }
                      >
                        ⇊
                      </button>
                      <button className="btn danger" title="Xóa dòng" onClick={() => void runOp({ op: 'delete', item_id: item.item_id })}>
                        ✕
                      </button>
                    </div>
                  </td>
                </tr>
                )
              })}
              {planEndIndex < doc.document.items.length && <tr aria-hidden="true"><td colSpan={8} style={{ height: (doc.document.items.length - planEndIndex) * LONGFORM_ROW_HEIGHT, padding: 0, border: 0 }} /></tr>}
            </tbody>
          </table>
          </div>
          <button
            className="btn"
            style={{ marginTop: 10 }}
            onClick={() =>
              void runOp({
                op: 'add',
                after_id: doc.document.items[doc.document.items.length - 1]?.item_id ?? '',
                chapter: doc.document.chapters[0] ?? '',
              })
            }
          >
            + Thêm dòng
          </button>
        </section>
      )}

      {doc && (
        <section className="section-card">
          <h2 className="section-title">Render</h2>
          <div className="field-grid">
            <div className="field">
              <label>Thư mục xuất</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  type="text"
                  style={{ flex: 1 }}
                  value={outputDir}
                  onChange={(event) => {
                    setOutputDir(event.target.value)
                    markDirty()
                    void refreshResumeJobs(event.target.value)
                  }}
                />
                <button className="btn" onClick={() => void pickFolder().then((path) => { if (path) { setOutputDir(path); markDirty() } })}>
                  Chọn…
                </button>
              </div>
            </div>
            <div className="field">
              <label>Tên project</label>
              <input type="text" value={projectName} onChange={(event) => { setProjectName(event.target.value); markDirty() }} />
            </div>
            <div className="field">
              <label>Thiết bị</label>
              <select value={device} onChange={(event) => { setDevice(event.target.value); markDirty() }}>
                {(statusQuery.data?.devices ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Ngôn ngữ</label>
              <select value={language} onChange={(event) => { setLanguage(event.target.value); markDirty() }}>
                {(statusQuery.data?.languages ?? []).map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Khoảng nghỉ giữa đoạn (ms)</label>
              <input type="number" min={0} value={gapMs} onChange={(event) => { setGapMs(Number(event.target.value)); markDirty() }} />
            </div>
          </div>
          {doc.voice_names.length > 0 && (
            <div className="field-grid" style={{ marginTop: 10 }}>
              {doc.voice_names.map((voice) => (
                <div className="field" key={voice}>
                  <label>Giọng cho "{voice}"</label>
                  <select
                    value={castMap[voice] ?? ''}
                    onChange={(event) => { setCastMap((current) => ({ ...current, [voice]: event.target.value })); markDirty() }}
                  >
                    <option value="">(auto)</option>
                    {(profilesQuery.data ?? []).map((voice) => (
                      <option key={voice.voice_id} value={voice.selection.profile_id} disabled={!voice.compatibility.longform}>
                        {voice.name}{voice.compatibility.longform ? '' : ' · không tương thích'}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          {(exportMp3 || exportM4b) && (
            <div className="field-grid" style={{ marginTop: 10 }}>
              <div className="field">
                <label>Tiêu đề sách</label>
                <input type="text" value={title} onChange={(event) => { setTitle(event.target.value); markDirty() }} />
              </div>
              <div className="field">
                <label>Tác giả</label>
                <input type="text" value={author} onChange={(event) => { setAuthor(event.target.value); markDirty() }} />
              </div>
              <div className="field">
                <label>Ảnh bìa (đường dẫn)</label>
                <input type="text" value={coverPath} onChange={(event) => { setCoverPath(event.target.value); markDirty() }} />
              </div>
            </div>
          )}
          <div className="field-grid" style={{ marginTop: 10 }}>
            <div className="field-check">
              <input type="checkbox" id="ws-mp3" checked={exportMp3} onChange={(event) => { setExportMp3(event.target.checked); markDirty() }} />
              <label htmlFor="ws-mp3">Xuất MP3</label>
            </div>
            <div className="field-check">
              <input type="checkbox" id="ws-m4b" checked={exportM4b} onChange={(event) => { setExportM4b(event.target.checked); markDirty() }} />
              <label htmlFor="ws-m4b">Xuất M4B (audiobook)</label>
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="ws-stems"
                checked={exportStems}
                onChange={(event) => { setExportStems(event.target.checked); markDirty() }}
              />
              <label htmlFor="ws-stems">Giữ stems riêng từng đoạn</label>
            </div>
            <div className="field-check">
              <input type="checkbox" id="ws-mastering" checked={mastering} onChange={(event) => { setMastering(event.target.checked); markDirty() }} />
              <label htmlFor="ws-mastering">Mastering âm lượng</label>
            </div>
          </div>
          {mastering && (
            <div className="field-grid longform-mastering" style={{ marginTop: 10 }}>
              <div className="field">
                <label>Âm lượng mục tiêu (LUFS)</label>
                <input type="number" min={-24} max={-9} step={1} value={targetLufs} onChange={(event) => { setTargetLufs(Number(event.target.value)); markDirty() }} />
              </div>
              <div className="field">
                <label>True peak tối đa (dB)</label>
                <input type="number" min={-6} max={-0.1} step={0.1} value={truePeakDb} onChange={(event) => { setTruePeakDb(Number(event.target.value)); markDirty() }} />
              </div>
            </div>
          )}
          {resumeJobs.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--color-fg-subtle)', fontSize: 12, marginBottom: 6 }}>
                Job đang chạy dở trong thư mục xuất:
              </div>
              {resumeJobs.map((job) => (
                <div key={job.project_dir} style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--color-fg-muted)' }}>
                    {job.project_name} — {job.completed_spans}/{job.total_spans} đoạn ({job.status})
                  </span>
                  <button className="btn" onClick={() => void openPath(job.project_dir)}>
                    Mở
                  </button>
                  <TaskButton
                    label="Tiếp tục"
                    onStart={() => handleRenderStart(job.project_dir)}
                    onFinish={(task) => void handleRenderDone(task)}
                  />
                </div>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
            <TaskButton
              label="Render kế hoạch"
              variant="accent"
              onStart={() => handleRenderStart()}
              onFinish={(task) => void handleRenderDone(task)}
            />
            {result && (
              <button className="btn" onClick={() => void openPath(result.project_dir)}>
                Mở output
              </button>
            )}
          </div>
          {result && resultAudioUrl && (
            <div className="longform-result">
              <audio controls preload="metadata" src={resultAudioUrl} />
              <div>
                <strong>Hoàn tất {result.span_count} đoạn</strong>
                <span>{result.mp3_path ? 'MP3' : 'WAV'}{result.m4b_path ? ' · M4B' : ''}</span>
              </div>
            </div>
          )}
          {result && resultAudioUrl && (activeRenderProject.current || selectedProjectId) && <AudioPostPanel key={result.manifest_path} projectId={galaxyProjectId} workflowId={activeRenderProject.current || selectedProjectId} workspace="longform" projectDir={result.project_dir} title={projectName || 'Truyện và sách nói'} sources={[{ source_id: 'longform-master', label: 'Bản đọc hoàn chỉnh', path: result.wav_path, role: 'voice', preview_url: resultAudioUrl }]} />}
        </section>
      )}
    </div>
  )
}

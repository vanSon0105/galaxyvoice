import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchSettings } from '../../api/settings'
import { fetchProfiles, fetchOmniVoiceStatus } from '../../api/omnivoice'
import { openPath } from '../../api/voice'
import {
  createDocument,
  documentOp,
  addHistory,
  fetchHistory,
  fetchProjects,
  fetchResumeJobs,
  importSource,
  saveProject,
  startRender,
} from '../../api/workspaces'
import type {
  DocumentItem,
  LongformDocument,
  RenderResultPayload,
  ResumeJob,
  WorkspaceProject,
} from '../../api/workspaces'
import { TaskButton } from '../../components/TaskButton'
import { pickBookFile, pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'

type Kind = 'stories' | 'audiobook'

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
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<Kind>('stories')
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const profilesQuery = useQuery({ queryKey: ['omnivoice-profiles'], queryFn: fetchProfiles })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const projectsQuery = useQuery({
    queryKey: ['workspace-projects', kind],
    queryFn: () => fetchProjects(kind),
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
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1.0)
  const [castMap, setCastMap] = useState<Record<string, string>>({})
  const [gapMs, setGapMs] = useState(250)
  const [exportMp3, setExportMp3] = useState(true)
  const [exportM4b, setExportM4b] = useState(false)
  const [exportStems, setExportStems] = useState(false)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [coverPath, setCoverPath] = useState('')
  const [resumeJobs, setResumeJobs] = useState<ResumeJob[]>([])
  const [result, setResult] = useState<RenderResultPayload | null>(null)
  const [error, setError] = useState('')
  const sourceRef = useRef<HTMLTextAreaElement | null>(null)

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
    const settings = settingsQuery.data
    if (!settings) return
    setOutputDir(String(settings.omnivoice_output_dir ?? settings.output_dir ?? ''))
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    setLanguage(String(settings.omnivoice_language ?? 'vi'))
    setSpeed(Number(settings.omnivoice_speed ?? 1))
  }, [settingsQuery.data])

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
      const created = await createDocument(kind, source)
      setDoc(created)
      setResult(null)
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
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const runOp = async (op: Parameters<typeof documentOp>[2]) => {
    if (!doc) return
    try {
      const updated = await documentOp(doc.doc_id, doc.kind, op)
      setDoc(updated)
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
    const response = await startRender({
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
      title,
      author,
      cover_path: coverPath,
      resume_project_dir: resumeProjectDir,
    })
    return response.task_id
  }

  const handleRenderDone = async (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const completed = task.result as unknown as RenderResultPayload
    setResult(completed)
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
    void refreshResumeJobs(outputDir)
  }

  const handleSaveProject = async () => {
    if (!source.trim() && !doc) {
      setError('Chưa có nội dung để lưu project.')
      return
    }
    try {
      const saved = await saveProject({
        workspace: kind,
        name: projectName || 'longform',
        project_id: selectedProjectId,
        payload: {
          source: doc?.script || source,
          output_dir: outputDir,
          device,
          language,
          speed,
          cast_map: castMap,
          gap_ms: gapMs,
          export_mp3: exportMp3,
          export_m4b: exportM4b,
          export_stems: exportStems,
          title,
          author,
          cover_path: coverPath,
        },
      })
      setSelectedProjectId(saved.project_id)
      setProjectName(saved.name)
      await queryClient.invalidateQueries({ queryKey: ['workspace-projects', kind] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const handleLoadProject = async (project: WorkspaceProject) => {
    const payload = project.payload
    const loadedSource = String(payload.source ?? '')
    setSelectedProjectId(project.project_id)
    setProjectName(project.name)
    setSource(loadedSource)
    setOutputDir(String(payload.output_dir ?? outputDir))
    setDevice(String(payload.device ?? device))
    setLanguage(String(payload.language ?? language))
    setSpeed(Number(payload.speed ?? speed))
    setCastMap(
      payload.cast_map && typeof payload.cast_map === 'object'
        ? (payload.cast_map as Record<string, string>)
        : {},
    )
    setGapMs(Number(payload.gap_ms ?? gapMs))
    setExportMp3(Boolean(payload.export_mp3 ?? exportMp3))
    setExportM4b(Boolean(payload.export_m4b ?? exportM4b))
    setExportStems(Boolean(payload.export_stems ?? exportStems))
    setTitle(String(payload.title ?? ''))
    setAuthor(String(payload.author ?? ''))
    setCoverPath(String(payload.cover_path ?? ''))
    if (loadedSource.trim()) {
      try {
        setDoc(await createDocument(kind, loadedSource))
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    }
  }

  const updateItemLocal = (itemId: string, changes: Record<string, unknown>) => {
    if (!doc) return
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
      },
    })
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Project &amp; lịch sử</h2>
        <div className="toolbar-row">
          <select
            value={selectedProjectId}
            onChange={(event) => {
              const project = (projectsQuery.data ?? []).find(
                (item) => item.project_id === event.target.value,
              )
              if (project) void handleLoadProject(project)
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
            Lưu project
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
              setDoc(null)
              setResult(null)
            }}
          >
            Truyện nhiều vai
          </button>
          <button
            className={`seg-item${kind === 'audiobook' ? ' active' : ''}`}
            onClick={() => {
              setKind('audiobook')
              setSelectedProjectId('')
              setDoc(null)
              setResult(null)
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
          onChange={(event) => setSource(event.target.value)}
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
        <section className="section-card">
          <h2 className="section-title">Kế hoạch ({doc.document.items.length} đoạn)</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 110 }}>Chương</th>
                <th style={{ width: 120 }}>Giọng</th>
                <th>Lời thoại</th>
                <th style={{ width: 70 }}>Tốc độ</th>
                <th style={{ width: 70 }}>Âm lượng</th>
                <th style={{ width: 70 }}>Nghỉ (ms)</th>
                <th style={{ width: 190 }}></th>
              </tr>
            </thead>
            <tbody>
              {doc.document.items.map((item: DocumentItem, index: number) => (
                <tr key={item.item_id}>
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
                    <input
                      type="text"
                      style={{ width: '100%' }}
                      value={item.text}
                      onChange={(event) => updateItemLocal(item.item_id, { text: event.target.value })}
                      onBlur={() => commitItem(item.item_id)}
                    />
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
                    <div style={{ display: 'flex', gap: 4 }}>
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
              ))}
            </tbody>
          </table>
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
                    void refreshResumeJobs(event.target.value)
                  }}
                />
                <button className="btn" onClick={() => void pickFolder().then((path) => path && setOutputDir(path))}>
                  Chọn…
                </button>
              </div>
            </div>
            <div className="field">
              <label>Tên project</label>
              <input type="text" value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            </div>
            <div className="field">
              <label>Thiết bị</label>
              <select value={device} onChange={(event) => setDevice(event.target.value)}>
                {(statusQuery.data?.devices ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Ngôn ngữ</label>
              <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                {(statusQuery.data?.languages ?? []).map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Khoảng nghỉ giữa đoạn (ms)</label>
              <input type="number" min={0} value={gapMs} onChange={(event) => setGapMs(Number(event.target.value))} />
            </div>
          </div>
          {doc.voice_names.length > 0 && (
            <div className="field-grid" style={{ marginTop: 10 }}>
              {doc.voice_names.map((voice) => (
                <div className="field" key={voice}>
                  <label>Giọng cho "{voice}"</label>
                  <select
                    value={castMap[voice] ?? ''}
                    onChange={(event) => setCastMap((current) => ({ ...current, [voice]: event.target.value }))}
                  >
                    <option value="">(auto)</option>
                    {(profilesQuery.data ?? []).map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          {exportM4b && (
            <div className="field-grid" style={{ marginTop: 10 }}>
              <div className="field">
                <label>Tiêu đề sách</label>
                <input type="text" value={title} onChange={(event) => setTitle(event.target.value)} />
              </div>
              <div className="field">
                <label>Tác giả</label>
                <input type="text" value={author} onChange={(event) => setAuthor(event.target.value)} />
              </div>
              <div className="field">
                <label>Ảnh bìa (đường dẫn)</label>
                <input type="text" value={coverPath} onChange={(event) => setCoverPath(event.target.value)} />
              </div>
            </div>
          )}
          <div className="field-grid" style={{ marginTop: 10 }}>
            <div className="field-check">
              <input type="checkbox" id="ws-mp3" checked={exportMp3} onChange={(event) => setExportMp3(event.target.checked)} />
              <label htmlFor="ws-mp3">Xuất MP3</label>
            </div>
            <div className="field-check">
              <input type="checkbox" id="ws-m4b" checked={exportM4b} onChange={(event) => setExportM4b(event.target.checked)} />
              <label htmlFor="ws-m4b">Xuất M4B (audiobook)</label>
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="ws-stems"
                checked={exportStems}
                onChange={(event) => setExportStems(event.target.checked)}
              />
              <label htmlFor="ws-stems">Giữ stems riêng từng đoạn</label>
            </div>
          </div>
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
        </section>
      )}
    </div>
  )
}

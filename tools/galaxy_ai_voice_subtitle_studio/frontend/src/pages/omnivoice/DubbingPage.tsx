import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchSettings } from '../../api/settings'
import { fetchProfiles, fetchOmniVoiceStatus } from '../../api/omnivoice'
import { openPath } from '../../api/voice'
import { fetchDubbingPlan, startRender } from '../../api/workspaces'
import type { DubbingSegment, RenderResultPayload } from '../../api/workspaces'
import { TaskButton } from '../../components/TaskButton'
import { pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'

/** Dubbing workspace: SRT → speaker segments → render per-segment TTS. */
export function DubbingPage() {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const profilesQuery = useQuery({ queryKey: ['omnivoice-profiles'], queryFn: fetchProfiles })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })

  const [srtText, setSrtText] = useState('')
  const [segments, setSegments] = useState<DubbingSegment[]>([])
  const [issues, setIssues] = useState<{ code: string; segment_id: string; message: string; severity: string }[]>([])
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1.0)
  const [gapMs, setGapMs] = useState(250)
  const [exportMp3, setExportMp3] = useState(true)
  const [result, setResult] = useState<RenderResultPayload | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings) return
    setOutputDir(String(settings.omnivoice_output_dir ?? settings.output_dir ?? ''))
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    setLanguage(String(settings.omnivoice_language ?? 'vi'))
    setSpeed(Number(settings.omnivoice_speed ?? 1))
  }, [settingsQuery.data])

  const handlePlan = async () => {
    setError('')
    if (!srtText.trim()) {
      setError('Dán nội dung SRT trước.')
      return
    }
    try {
      const plan = await fetchDubbingPlan(srtText)
      setSegments(plan.segments)
      setIssues(plan.issues)
      setResult(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const updateSegment = (segmentId: string, changes: Partial<DubbingSegment>) => {
    setSegments((current) =>
      current.map((segment) =>
        segment.segment_id === segmentId ? { ...segment, ...changes } : segment,
      ),
    )
  }

  const handleRenderStart = async (): Promise<string> => {
    setError('')
    if (segments.length === 0) {
      setError('Tạo kế hoạch lồng tiếng trước khi render.')
      throw new Error('Tạo kế hoạch lồng tiếng trước khi render.')
    }
    const response = await startRender({
      kind: 'dubbing',
      segments,
      output_dir: outputDir,
      project_name: projectName || 'dubbing',
      device,
      language,
      speed,
      gap_ms: gapMs,
      export_mp3: exportMp3,
    })
    return response.task_id
  }

  const handleRenderDone = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setResult(task.result as unknown as RenderResultPayload)
    }
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Phụ đề nguồn (SRT)</h2>
        <textarea
          className="srt-editor"
          rows={8}
          placeholder={'1\n00:00:00,000 --> 00:00:03,000\nLan: Hôm nay trời đẹp quá!\n\n2\n00:00:03,000 --> 00:00:06,000\nMinh: Đúng vậy.'}
          value={srtText}
          onChange={(event) => setSrtText(event.target.value)}
        />
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <button className="btn accent" onClick={() => void handlePlan()}>
            Tạo kế hoạch lồng tiếng
          </button>
          {error && <span style={{ color: 'var(--color-danger)', fontSize: 12 }}>{error}</span>}
        </div>
      </section>

      {segments.length > 0 && (
        <section className="section-card">
          <h2 className="section-title">Đoạn lồng tiếng ({segments.length})</h2>
          {issues.length > 0 && (
            <div style={{ color: 'var(--color-warning)', fontSize: 12, marginBottom: 8 }}>
              {issues.map((issue) => issue.message).join(' · ')}
            </div>
          )}
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 150 }}>Thời gian</th>
                <th style={{ width: 110 }}>Người nói</th>
                <th>Lời thoại</th>
                <th style={{ width: 140 }}>Profile</th>
                <th style={{ width: 70 }}>Tốc độ</th>
                <th style={{ width: 90 }}></th>
              </tr>
            </thead>
            <tbody>
              {segments.map((segment, index) => (
                <tr key={segment.segment_id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    {`${(segment.start_ms / 1000).toFixed(1)}s–${(segment.end_ms / 1000).toFixed(1)}s`}
                  </td>
                  <td>
                    <input
                      type="text"
                      value={segment.speaker_id}
                      onChange={(event) => updateSegment(segment.segment_id, { speaker_id: event.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      style={{ width: '100%' }}
                      value={segment.text}
                      onChange={(event) => updateSegment(segment.segment_id, { text: event.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      value={segment.profile_id}
                      onChange={(event) => updateSegment(segment.segment_id, { profile_id: event.target.value })}
                    >
                      <option value="">(auto)</option>
                      {(profilesQuery.data ?? []).map((profile) => (
                        <option key={profile.profile_id} value={profile.profile_id}>
                          {profile.display_name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0.5}
                      max={1.5}
                      step={0.1}
                      value={segment.speed}
                      onChange={(event) => updateSegment(segment.segment_id, { speed: Number(event.target.value) })}
                    />
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button
                        className="btn"
                        title="Tách tại giữa"
                        onClick={() => {
                          const current = [...segments]
                          const text = segment.text.trim()
                          const middle = Math.floor(text.length / 2)
                          const splitMs = segment.start_ms + Math.round((segment.end_ms - segment.start_ms) / 2)
                          current.splice(index, 1, { ...segment, text: text.slice(0, middle), end_ms: splitMs }, {
                            ...segment,
                            segment_id: `${segment.segment_id}-b`,
                            text: text.slice(middle),
                            start_ms: splitMs,
                          })
                          setSegments(current)
                        }}
                      >
                        ⑂
                      </button>
                      <button
                        className="btn"
                        title="Gộp với đoạn sau"
                        disabled={index >= segments.length - 1}
                        onClick={() => {
                          const current = [...segments]
                          const next = current[index + 1]
                          current.splice(index, 2, {
                            ...segment,
                            end_ms: Math.max(segment.end_ms, next.end_ms),
                            text: `${segment.text} ${next.text}`.trim(),
                          })
                          setSegments(current)
                        }}
                      >
                        ⇊
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {segments.length > 0 && (
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
                  onChange={(event) => setOutputDir(event.target.value)}
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
              <label>Khoảng nghỉ (ms)</label>
              <input type="number" min={0} value={gapMs} onChange={(event) => setGapMs(Number(event.target.value))} />
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="dub-render-mp3"
                checked={exportMp3}
                onChange={(event) => setExportMp3(event.target.checked)}
              />
              <label htmlFor="dub-render-mp3">Xuất MP3</label>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
            <TaskButton label="Render lồng tiếng" variant="accent" onStart={handleRenderStart} onFinish={handleRenderDone} />
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

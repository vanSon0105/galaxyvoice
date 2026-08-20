import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchSettings } from '../../api/settings'
import type { AppSettings } from '../../api/settings'
import { fetchOmniVoiceStatus, startOmniVoiceBatch } from '../../api/omnivoice'
import type { BatchResultPayload } from '../../api/omnivoice'
import { openPath } from '../../api/voice'
import { TaskButton } from '../../components/TaskButton'
import { pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'

/** Batch / long-form voice generation (JSONL or line-per-item). */
export function BatchPage() {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })

  const settings: AppSettings | undefined = settingsQuery.data
  const [source, setSource] = useState('')
  const [longForm, setLongForm] = useState(false)
  const [combine, setCombine] = useState(false)
  const [gapMs, setGapMs] = useState(250)
  const [mode, setMode] = useState<'auto' | 'clone' | 'design'>('auto')
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('omnivoice-batch')
  const [modelId, setModelId] = useState('k2-fsa/OmniVoice')
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1.0)
  const [exportMp3, setExportMp3] = useState(true)
  const [formError, setFormError] = useState('')
  const [result, setResult] = useState<BatchResultPayload | null>(null)

  const seededRef = useRef(false)
  useEffect(() => {
    if (!settings || seededRef.current) return
    seededRef.current = true
    setOutputDir(String(settings.omnivoice_output_dir ?? settings.output_dir ?? ''))
    setModelId(String(settings.omnivoice_model_id ?? 'k2-fsa/OmniVoice'))
    setDevice(String(settings.omnivoice_device ?? 'auto'))
    setLanguage(String(settings.omnivoice_language ?? 'vi'))
    setSpeed(Number(settings.omnivoice_speed ?? 1))
    setExportMp3(settings.omnivoice_export_mp3 !== false)
    setMode((settings.omnivoice_batch_mode as 'auto' | 'clone' | 'design') ?? 'auto')
  }, [settings])

  const handleStart = async (): Promise<string> => {
    setFormError('')
    if (!source.trim()) {
      setFormError('Nhập ít nhất một dòng nội dung hoặc JSONL.')
      throw new Error('Nhập ít nhất một dòng nội dung hoặc JSONL.')
    }
    const response = await startOmniVoiceBatch({
      source,
      long_form: longForm,
      combine,
      gap_ms: gapMs,
      mode,
      output_dir: outputDir,
      project_name: projectName,
      model_id: modelId,
      device,
      language,
      speed,
      export_mp3: exportMp3,
    })
    return response.task_id
  }

  const handleDone = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setResult(task.result as unknown as BatchResultPayload)
    }
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Nội dung batch</h2>
        <textarea
          className="srt-editor"
          rows={10}
          placeholder={
            'Mỗi dòng là một câu, hoặc JSONL: {"id": "...", "text": "...", "language_id": "vi", "speed": 1.0}'
          }
          value={source}
          onChange={(event) => setSource(event.target.value)}
        />
        <div className="field-grid" style={{ marginTop: 10 }}>
          <div className="field-check">
            <input
              type="checkbox"
              id="ov-batch-longform"
              checked={longForm}
              onChange={(event) => setLongForm(event.target.checked)}
            />
            <label htmlFor="ov-batch-longform">Chế độ long-form (tách theo đoạn văn)</label>
          </div>
          <div className="field-check">
            <input
              type="checkbox"
              id="ov-batch-combine"
              checked={combine}
              onChange={(event) => setCombine(event.target.checked)}
            />
            <label htmlFor="ov-batch-combine">Ghép thành một file</label>
          </div>
          <div className="field">
            <label>Khoảng nghỉ khi ghép (ms)</label>
            <input
              type="number"
              min={0}
              max={5000}
              value={gapMs}
              onChange={(event) => setGapMs(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label>Chế độ</label>
            <select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}>
              <option value="auto">Tự chọn giọng</option>
              <option value="clone">Nhái giọng</option>
              <option value="design">Thiết kế giọng</option>
            </select>
          </div>
          <div className="field">
            <label>Thư mục xuất</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                type="text"
                style={{ flex: 1 }}
                value={outputDir}
                onChange={(event) => setOutputDir(event.target.value)}
              />
              <button
                className="btn"
                onClick={() => void pickFolder().then((path) => path && setOutputDir(path))}
              >
                Chọn…
              </button>
            </div>
          </div>
          <div className="field">
            <label>Tên project</label>
            <input
              type="text"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
            />
          </div>
          <div className="field">
            <label>Model</label>
            <input type="text" value={modelId} onChange={(event) => setModelId(event.target.value)} />
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
            <label>Tốc độ ({speed})</label>
            <input
              type="range"
              min={0.5}
              max={1.5}
              step={0.1}
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            />
          </div>
          <div className="field-check">
            <input
              type="checkbox"
              id="ov-batch-mp3"
              checked={exportMp3}
              onChange={(event) => setExportMp3(event.target.checked)}
            />
            <label htmlFor="ov-batch-mp3">Xuất thêm MP3</label>
          </div>
        </div>
      </section>

      {formError && (
        <div className="section-card" style={{ borderColor: 'rgba(220,118,111,0.4)' }}>
          <span style={{ color: 'var(--color-danger)', fontSize: 12.5 }}>{formError}</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <TaskButton
          label="Tạo batch"
          variant="accent"
          onStart={handleStart}
          onFinish={handleDone}
        />
        {result && (
          <button className="btn" onClick={() => void openPath(result.project_dir)}>
            Mở output
          </button>
        )}
      </div>
    </div>
  )
}

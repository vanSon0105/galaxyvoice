import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { fetchSettings } from '../../api/settings'
import type { AppSettings } from '../../api/settings'
import {
  fetchOmniVoiceStatus,
  fetchProfiles,
  installOmniVoiceRuntime,
  startOmniVoiceGenerate,
} from '../../api/omnivoice'
import { openPath } from '../../api/voice'
import type { GenerateResultPayload, OmniVoiceStatus } from '../../api/omnivoice'
import { TaskButton } from '../../components/TaskButton'
import { pickAudioFile, pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'

type Mode = 'auto' | 'clone' | 'design'

const MODE_LABELS: { code: Mode; label: string }[] = [
  { code: 'auto', label: 'Tự chọn giọng' },
  { code: 'clone', label: 'Nhái giọng' },
  { code: 'design', label: 'Thiết kế giọng' },
]

function str(settings: AppSettings | undefined, key: string, fallback = ''): string {
  return String(settings?.[key] ?? fallback)
}

function num(settings: AppSettings | undefined, key: string, fallback: number): number {
  const value = Number(settings?.[key])
  return Number.isFinite(value) && value !== 0 ? value : fallback
}

function bool(settings: AppSettings | undefined, key: string, fallback: boolean): boolean {
  const value = settings?.[key]
  return typeof value === 'boolean' ? value : fallback
}

/** OmniVoice studio: auto / clone / design generation. */
export function StudioPage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const profilesQuery = useQuery({ queryKey: ['omnivoice-profiles'], queryFn: fetchProfiles })
  const [searchParams] = useSearchParams()

  const settings = settingsQuery.data
  const status: OmniVoiceStatus | undefined = statusQuery.data

  const [mode, setMode] = useState<Mode>('auto')
  const [text, setText] = useState('')
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [modelId, setModelId] = useState('k2-fsa/OmniVoice')
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1.0)
  const [duration, setDuration] = useState('')
  const [exportMp3, setExportMp3] = useState(true)
  const [referenceAudio, setReferenceAudio] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [profileId, setProfileId] = useState('')
  const [saveProfileName, setSaveProfileName] = useState('')
  const [cloneInstruct, setCloneInstruct] = useState('')
  const [designValues, setDesignValues] = useState<Record<string, string>>({})
  const [customInstruct, setCustomInstruct] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [numStep, setNumStep] = useState(32)
  const [guidanceScale, setGuidanceScale] = useState(2.0)
  const [tShift, setTShift] = useState(0.1)
  const [formError, setFormError] = useState('')
  const [result, setResult] = useState<GenerateResultPayload | null>(null)

  const seededRef = { current: false }
  useEffect(() => {
    if (!settings || seededRef.current) return
    seededRef.current = true
    setOutputDir(str(settings, 'omnivoice_output_dir') || str(settings, 'output_dir'))
    setModelId(str(settings, 'omnivoice_model_id', 'k2-fsa/OmniVoice'))
    setDevice(str(settings, 'omnivoice_device', 'auto'))
    setLanguage(str(settings, 'omnivoice_language', 'vi'))
    setSpeed(num(settings, 'omnivoice_speed', 1))
    setNumStep(num(settings, 'omnivoice_num_step', 32))
    setGuidanceScale(num(settings, 'omnivoice_guidance_scale', 2))
    setTShift(num(settings, 'omnivoice_t_shift', 0.1))
    setExportMp3(bool(settings, 'omnivoice_export_mp3', true))
    setCloneInstruct(str(settings, 'omnivoice_clone_instruct'))
    setProfileId(str(settings, 'omnivoice_profile_id'))
  }, [settings])

  // Apply URL params from gallery selection
  useEffect(() => {
    const urlMode = searchParams.get('mode')
    if (urlMode && (urlMode === 'auto' || urlMode === 'clone' || urlMode === 'design')) {
      setMode(urlMode)
    }
    if (searchParams.get('gender')) setDesignValues(prev => ({ ...prev, gender: searchParams.get('gender')! }))
    if (searchParams.get('age')) setDesignValues(prev => ({ ...prev, age: searchParams.get('age')! }))
    if (searchParams.get('pitch')) setDesignValues(prev => ({ ...prev, pitch: searchParams.get('pitch')! }))
    if (searchParams.get('accent')) setDesignValues(prev => ({ ...prev, accent: searchParams.get('accent')! }))
    if (searchParams.get('style')) setDesignValues(prev => ({ ...prev, style: searchParams.get('style')! }))
    if (searchParams.get('language')) setLanguage(searchParams.get('language')!)
    if (searchParams.get('instruct')) setCustomInstruct(searchParams.get('instruct')!)
    if (searchParams.get('sample')) setText(searchParams.get('sample')!)
  }, [searchParams])

  const designInstruction = (): string => {
    const chosen = Object.values(designValues).filter(Boolean)
    const custom = customInstruct.trim()
    return [...chosen, custom].filter(Boolean).join(', ')
  }

  const handleStart = async (): Promise<string> => {
    setFormError('')
    if (!text.trim()) {
      setFormError('Nhập nội dung cần tạo giọng.')
      throw new Error('Nhập nội dung cần tạo giọng.')
    }
    if (mode === 'clone' && !profileId && !referenceAudio.trim()) {
      setFormError('Nhái giọng cần audio mẫu hoặc profile đã lưu.')
      throw new Error('Nhái giọng cần audio mẫu hoặc profile đã lưu.')
    }
    const response = await startOmniVoiceGenerate({
      mode,
      text,
      output_dir: outputDir,
      project_name: projectName,
      model_id: modelId,
      device,
      language,
      speed,
      duration: duration ? Number(duration) : null,
      export_mp3: exportMp3,
      reference_audio: referenceAudio,
      reference_text: referenceText,
      profile_id: profileId,
      save_profile_name: saveProfileName,
      instruct: mode === 'design' ? designInstruction() : cloneInstruct,
      num_step: numStep,
      guidance_scale: guidanceScale,
      t_shift: tShift,
    })
    return response.task_id
  }

  const handleDone = (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    setResult(task.result as unknown as GenerateResultPayload)
    // A saved profile may have been created; refresh the list.
    void queryClient.invalidateQueries({ queryKey: ['omnivoice-profiles'] })
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">OmniVoice runtime</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span
            style={{
              color: status?.installed ? 'var(--color-success)' : 'var(--color-warning)',
              fontSize: 12.5,
            }}
          >
            {status ? status.message : 'Đang kiểm tra…'}
          </span>
          {status && !status.installed && (
            <button
              className="btn accent"
              onClick={() => void installOmniVoiceRuntime().then(() =>
                queryClient.invalidateQueries({ queryKey: ['omnivoice-status'] }))
              }
            >
              Cài runtime local
            </button>
          )}
        </div>
      </section>

      <section className="section-card">
        <h2 className="section-title">Chế độ</h2>
        <div className="seg" role="tablist">
          {MODE_LABELS.map((item) => (
            <button
              key={item.code}
              role="tab"
              className={`seg-item${mode === item.code ? ' active' : ''}`}
              onClick={() => setMode(item.code)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <section className="section-card">
        <h2 className="section-title">Nội dung</h2>
        <textarea
          className="srt-editor"
          rows={5}
          placeholder="Nội dung cần đọc…"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="field-grid" style={{ marginTop: 10 }}>
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
              {(status?.devices ?? []).map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Ngôn ngữ</label>
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {(status?.languages ?? []).map((code) => (
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
          <div className="field">
            <label>Thời lượng (giây, trống = tự động)</label>
            <input type="number" min={0} value={duration} onChange={(event) => setDuration(event.target.value)} />
          </div>
          <div className="field-check">
            <input
              type="checkbox"
              id="ov-export-mp3"
              checked={exportMp3}
              onChange={(event) => setExportMp3(event.target.checked)}
            />
            <label htmlFor="ov-export-mp3">Xuất thêm MP3</label>
          </div>
        </div>
      </section>

      {mode === 'clone' && (
        <section className="section-card">
          <h2 className="section-title">Nhái giọng</h2>
          <div className="field-grid">
            <div className="field">
              <label>Audio mẫu</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  type="text"
                  style={{ flex: 1 }}
                  value={referenceAudio}
                  onChange={(event) => setReferenceAudio(event.target.value)}
                />
                <button
                  className="btn"
                  onClick={() => void pickAudioFile().then((path) => path && setReferenceAudio(path))}
                >
                  Chọn…
                </button>
              </div>
            </div>
            <div className="field">
              <label>Nội dung audio mẫu</label>
              <input
                type="text"
                value={referenceText}
                onChange={(event) => setReferenceText(event.target.value)}
              />
            </div>
            <div className="field">
              <label>Profile đã lưu</label>
              <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                <option value="">(dùng audio mẫu)</option>
                {(profilesQuery.data ?? []).map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {profile.display_name} [{profile.language}]
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Lưu thành profile mới (tên)</label>
              <input
                type="text"
                value={saveProfileName}
                onChange={(event) => setSaveProfileName(event.target.value)}
              />
            </div>
            <div className="field">
              <label>Hướng dẫn thêm</label>
              <input
                type="text"
                value={cloneInstruct}
                onChange={(event) => setCloneInstruct(event.target.value)}
              />
            </div>
          </div>
        </section>
      )}

      {mode === 'design' && (
        <section className="section-card">
          <h2 className="section-title">Thiết kế giọng</h2>
          <div className="field-grid">
            {(
              [
                ['gender', 'Giới tính'],
                ['age', 'Độ tuổi'],
                ['pitch', 'Cao độ'],
                ['style', 'Phong cách'],
                ['accent', 'Accent tiếng Anh'],
                ['dialect', 'Phương ngữ Trung'],
              ] as const
            ).map(([key, label]) => (
              <div className="field" key={key}>
                <label>{label}</label>
                <select
                  value={designValues[key] ?? ''}
                  onChange={(event) =>
                    setDesignValues((current) => ({ ...current, [key]: event.target.value }))
                  }
                >
                  {(status?.design_options[key] ?? []).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <div className="field">
              <label>Mô tả thêm</label>
              <input
                type="text"
                value={customInstruct}
                onChange={(event) => setCustomInstruct(event.target.value)}
              />
            </div>
          </div>
        </section>
      )}

      <section className="section-card">
        <h2 className="section-title">Thông số nâng cao</h2>
        <button className="btn" onClick={() => setShowAdvanced((current) => !current)}>
          {showAdvanced ? 'Thu gọn' : 'Hiện thông số'}
        </button>
        {showAdvanced && (
          <div className="field-grid" style={{ marginTop: 10 }}>
            <div className="field">
              <label>Số bước (4..64)</label>
              <input
                type="number"
                min={4}
                max={64}
                value={numStep}
                onChange={(event) => setNumStep(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label>Guidance scale (0..4)</label>
              <input
                type="number"
                min={0}
                max={4}
                step={0.1}
                value={guidanceScale}
                onChange={(event) => setGuidanceScale(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label>T-shift (0.01..1)</label>
              <input
                type="number"
                min={0.01}
                max={1}
                step={0.01}
                value={tShift}
                onChange={(event) => setTShift(Number(event.target.value))}
              />
            </div>
          </div>
        )}
      </section>

      {formError && (
        <div className="section-card" style={{ borderColor: 'rgba(220,118,111,0.4)' }}>
          <span style={{ color: 'var(--color-danger)', fontSize: 12.5 }}>{formError}</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <TaskButton
          label="Tạo giọng"
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

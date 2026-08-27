import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import {
  fetchOmniVoiceStatus,
  installOmniVoiceRuntime,
  type OmniVoiceStatus,
} from '../../api/omnivoice'
import { fetchSettings, type AppSettings } from '../../api/settings'
import {
  deleteStudioTake,
  fetchStudioTakes,
  rerunStudioTake,
  setStudioTakePrimary,
  setStudioTakeStarred,
  startStudioGeneration,
  studioTakeAudioUrl,
  type StudioTake,
  type StudioVoiceSource,
} from '../../api/studio'
import { openPath } from '../../api/voice'
import { fetchLibraryVoices, libraryVoiceRequest } from '../../api/voiceLibrary'
import { TaskButton } from '../../components/TaskButton'
import { AudioPostPanel } from '../../components/audio/AudioPostPanel'
import { WorkspaceLoading, WorkspaceState } from '../../components/WorkspaceState'
import { pickAudioFile, pickFolder } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'
import { useVoiceProject } from './VoiceProjectContext'

const VOICE_SOURCES: { value: StudioVoiceSource; label: string }[] = [
  { value: 'auto', label: 'Tự động' },
  { value: 'profile', label: 'Thư viện' },
  { value: 'reference', label: 'Audio mẫu' },
  { value: 'design', label: 'Thiết kế' },
]

function settingString(settings: AppSettings | undefined, key: string, fallback = ''): string {
  return String(settings?.[key] ?? fallback)
}

function settingNumber(settings: AppSettings | undefined, key: string, fallback: number): number {
  const value = Number(settings?.[key])
  return Number.isFinite(value) && value !== 0 ? value : fallback
}

function takeTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('vi-VN')
}

function TakePlayer({ take, slot }: { take: StudioTake; slot: string }) {
  return (
    <article className="studio-compare-slot">
      <div className="studio-compare-title">
        <span>{slot}</span>
        <strong>{take.title}</strong>
      </div>
      <audio controls preload="none" src={studioTakeAudioUrl(take)} />
      <small>{take.language} · {take.speed.toFixed(1)}x · {take.engine_id}</small>
    </article>
  )
}

export function StudioPage() {
  const { projectId, project } = useVoiceProject()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const statusQuery = useQuery({ queryKey: ['omnivoice-status'], queryFn: fetchOmniVoiceStatus })
  const voicesQuery = useQuery({ queryKey: ['voice-library-picker'], queryFn: () => fetchLibraryVoices() })
  const [historyQuery, setHistoryQuery] = useState('')
  const [starredOnly, setStarredOnly] = useState(false)
  const takesQuery = useQuery({
    queryKey: ['studio-takes', projectId, historyQuery, starredOnly],
    queryFn: () => fetchStudioTakes({ project_id: projectId, query: historyQuery, starred_only: starredOnly }),
  })

  const settings = settingsQuery.data
  const status: OmniVoiceStatus | undefined = statusQuery.data
  const [source, setSource] = useState<StudioVoiceSource>('auto')
  const [title, setTitle] = useState('Bản đọc mới')
  const [text, setText] = useState('')
  const [outputDir, setOutputDir] = useState('')
  const [modelId, setModelId] = useState('k2-fsa/OmniVoice')
  const [device, setDevice] = useState('auto')
  const [language, setLanguage] = useState('vi')
  const [speed, setSpeed] = useState(1)
  const [duration, setDuration] = useState('')
  const [exportWav, setExportWav] = useState(true)
  const [exportMp3, setExportMp3] = useState(true)
  const [profileId, setProfileId] = useState('')
  const [referenceAudio, setReferenceAudio] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [saveProfileName, setSaveProfileName] = useState('')
  const [consentConfirmed, setConsentConfirmed] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [numStep, setNumStep] = useState(32)
  const [guidanceScale, setGuidanceScale] = useState(2)
  const [tShift, setTShift] = useState(0.1)
  const [normalizeText, setNormalizeText] = useState(false)
  const [formError, setFormError] = useState('')
  const [latestTake, setLatestTake] = useState<StudioTake | null>(null)
  const [compareIds, setCompareIds] = useState<string[]>([])
  const selectedLibraryVoice = (voicesQuery.data ?? []).find((voice) => voice.voice_id === profileId)

  const seeded = useRef(false)
  useEffect(() => {
    if (!settings || seeded.current) return
    seeded.current = true
    setOutputDir(settingString(settings, 'omnivoice_output_dir') || settingString(settings, 'output_dir'))
    setModelId(settingString(settings, 'omnivoice_model_id', 'k2-fsa/OmniVoice'))
    setDevice(settingString(settings, 'omnivoice_device', 'auto'))
    setLanguage(settingString(settings, 'omnivoice_language', 'vi'))
    setSpeed(settingNumber(settings, 'omnivoice_speed', 1))
    setNumStep(settingNumber(settings, 'omnivoice_num_step', 32))
    setGuidanceScale(settingNumber(settings, 'omnivoice_guidance_scale', 2))
    setTShift(settingNumber(settings, 'omnivoice_t_shift', 0.1))
  }, [settings])

  useEffect(() => {
    const mode = searchParams.get('mode')
    if (mode === 'clone') setSource('reference')
    if (mode === 'design') setSource('design')
    if (searchParams.get('sample')) setText(searchParams.get('sample') ?? '')
    if (searchParams.get('language')) setLanguage(searchParams.get('language') ?? 'vi')
    if (searchParams.get('instruct')) setInstruction(searchParams.get('instruct') ?? '')
  }, [searchParams])

  useEffect(() => {
    setLatestTake(null)
    setCompareIds([])
  }, [projectId])

  const takes = useMemo(() => takesQuery.data ?? [], [takesQuery.data])
  const compareTakes = useMemo(
    () => compareIds.map((id) => takes.find((take) => take.take_id === id)).filter(Boolean) as StudioTake[],
    [compareIds, takes],
  )

  const refreshTakes = async () => {
    await queryClient.invalidateQueries({ queryKey: ['studio-takes'] })
  }

  const primaryMutation = useMutation({
    mutationFn: ({ takeId, primary }: { takeId: string; primary: boolean }) =>
      setStudioTakePrimary(takeId, primary),
    onSuccess: refreshTakes,
  })
  const starMutation = useMutation({
    mutationFn: ({ takeId, starred }: { takeId: string; starred: boolean }) =>
      setStudioTakeStarred(takeId, starred),
    onSuccess: refreshTakes,
  })
  const deleteMutation = useMutation({
    mutationFn: deleteStudioTake,
    onSuccess: async (_, takeId) => {
      setCompareIds((ids) => ids.filter((id) => id !== takeId))
      await refreshTakes()
    },
  })

  const toggleCompare = (takeId: string) => {
    setCompareIds((ids) => {
      if (ids.includes(takeId)) return ids.filter((id) => id !== takeId)
      return [...ids.slice(-1), takeId]
    })
  }

  const handleStart = async (): Promise<string> => {
    setFormError('')
    if (!projectId) throw new Error('Hãy chọn hoặc tạo một dự án trước khi tạo giọng.')
    if (!text.trim()) throw new Error('Nhập nội dung cần tạo giọng.')
    if (!exportWav && !exportMp3) throw new Error('Chọn ít nhất một định dạng đầu ra.')
    if (source === 'profile' && !selectedLibraryVoice) throw new Error('Chọn một giọng tương thích trong thư viện.')
    if (source === 'reference' && !referenceAudio.trim()) throw new Error('Chọn audio tham chiếu.')
    if (source === 'design' && !instruction.trim()) throw new Error('Nhập mô tả giọng cần thiết kế.')
    try {
      const selectedRequest = selectedLibraryVoice ? libraryVoiceRequest(selectedLibraryVoice) : null
      const response = await startStudioGeneration({
        project_id: projectId,
        title: title.trim() || 'Bản đọc mới',
        text,
        language,
        output_dir: outputDir,
        output_name: title.trim() || 'studio-take',
        model_id: modelId,
        device,
        speed,
        duration: duration ? Number(duration) : null,
        formats: [exportWav ? 'wav' : null, exportMp3 ? 'mp3' : null].filter(Boolean) as ('wav' | 'mp3')[],
        voice: {
          source: source === 'profile' && selectedRequest ? selectedRequest.source : source,
          profile_id: source === 'profile' ? selectedRequest?.profile_id : profileId,
          reference_audio: source === 'profile' ? selectedRequest?.reference_audio : referenceAudio,
          reference_text: source === 'profile' ? selectedRequest?.reference_text : referenceText,
          save_profile_name: saveProfileName,
          instruction: source === 'profile' ? selectedRequest?.instruction : instruction,
          consent_confirmed: consentConfirmed,
          consent_basis: consentConfirmed ? 'owner' : '',
          consent_statement: consentConfirmed ? 'Đã xác nhận trong Galaxy Studio' : '',
        },
        engine_options: { num_step: numStep, guidance_scale: guidanceScale, t_shift: tShift, normalize_text: normalizeText },
      })
      return response.task_id
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      setFormError(message)
      throw cause
    }
  }

  const handleDone = (task: TaskState) => {
    if (task.status !== 'done' || !task.result) return
    const payload = task.result as { take?: StudioTake }
    if (payload.take) setLatestTake(payload.take)
    void refreshTakes()
    void queryClient.invalidateQueries({ queryKey: ['voice-library'] })
    void queryClient.invalidateQueries({ queryKey: ['voice-library-picker'] })
  }

  const handleRerunDone = (task: TaskState) => {
    if (task.status === 'done') void refreshTakes()
  }

  return (
    <div className="studio-page">
      <div className="studio-layout">
        <main className="studio-compose">
          <section className="section-card studio-runtime-bar">
            <div>
              <span className={`status-dot ${status?.installed ? 'open' : 'closed'}`} />
              <strong>OmniVoice</strong>
              <small>{status?.message ?? 'Đang kiểm tra runtime...'}</small>
            </div>
            {status && !status.installed && (
              <button className="btn accent" type="button" onClick={() => void installOmniVoiceRuntime()}>
                Cài runtime
              </button>
            )}
          </section>

          <section className="section-card">
            <div className="section-header compact">
              <h2 className="section-title">Nội dung</h2>
              <span className="studio-counter">{text.trim().length.toLocaleString('vi-VN')} ký tự</span>
            </div>
            <div className="field-grid studio-title-row">
              <div className="field">
                <label htmlFor="studio-title">Tên bản đọc</label>
                <input id="studio-title" type="text" value={title} onChange={(event) => setTitle(event.target.value)} />
              </div>
              <div className="field">
                <label>Dự án</label>
                <input type="text" value={project?.name ?? 'Chưa chọn dự án'} disabled />
              </div>
            </div>
            <textarea
              className="studio-script"
              rows={9}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Nhập nội dung cần đọc..."
              aria-label="Nội dung cần đọc"
            />
          </section>

          <section className="section-card">
            <h2 className="section-title">Nguồn giọng</h2>
            <div className="seg studio-source-tabs" role="tablist">
              {VOICE_SOURCES.map((item) => (
                <button
                  className={`seg-item${source === item.value ? ' active' : ''}`}
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={source === item.value}
                  onClick={() => setSource(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="field-grid studio-source-fields">
              {source === 'profile' && (
                <div className="field field-wide">
                  <label>Giọng trong thư viện</label>
                  <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                    <option value="">Chọn giọng...</option>
                    {(voicesQuery.data ?? []).map((voice) => (
                      <option key={voice.voice_id} value={voice.voice_id} disabled={!voice.compatibility.studio}>
                        {voice.name} · {voice.language}{voice.compatibility.studio ? '' : ' · không tương thích'}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {source === 'reference' && (
                <>
                  <div className="field field-wide">
                    <label>Audio tham chiếu</label>
                    <div className="input-action">
                      <input value={referenceAudio} onChange={(event) => setReferenceAudio(event.target.value)} />
                      <button className="btn" type="button" onClick={() => void pickAudioFile().then((path) => path && setReferenceAudio(path))}>Chọn</button>
                    </div>
                  </div>
                  <div className="field">
                    <label>Transcript audio mẫu</label>
                    <input value={referenceText} onChange={(event) => setReferenceText(event.target.value)} />
                  </div>
                  <div className="field">
                    <label>Lưu vào thư viện với tên</label>
                    <input value={saveProfileName} onChange={(event) => setSaveProfileName(event.target.value)} />
                  </div>
                  {saveProfileName.trim() && <label className="field-check field-wide"><input type="checkbox" checked={consentConfirmed} onChange={(event) => setConsentConfirmed(event.target.checked)} /> Tôi có quyền sử dụng giọng nói này</label>}
                </>
              )}
              <div className="field field-wide">
                <label>{source === 'design' ? 'Mô tả giọng' : 'Hướng dẫn phát âm / ngữ điệu'}</label>
                <input
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder={source === 'design' ? 'Ví dụ: nữ trẻ, ấm áp, nhịp kể chuyện...' : 'Tên riêng, cách đọc số, nhịp và cảm xúc...'}
                />
              </div>
            </div>
          </section>

          <section className="section-card">
            <h2 className="section-title">Đầu ra</h2>
            <div className="field-grid">
              <div className="field field-wide">
                <label>Thư mục xuất</label>
                <div className="input-action">
                  <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
                  <button className="btn" type="button" onClick={() => void pickFolder().then((path) => path && setOutputDir(path))}>Chọn</button>
                </div>
              </div>
              <div className="field">
                <label>Ngôn ngữ</label>
                <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                  {(status?.languages ?? ['vi']).map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Thiết bị</label>
                <select value={device} onChange={(event) => setDevice(event.target.value)}>
                  {(status?.devices ?? [{ code: 'auto', label: 'Tự động' }]).map((option) => (
                    <option key={option.code} value={option.code}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Tốc độ <output>{speed.toFixed(1)}x</output></label>
                <input type="range" min={0.5} max={1.5} step={0.1} value={speed} onChange={(event) => setSpeed(Number(event.target.value))} />
              </div>
              <div className="field">
                <label>Thời lượng mục tiêu (giây)</label>
                <input type="number" min={0} value={duration} onChange={(event) => setDuration(event.target.value)} placeholder="Tự động" />
              </div>
              <div className="studio-format-row field-wide">
                <label><input type="checkbox" checked={exportWav} onChange={(event) => setExportWav(event.target.checked)} /> WAV</label>
                <label><input type="checkbox" checked={exportMp3} onChange={(event) => setExportMp3(event.target.checked)} /> MP3</label>
              </div>
            </div>
          </section>

          <section className="section-card studio-advanced">
            <button className="btn quiet" type="button" onClick={() => setShowAdvanced((value) => !value)}>
              {showAdvanced ? 'Ẩn thông số engine' : 'Thông số engine'}
            </button>
            {showAdvanced && (
              <div className="field-grid">
                <div className="field field-wide"><label>Model</label><input value={modelId} onChange={(event) => setModelId(event.target.value)} /></div>
                <div className="field"><label>Số bước</label><input type="number" min={4} max={64} value={numStep} onChange={(event) => setNumStep(Number(event.target.value))} /></div>
                <div className="field"><label>Guidance</label><input type="number" min={0} max={4} step={0.1} value={guidanceScale} onChange={(event) => setGuidanceScale(Number(event.target.value))} /></div>
                <div className="field"><label>T-shift</label><input type="number" min={0.01} max={1} step={0.01} value={tShift} onChange={(event) => setTShift(Number(event.target.value))} /></div>
                <label className="field-check"><input type="checkbox" checked={normalizeText} onChange={(event) => setNormalizeText(event.target.checked)} /> Chuẩn hóa văn bản</label>
              </div>
            )}
          </section>

          {formError && <div className="studio-error">{formError}</div>}
          <div className="studio-generate-bar">
            <TaskButton label="Tạo bản đọc" variant="accent" onStart={handleStart} onFinish={handleDone} disabled={!projectId} />
            <span>{projectId ? `Đang ghi vào ${project?.name ?? 'dự án hiện tại'}` : 'Bản đọc chưa gắn với dự án'}</span>
          </div>
        </main>

        <aside className="studio-results">
          <section className="section-card studio-latest">
            <div className="section-header compact">
              <h2 className="section-title">Bản nghe gần nhất</h2>
              {latestTake?.primary && <span className="studio-primary-badge">Bản chính</span>}
            </div>
            {latestTake ? (
              <>
                <strong>{latestTake.title}</strong>
                <audio controls preload="metadata" src={studioTakeAudioUrl(latestTake)} />
                <div className="studio-result-actions">
                  <button className="btn" type="button" onClick={() => void openPath(latestTake.project_dir)}>Mở thư mục</button>
                  {latestTake.formats.includes('wav') && <a className="btn" href={studioTakeAudioUrl(latestTake, 'wav', true)}>Tải WAV</a>}
                  {latestTake.formats.includes('mp3') && latestTake.mp3_path && <a className="btn" href={studioTakeAudioUrl(latestTake, 'mp3', true)}>Tải MP3</a>}
                </div>
              </>
            ) : (
              <WorkspaceState title="Chưa có bản nghe" />
            )}
          </section>

          {latestTake && (
            <AudioPostPanel
              key={latestTake.take_id}
              projectId={latestTake.project_id || projectId}
              workspace="studio"
              projectDir={latestTake.project_dir}
              title={latestTake.title}
              sources={[{ source_id: latestTake.take_id, label: latestTake.title, path: latestTake.wav_path, role: 'voice', preview_url: studioTakeAudioUrl(latestTake, 'wav') }]}
            />
          )}

          {compareTakes.length > 0 && (
            <section className="section-card studio-compare">
              <div className="section-header compact">
                <h2 className="section-title">So sánh A/B</h2>
                <button className="btn quiet" type="button" onClick={() => setCompareIds([])}>Đóng</button>
              </div>
              <div className="studio-compare-grid">
                {compareTakes.map((take, index) => <TakePlayer key={take.take_id} take={take} slot={index === 0 ? 'A' : 'B'} />)}
              </div>
            </section>
          )}

          <section className="section-card studio-history">
            <div className="section-header compact">
              <h2 className="section-title">Lịch sử bản đọc</h2>
              <span className="studio-counter">{takes.length}</span>
            </div>
            <div className="studio-history-tools">
              <input aria-label="Tìm lịch sử" value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Tìm bản đọc..." />
              <label><input type="checkbox" checked={starredOnly} onChange={(event) => setStarredOnly(event.target.checked)} /> Đã ghim</label>
            </div>
            {takesQuery.isPending ? (
              <WorkspaceLoading label="Đang đọc lịch sử..." />
            ) : takesQuery.isError ? (
              <WorkspaceState
                title="Không đọc được lịch sử"
                tone="error"
                action={<button className="btn" type="button" onClick={() => void takesQuery.refetch()}>Thử lại</button>}
              />
            ) : takes.length === 0 ? (
              <WorkspaceState title="Chưa có bản đọc" />
            ) : (
              <div className="studio-take-list">
                {takes.map((take) => (
                  <article className={`studio-take${take.primary ? ' primary' : ''}`} key={take.take_id}>
                    <div className="studio-take-head">
                      <div>
                        <strong>{take.title}</strong>
                        <small>{takeTime(take.created_at)} · {take.language} · {take.speed.toFixed(1)}x</small>
                      </div>
                      <div className="studio-take-flags">
                        {take.primary && <span>Bản chính</span>}
                        <button
                          className={`studio-pin${take.starred ? ' active' : ''}`}
                          type="button"
                          aria-label={`${take.starred ? 'Bỏ ghim' : 'Ghim'} ${take.title}`}
                          onClick={() => starMutation.mutate({ takeId: take.take_id, starred: !take.starred })}
                        >
                          {take.starred ? '★' : '☆'}
                        </button>
                      </div>
                    </div>
                    <p>{take.text}</p>
                    <audio controls preload="none" src={studioTakeAudioUrl(take)} />
                    <div className="studio-take-actions">
                      <label className="studio-compare-check">
                        <input
                          type="checkbox"
                          checked={compareIds.includes(take.take_id)}
                          onChange={() => toggleCompare(take.take_id)}
                          aria-label={`So sánh ${take.title}`}
                        /> A/B
                      </label>
                      <button
                        className="btn"
                        type="button"
                        aria-label={`Chọn ${take.title} làm bản chính`}
                        onClick={() => primaryMutation.mutate({ takeId: take.take_id, primary: !take.primary })}
                      >
                        {take.primary ? 'Bỏ bản chính' : 'Chọn bản chính'}
                      </button>
                      <TaskButton label="Chạy lại" onStart={() => rerunStudioTake(take.take_id).then((value) => value.task_id)} onFinish={handleRerunDone} />
                      <button className="btn" type="button" onClick={() => setLatestTake(take)}>Hậu kỳ</button>
                      <button className="btn" type="button" onClick={() => void openPath(take.project_dir)}>Mở</button>
                      <button className="btn danger" type="button" onClick={() => deleteMutation.mutate(take.take_id)}>Xóa</button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchSettings, fetchSettingsMeta } from '../../api/settings'
import type { AppSettings, SettingsMeta } from '../../api/settings'
import {
  fetchDraft,
  fetchEngines,
  fetchVoices,
  openPath,
  startExtractAudio,
  startGenerate,
  startTranscribe,
} from '../../api/voice'
import type {
  EngineInfo,
  ExtractResultPayload,
  GenerateResultPayload,
} from '../../api/voice'
import { TaskButton } from '../../components/TaskButton'
import { hasNativeDialogs, pickFolder, pickVideoFile } from '../../lib/dialogs'
import type { TaskState } from '../../ws/useTasks'
import { DraftEditor } from './DraftEditor'

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

/** Video Dubbing workspace: script → voice → SRT/MP3, audio extraction,
 *  subtitles with translation and an editable draft. */
export function DubPage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const metaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const enginesQuery = useQuery({ queryKey: ['voice-engines'], queryFn: fetchEngines })

  const settings = settingsQuery.data
  const meta: SettingsMeta | undefined = metaQuery.data

  const [script, setScript] = useState('')
  const [engine, setEngine] = useState('')
  const [voiceName, setVoiceName] = useState('')
  const [rate, setRate] = useState(0)
  const [volume, setVolume] = useState(100)
  const [pauseMs, setPauseMs] = useState(250)
  const [maxChars, setMaxChars] = useState(160)
  const [exportMp3, setExportMp3] = useState(true)
  const [keepSegments, setKeepSegments] = useState(true)
  const [videoPath, setVideoPath] = useState('')
  const [projectName, setProjectName] = useState('')
  const [exportWav, setExportWav] = useState(true)
  const [exportMp3Video, setExportMp3Video] = useState(true)
  const [sourceLang, setSourceLang] = useState('auto')
  const [targetLang, setTargetLang] = useState('vi')
  const [whisperModel, setWhisperModel] = useState('base')
  const [provider, setProvider] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [aiBaseUrl, setAiBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [device, setDevice] = useState('auto')
  const [outputDir, setOutputDir] = useState('')

  const [draftTaskId, setDraftTaskId] = useState<string | null>(null)
  const [generateResult, setGenerateResult] = useState<GenerateResultPayload | null>(null)
  const [extractResult, setExtractResult] = useState<ExtractResultPayload | null>(null)
  const [formError, setFormError] = useState('')

  const voiceQuery = useQuery({
    queryKey: ['voices', engine],
    queryFn: () => fetchVoices(engine),
    enabled: Boolean(engine),
  })

  // Seed the form from shared settings once they load.
  const seededRef = { current: false }
  useEffect(() => {
    if (!settings || seededRef.current) return
    seededRef.current = true
    setEngine(str(settings, 'tts_engine', 'edge'))
    setVoiceName(str(settings, 'voice_name'))
    setRate(num(settings, 'rate', 0))
    setVolume(num(settings, 'volume', 100))
    setPauseMs(num(settings, 'pause_ms', 250))
    setMaxChars(num(settings, 'max_chars', 160))
    setExportMp3(bool(settings, 'export_mp3', true))
    setKeepSegments(bool(settings, 'keep_segments', true))
    setSourceLang(str(settings, 'video_source_language', 'auto'))
    setTargetLang(str(settings, 'video_target_language', 'vi'))
    setWhisperModel(str(settings, 'whisper_model', 'base'))
    setProvider(str(settings, 'ai_provider', meta?.default_translation_provider ?? ''))
    setAiModel(str(settings, 'ai_model'))
    setAiBaseUrl(str(settings, 'ai_base_url'))
    setDevice(str(settings, 'voice_processing_device', 'auto'))
    setOutputDir(str(settings, 'output_dir'))
  }, [settings, meta])

  const engines: EngineInfo[] = enginesQuery.data ?? []

  // Pick a voice matching a language (culture prefix), like the tkinter tab.
  const selectVoiceForLanguage = (languageCode: string): boolean => {
    const normalized = languageCode.trim().toLowerCase()
    if (!normalized || normalized === 'auto' || normalized === 'none') return false
    const voices = voiceQuery.data ?? []
    const matching = voices.filter(
      (voice) =>
        voice.culture.trim().toLowerCase() === normalized ||
        voice.culture.trim().toLowerCase().startsWith(`${normalized}-`),
    )
    if (matching.length === 0) return false
    if (matching.some((voice) => voice.name === voiceName)) return true
    setVoiceName(matching[0].name)
    return true
  }

  const confirmDiscardDraft = (message: string): boolean => {
    if (!draftTaskId) return true
    return window.confirm(message)
  }

  const changeVideo = (path: string) => {
    if (!confirmDiscardDraft('Đổi video sẽ bỏ bản phụ đề hiện tại chưa export. Tiếp tục?')) {
      return
    }
    setDraftTaskId(null)
    setVideoPath(path)
    if (projectName === 'galaxy_project' || projectName === '') {
      const stem = path.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''
      setProjectName(stem)
    }
  }

  const handleGenerateDone = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      const result = task.result as unknown as GenerateResultPayload
      setGenerateResult(result)
      if (result.translated_text) {
        setScript(result.translated_text)
      }
    }
  }

  const handleExtractDone = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setExtractResult(task.result as unknown as ExtractResultPayload)
    }
  }

  const handleTranscribeDone = async (task: TaskState) => {
    if (task.status !== 'done') return
    setDraftTaskId(task.taskId)
    // Mirror the tkinter flow: load the subtitle script into the Script box
    // and pick a matching voice so Generate reads it immediately.
    try {
      const draft = await fetchDraft(task.taskId)
      if (draft.script_text.trim()) {
        setScript(draft.script_text)
        selectVoiceForLanguage(draft.script_language)
      }
    } catch {
      // Draft fetch is best-effort; the editor below surfaces its own errors.
    }
  }

  const browseVideo = async () => {
    const path = await pickVideoFile()
    if (path) {
      changeVideo(path)
    } else if (!hasNativeDialogs()) {
      setFormError('Cửa sổ hiện tại không hỗ trợ hộp thoại chọn file — hãy gõ trực tiếp đường dẫn video.')
    }
  }

  const browseOutput = async () => {
    const path = await pickFolder()
    if (path) {
      setOutputDir(path)
    } else if (!hasNativeDialogs()) {
      setFormError('Cửa sổ hiện tại không hỗ trợ hộp thoại chọn thư mục — hãy gõ trực tiếp đường dẫn.')
    }
  }

  const handleProviderChange = (code: string) => {
    setProvider(code)
    // Auto-fill provider defaults; the API key is intentionally kept as typed.
    const providerMeta = meta?.translation_providers.find((item) => item.code === code)
    if (providerMeta) {
      setAiModel(providerMeta.default_model)
      setAiBaseUrl(providerMeta.default_base_url)
    }
  }

  const commonVoiceOptions = () => ({
    output_dir: outputDir,
    project_name: projectName,
    voice_name: voiceName || null,
    rate,
    volume,
    pause_ms: pauseMs,
    max_chars: maxChars,
    export_mp3: exportMp3,
    keep_segments: keepSegments,
    engine,
  })

  const wantsTranslation = targetLang !== 'none' && !(sourceLang !== 'auto' && sourceLang === targetLang)

  const handleGenerateStart = async (): Promise<string> => {
    setFormError('')
    if (!script.trim()) {
      setFormError('Dán kịch bản trước khi tạo voice.')
      throw new Error('Dán kịch bản trước khi tạo voice.')
    }
    if (wantsTranslation && !selectVoiceForLanguage(targetLang)) {
      setFormError(
        `Chưa tải được giọng cho ngôn ngữ đích ${targetLang}. Bấm ↻ tải lại danh sách giọng rồi thử lại.`,
      )
      throw new Error('Chưa có giọng khớp ngôn ngữ đích.')
    }
    const response = await startGenerate({
      text: script,
      ...commonVoiceOptions(),
      source_language: sourceLang,
      target_language: targetLang,
      ai_provider: provider,
      ai_model: aiModel,
      ai_base_url: aiBaseUrl,
      ai_api_key: apiKey,
    })
    return response.task_id
  }

  const handleExtractStart = async (): Promise<string> => {
    setFormError('')
    if (!videoPath.trim()) {
      setFormError('Chọn video trước khi trích audio.')
      throw new Error('Chọn video trước khi trích audio.')
    }
    if (!exportWav && !exportMp3Video) {
      setFormError('Chọn WAV, MP3 hoặc cả hai.')
      throw new Error('Chọn WAV, MP3 hoặc cả hai.')
    }
    const response = await startExtractAudio({
      video_path: videoPath,
      output_dir: outputDir,
      project_name: projectName,
      export_wav: exportWav,
      export_mp3: exportMp3Video,
    })
    return response.task_id
  }

  const handleTranscribeStart = async (): Promise<string> => {
    setFormError('')
    if (!videoPath.trim()) {
      setFormError('Chọn video trước khi tạo phụ đề.')
      throw new Error('Chọn video trước khi tạo phụ đề.')
    }
    if (!confirmDiscardDraft('Tạo lại phụ đề sẽ bỏ bản hiện tại chưa export. Tiếp tục?')) {
      throw new Error('Đã hủy.')
    }
    const response = await startTranscribe({
      video_path: videoPath,
      output_dir: outputDir,
      project_name: projectName,
      source_language: sourceLang,
      target_language: targetLang,
      whisper_model: whisperModel,
      processing_device: device,
      ai_provider: provider,
      ai_model: aiModel,
      ai_base_url: aiBaseUrl,
      ai_api_key: apiKey,
    })
    return response.task_id
  }

  return (
    <div>
      <div className="page-grid">
        <section className="section-card">
          <h2 className="section-title">Kịch bản</h2>
          <textarea
            className="srt-editor"
            rows={10}
            placeholder="Dán kịch bản cần đọc tại đây…"
            value={script}
            onChange={(event) => setScript(event.target.value)}
          />
        </section>

        <section className="section-card">
          <h2 className="section-title">Giọng đọc</h2>
          <div className="field-grid">
            <div className="field">
              <label>Engine</label>
              <select value={engine} onChange={(event) => setEngine(event.target.value)}>
                {engines.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Giọng</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <select
                  style={{ flex: 1 }}
                  value={voiceName}
                  onChange={(event) => setVoiceName(event.target.value)}
                >
                  <option value="">(mặc định)</option>
                  {(voiceQuery.data ?? []).map((voice) => (
                    <option key={voice.name} value={voice.name}>
                      {voice.name}
                    </option>
                  ))}
                </select>
                <button
                  className="btn"
                  title="Tải lại danh sách giọng"
                  onClick={() => void queryClient.invalidateQueries({ queryKey: ['voices', engine] })}
                >
                  ↻
                </button>
              </div>
            </div>
            <div className="field">
              <label>Tốc độ ({rate})</label>
              <input
                type="range"
                min={-10}
                max={10}
                value={rate}
                onChange={(event) => setRate(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label>Âm lượng ({volume})</label>
              <input
                type="range"
                min={0}
                max={100}
                value={volume}
                onChange={(event) => setVolume(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label>Khoảng nghỉ giữa đoạn (ms)</label>
              <input
                type="number"
                min={0}
                max={1200}
                value={pauseMs}
                onChange={(event) => setPauseMs(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label>Độ dài đoạn tối đa (ký tự)</label>
              <input
                type="number"
                min={60}
                max={260}
                value={maxChars}
                onChange={(event) => setMaxChars(Number(event.target.value))}
              />
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="dub-export-mp3"
                checked={exportMp3}
                onChange={(event) => setExportMp3(event.target.checked)}
              />
              <label htmlFor="dub-export-mp3">Xuất thêm MP3</label>
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="dub-keep-segments"
                checked={keepSegments}
                onChange={(event) => setKeepSegments(event.target.checked)}
              />
              <label htmlFor="dub-keep-segments">Giữ các đoạn audio riêng lẻ</label>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
            <TaskButton
              label="Tạo voice"
              variant="accent"
              onStart={handleGenerateStart}
              onFinish={handleGenerateDone}
            />
            {generateResult && (
              <button className="btn" onClick={() => void openPath(generateResult.project_dir)}>
                Mở output
              </button>
            )}
          </div>
        </section>

        <section className="section-card">
          <h2 className="section-title">Video</h2>
          <div className="field-grid">
            <div className="field">
              <label>Video nguồn</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  type="text"
                  style={{ flex: 1 }}
                  value={videoPath}
                  onChange={(event) => changeVideo(event.target.value)}
                />
                <button className="btn" onClick={() => void browseVideo()}>
                  Chọn…
                </button>
              </div>
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
                <button className="btn" onClick={() => void browseOutput()}>
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
            <div className="field-check">
              <input
                type="checkbox"
                id="dub-video-wav"
                checked={exportWav}
                onChange={(event) => setExportWav(event.target.checked)}
              />
              <label htmlFor="dub-video-wav">Xuất WAV</label>
            </div>
            <div className="field-check">
              <input
                type="checkbox"
                id="dub-video-mp3"
                checked={exportMp3Video}
                onChange={(event) => setExportMp3Video(event.target.checked)}
              />
              <label htmlFor="dub-video-mp3">Xuất MP3</label>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
            <TaskButton label="Trích audio" onStart={handleExtractStart} onFinish={handleExtractDone} />
            {extractResult && (
              <button className="btn" onClick={() => void openPath(extractResult.project_dir)}>
                Mở output
              </button>
            )}
          </div>
        </section>

        <section className="section-card">
          <h2 className="section-title">Phụ đề</h2>
          <div className="field-grid">
            <div className="field">
              <label>Ngôn ngữ video nguồn</label>
              <select value={sourceLang} onChange={(event) => setSourceLang(event.target.value)}>
                {(meta?.source_languages ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Ngôn ngữ dịch</label>
              <select value={targetLang} onChange={(event) => setTargetLang(event.target.value)}>
                {(meta?.target_languages ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Model Whisper</label>
              <select
                value={whisperModel}
                onChange={(event) => setWhisperModel(event.target.value)}
              >
                {(meta?.whisper_models ?? []).map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Thiết bị xử lý</label>
              <select value={device} onChange={(event) => setDevice(event.target.value)}>
                {(meta?.processing_devices ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Nhà cung cấp AI dịch</label>
              <select value={provider} onChange={(event) => handleProviderChange(event.target.value)}>
                {(meta?.translation_providers ?? []).map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Model AI dịch</label>
              <input
                type="text"
                list="dub-ai-model-options"
                value={aiModel}
                onChange={(event) => setAiModel(event.target.value)}
              />
              <datalist id="dub-ai-model-options">
                {(
                  meta?.translation_providers.find((item) => item.code === provider)?.models ?? []
                ).map((model) => (
                  <option key={model} value={model} />
                ))}
              </datalist>
            </div>
            <div className="field">
              <label>Base URL</label>
              <input
                type="text"
                value={aiBaseUrl}
                onChange={(event) => setAiBaseUrl(event.target.value)}
              />
            </div>
            <div className="field">
              <label>API key (không lưu)</label>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <TaskButton label="Tạo phụ đề" onStart={handleTranscribeStart} onFinish={handleTranscribeDone} />
          </div>
        </section>
      </div>

      {formError && (
        <div className="section-card" style={{ borderColor: 'rgba(220,118,111,0.4)' }}>
          <span style={{ color: 'var(--color-danger)', fontSize: 12.5 }}>{formError}</span>
        </div>
      )}

      {draftTaskId && <DraftEditor taskId={draftTaskId} currentVideoPath={videoPath} />}
    </div>
  )
}

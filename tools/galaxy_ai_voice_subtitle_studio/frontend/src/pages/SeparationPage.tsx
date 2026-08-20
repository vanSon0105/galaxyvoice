import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteAudioPreset,
  fetchAudioMeta,
  fetchAudioModels,
  fetchAudioPresets,
  fetchAudioRuntime,
  installAudioRuntime,
  saveAudioPreset,
  startAudioSeparation,
} from '../api/audio'
import type { AudioPreset, SeparationResult } from '../api/audio'
import { fetchSettings, updateSettings } from '../api/settings'
import type { AppSettings } from '../api/settings'
import { openPath } from '../api/voice'
import { TaskButton } from '../components/TaskButton'
import { hasNativeDialogs, pickFolder, pickMediaFile } from '../lib/dialogs'
import type { TaskState } from '../ws/useTasks'

function settingString(settings: AppSettings | undefined, key: string, fallback: string): string {
  return String(settings?.[key] ?? fallback)
}

function settingBool(settings: AppSettings | undefined, key: string, fallback: boolean): boolean {
  return typeof settings?.[key] === 'boolean' ? Boolean(settings[key]) : fallback
}

export function SeparationPage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const metaQuery = useQuery({ queryKey: ['audio-meta'], queryFn: fetchAudioMeta })
  const modelsQuery = useQuery({ queryKey: ['audio-models'], queryFn: () => fetchAudioModels() })
  const presetsQuery = useQuery({ queryKey: ['audio-presets'], queryFn: fetchAudioPresets })

  const [inputPath, setInputPath] = useState('')
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [method, setMethod] = useState('mdx')
  const [modelFilename, setModelFilename] = useState('Kim_Vocal_2.onnx')
  const [outputFormat, setOutputFormat] = useState('WAV')
  const [segmentSize, setSegmentSize] = useState('256')
  const [overlap, setOverlap] = useState('Default')
  const [device, setDevice] = useState('auto')
  const [gpuConversion, setGpuConversion] = useState(true)
  const [vocalsOnly, setVocalsOnly] = useState(false)
  const [instrumentalOnly, setInstrumentalOnly] = useState(false)
  const [sampleMode, setSampleMode] = useState(false)
  const [selectedPreset, setSelectedPreset] = useState('Default')
  const [presetName, setPresetName] = useState('')
  const [result, setResult] = useState<SeparationResult | null>(null)
  const [message, setMessage] = useState('')

  const settings = settingsQuery.data
  const meta = metaQuery.data
  const seeded = useRef(false)
  useEffect(() => {
    if (!settings || seeded.current) return
    seeded.current = true
    setOutputDir(
      settingString(settings, 'audio_output_dir', settingString(settings, 'output_dir', '')),
    )
    setMethod(settingString(settings, 'audio_process_method', 'mdx'))
    setModelFilename(settingString(settings, 'audio_model_name', 'Kim_Vocal_2.onnx'))
    setOutputFormat(settingString(settings, 'audio_output_format', 'WAV'))
    setSegmentSize(settingString(settings, 'audio_segment_size', '256'))
    setOverlap(settingString(settings, 'audio_overlap', 'Default'))
    setDevice(settingString(settings, 'audio_processing_device', 'auto'))
    setGpuConversion(settingBool(settings, 'audio_gpu_conversion', true))
    setVocalsOnly(settingBool(settings, 'audio_vocals_only', false))
    setInstrumentalOnly(settingBool(settings, 'audio_instrumental_only', false))
    setSampleMode(settingBool(settings, 'audio_sample_mode', false))
    setSelectedPreset(settingString(settings, 'audio_saved_setting', 'Default'))
  }, [settings])

  const methodModels = useMemo(
    () => (modelsQuery.data ?? []).filter((model) => model.method === method),
    [modelsQuery.data, method],
  )
  const controls = meta?.method_controls[method]
  const allPresets = useMemo(
    () => ({ ...(presetsQuery.data?.builtin ?? {}), ...(presetsQuery.data?.custom ?? {}) }),
    [presetsQuery.data],
  )

  useEffect(() => {
    if (methodModels.length === 0) return
    if (!methodModels.some((model) => model.filename === modelFilename)) {
      setModelFilename(methodModels[0].filename)
    }
  }, [methodModels, modelFilename])

  useEffect(() => {
    if (!controls) return
    if (!controls.segment_values.includes(segmentSize)) setSegmentSize(controls.segment_default)
    if (!controls.overlap_values.includes(overlap)) setOverlap(controls.overlap_default)
  }, [controls, overlap, segmentSize])

  const selectedRuntimeDevice = gpuConversion ? device : 'cpu'
  const runtimeQuery = useQuery({
    queryKey: ['audio-runtime', selectedRuntimeDevice, method],
    queryFn: () => fetchAudioRuntime(selectedRuntimeDevice, method),
    enabled: Boolean(meta),
  })

  const currentPreset = (): AudioPreset => ({
    method,
    model_filename: modelFilename,
    output_format: outputFormat,
    segment_size: segmentSize,
    overlap,
    processing_device: device,
    gpu_conversion: gpuConversion,
    vocals_only: vocalsOnly,
    instrumental_only: instrumentalOnly,
    sample_mode: sampleMode,
  })

  const applyPreset = (name: string) => {
    setSelectedPreset(name)
    const preset = allPresets[name]
    if (!preset) return
    if (preset.method) setMethod(preset.method)
    if (preset.model_filename) setModelFilename(preset.model_filename)
    if (preset.output_format) setOutputFormat(preset.output_format)
    if (preset.segment_size) setSegmentSize(preset.segment_size)
    if (preset.overlap) setOverlap(preset.overlap)
    if (preset.processing_device) setDevice(preset.processing_device)
    if (typeof preset.gpu_conversion === 'boolean') setGpuConversion(preset.gpu_conversion)
    if (typeof preset.vocals_only === 'boolean') setVocalsOnly(preset.vocals_only)
    if (typeof preset.instrumental_only === 'boolean') {
      setInstrumentalOnly(preset.instrumental_only)
    }
    if (typeof preset.sample_mode === 'boolean') setSampleMode(preset.sample_mode)
  }

  const chooseInput = async () => {
    const path = await pickMediaFile()
    if (!path) {
      if (!hasNativeDialogs()) setMessage('Hãy nhập trực tiếp đường dẫn file media.')
      return
    }
    setInputPath(path)
    const stem = path.replace(/\\/g, '/').split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''
    setProjectName(`${stem}-separated`)
    setResult(null)
  }

  const chooseOutput = async () => {
    const path = await pickFolder()
    if (path) setOutputDir(path)
    else if (!hasNativeDialogs()) setMessage('Hãy nhập trực tiếp đường dẫn thư mục xuất.')
  }

  const savePreset = async () => {
    const name = presetName.trim()
    if (!name) {
      setMessage('Nhập tên cho preset tùy chỉnh.')
      return
    }
    try {
      await saveAudioPreset(name, currentPreset())
      setSelectedPreset(name)
      setPresetName('')
      setMessage(`Đã lưu preset “${name}”.`)
      await queryClient.invalidateQueries({ queryKey: ['audio-presets'] })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const deletePreset = async () => {
    if (!(selectedPreset in (presetsQuery.data?.custom ?? {}))) {
      setMessage('Chỉ preset tùy chỉnh mới có thể xóa.')
      return
    }
    try {
      await deleteAudioPreset(selectedPreset)
      applyPreset('Default')
      setMessage(`Đã xóa preset “${selectedPreset}”.`)
      await queryClient.invalidateQueries({ queryKey: ['audio-presets'] })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const start = async (): Promise<string> => {
    setMessage('')
    setResult(null)
    if (!inputPath.trim()) throw new Error('Chọn file audio hoặc video đầu vào.')
    if (!outputDir.trim()) throw new Error('Chọn thư mục xuất.')
    if (!modelFilename) throw new Error('Không tìm thấy model phù hợp với phương pháp đã chọn.')
    await updateSettings({
      audio_output_dir: outputDir,
      audio_process_method: method,
      audio_model_name: modelFilename,
      audio_output_format: outputFormat,
      audio_segment_size: segmentSize,
      audio_overlap: overlap,
      audio_processing_device: device,
      audio_gpu_conversion: gpuConversion,
      audio_vocals_only: vocalsOnly,
      audio_instrumental_only: instrumentalOnly,
      audio_sample_mode: sampleMode,
      audio_saved_setting: selectedPreset,
    })
    const response = await startAudioSeparation({
      input_path: inputPath,
      output_dir: outputDir,
      project_name: projectName,
      method,
      model_filename: modelFilename,
      output_format: outputFormat,
      segment_size: segmentSize,
      overlap,
      processing_device: device,
      gpu_conversion: gpuConversion,
      vocals_only: vocalsOnly,
      instrumental_only: instrumentalOnly,
      sample_mode: sampleMode,
    })
    return response.task_id
  }

  const onFinished = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setResult(task.result as SeparationResult)
      setMessage('Tách âm thanh hoàn tất.')
    } else if (task.status === 'failed') {
      setMessage(task.error ?? 'Tách âm thanh thất bại.')
    } else if (task.status === 'cancelled') {
      setMessage('Đã dừng tác vụ tách âm thanh.')
    }
  }

  return (
    <div className="separation-page">
      <header className="workspace-heading">
        <div>
          <h1>Tách âm thanh</h1>
          <p>Tách giọng hát, nhạc nền hoặc khử nhiễu bằng model UVR cục bộ.</p>
        </div>
        <div className={`runtime-pill ${runtimeQuery.data?.state ?? 'checking'}`}>
          <span className="status-dot" />
          {runtimeQuery.data?.message ?? 'Đang đọc trạng thái runtime...'}
        </div>
      </header>

      <div className="separation-grid">
        <div>
          <section className="section-card">
            <h2 className="section-title">Nguồn và đầu ra</h2>
            <div className="field-grid">
              <div className="field field-wide">
                <label>Audio hoặc video đầu vào</label>
                <div className="input-action">
                  <input value={inputPath} onChange={(event) => setInputPath(event.target.value)} />
                  <button className="btn" onClick={() => void chooseInput()}>Chọn file</button>
                </div>
              </div>
              <div className="field field-wide">
                <label>Thư mục xuất</label>
                <div className="input-action">
                  <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
                  <button className="btn" onClick={() => void chooseOutput()}>Chọn thư mục</button>
                </div>
              </div>
              <div className="field">
                <label>Tên project</label>
                <input type="text" value={projectName} onChange={(event) => setProjectName(event.target.value)} />
              </div>
              <div className="field">
                <label>Định dạng</label>
                <div className="seg">
                  {(meta?.formats ?? ['WAV', 'FLAC', 'MP3']).map((format) => (
                    <button
                      key={format}
                      className={`seg-item${outputFormat === format ? ' active' : ''}`}
                      onClick={() => setOutputFormat(format)}
                    >
                      {format}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="section-card">
            <div className="section-header compact">
              <div>
                <h2 className="section-title">Engine tách stem</h2>
                <p className="section-subtitle">Model được đọc từ thư mục Ultimate Vocal Remover hiện có.</p>
              </div>
              <button
                className="btn"
                onClick={() => void fetchAudioModels(true).then((models) => {
                  queryClient.setQueryData(['audio-models'], models)
                  setMessage(`Đã quét lại ${models.length} model UVR.`)
                }).catch((error: unknown) => setMessage(error instanceof Error ? error.message : String(error)))}
              >
                Làm mới model
              </button>
            </div>
            <div className="field-grid">
              <div className="field">
                <label>Phương pháp</label>
                <select value={method} onChange={(event) => setMethod(event.target.value)}>
                  {(meta?.methods ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Model</label>
                <select value={modelFilename} onChange={(event) => setModelFilename(event.target.value)}>
                  {methodModels.map((model) => <option key={model.filename} value={model.filename}>{model.label}</option>)}
                </select>
                {methodModels.length === 0 && <span className="field-hint error-text">Chưa tìm thấy model cho phương pháp này.</span>}
              </div>
              <div className="field">
                <label>{controls?.segment_label ?? 'Segment size'}</label>
                <select value={segmentSize} onChange={(event) => setSegmentSize(event.target.value)}>
                  {(controls?.segment_values ?? ['256']).map((value) => <option key={value}>{value}</option>)}
                </select>
              </div>
              <div className="field">
                <label>{controls?.overlap_label ?? 'Overlap'}</label>
                <select value={overlap} onChange={(event) => setOverlap(event.target.value)}>
                  {(controls?.overlap_values ?? ['Default']).map((value) => <option key={value}>{value}</option>)}
                </select>
              </div>
              <div className="field-check">
                <input id="audio-gpu" type="checkbox" checked={gpuConversion} onChange={(event) => setGpuConversion(event.target.checked)} />
                <label htmlFor="audio-gpu">Dùng tăng tốc GPU</label>
              </div>
              <div className="field">
                <label>Thiết bị xử lý</label>
                <select value={device} disabled={!gpuConversion} onChange={(event) => setDevice(event.target.value)}>
                  {(meta?.devices ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                </select>
              </div>
              <div className="field-check">
                <input id="audio-vocals" type="checkbox" checked={vocalsOnly} onChange={(event) => { setVocalsOnly(event.target.checked); if (event.target.checked) setInstrumentalOnly(false) }} />
                <label htmlFor="audio-vocals">Chỉ xuất giọng hát</label>
              </div>
              <div className="field-check">
                <input id="audio-instrumental" type="checkbox" checked={instrumentalOnly} onChange={(event) => { setInstrumentalOnly(event.target.checked); if (event.target.checked) setVocalsOnly(false) }} />
                <label htmlFor="audio-instrumental">Chỉ xuất nhạc nền</label>
              </div>
              <div className="field-check">
                <input id="audio-sample" type="checkbox" checked={sampleMode} onChange={(event) => setSampleMode(event.target.checked)} />
                <label htmlFor="audio-sample">Chế độ mẫu 30 giây</label>
              </div>
            </div>
          </section>
        </div>

        <aside>
          <section className="section-card">
            <h2 className="section-title">Preset</h2>
            <div className="field">
              <label>Thiết lập đã lưu</label>
              <select value={selectedPreset} onChange={(event) => applyPreset(event.target.value)}>
                {Object.keys(allPresets).map((name) => <option key={name}>{name}</option>)}
              </select>
            </div>
            <div className="preset-row">
              <input placeholder="Tên preset mới" value={presetName} onChange={(event) => setPresetName(event.target.value)} />
              <button className="btn" onClick={() => void savePreset()}>Lưu</button>
              <button className="btn danger" onClick={() => void deletePreset()}>Xóa</button>
            </div>
          </section>

          <section className="section-card runtime-card">
            <h2 className="section-title">Runtime cục bộ</h2>
            <dl className="runtime-details">
              <dt>Thiết bị</dt><dd>{runtimeQuery.data?.resolved_device ?? selectedRuntimeDevice}</dd>
              <dt>Model UVR</dt><dd>{meta?.uvr_root ?? 'Đang tải...'}</dd>
              <dt>Python</dt><dd>{meta?.runtime_path ?? 'Đang tải...'}</dd>
            </dl>
            <div className="toolbar-row">
              <button
                className="btn"
                onClick={() => void queryClient.fetchQuery({ queryKey: ['audio-runtime', selectedRuntimeDevice, method], queryFn: () => fetchAudioRuntime(selectedRuntimeDevice, method, true) })}
              >
                Kiểm tra lại
              </button>
              <button
                className="btn"
                disabled={!meta?.installer_available}
                onClick={() => void installAudioRuntime(selectedRuntimeDevice).then(() => setMessage('Đã mở bộ cài runtime trong cửa sổ riêng.')).catch((error: unknown) => setMessage(error instanceof Error ? error.message : String(error)))}
              >
                Cài / cập nhật engine
              </button>
            </div>
          </section>

          <section className="section-card action-card">
            <TaskButton
              label="Bắt đầu tách âm"
              variant="accent"
              onStart={start}
              onFinish={onFinished}
              disabled={methodModels.length === 0 || !runtimeQuery.data?.ready}
            />
            {message && <p className={message.includes('thất bại') ? 'error-text' : 'action-message'}>{message}</p>}
          </section>

          {result && (
            <section className="section-card">
              <div className="section-header compact">
                <h2 className="section-title">Stem đã tạo</h2>
                <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>
              </div>
              <div className="stem-list">
                {result.files.map((file) => (
                  <div className="stem-row" key={file.name}>
                    <span title={file.name}>{file.name}</span>
                    <audio controls preload="metadata" src={file.url} />
                  </div>
                ))}
              </div>
              {result.warnings.map((warning) => <p className="field-hint" key={warning}>{warning}</p>)}
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}

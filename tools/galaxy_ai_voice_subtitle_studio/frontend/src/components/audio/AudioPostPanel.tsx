import { useMemo, useRef, useState } from 'react'

import {
  exportAudio,
  discoverProjectAudio,
  fetchWaveform,
  type AudioExportResult,
  type AudioFormat,
  type AudioPostSource,
} from '../../api/audioPost'
import type { TaskState } from '../../ws/useTasks'
import { TaskButton } from '../TaskButton'

interface Props {
  projectId: string
  workflowId: string
  workspace: string
  projectDir: string
  title: string
  sources: AudioPostSource[]
}

interface SourceState extends AudioPostSource {
  selected: boolean
  gain_db: number
}

export function AudioPostPanel({ projectId, workflowId, workspace, projectDir, title, sources }: Props) {
  const [sourceState, setSourceState] = useState<SourceState[]>(() =>
    sources.map((source, index) => ({ ...source, selected: source.selected ?? index === 0, gain_db: source.gain_db ?? 0 })),
  )
  const [formats, setFormats] = useState<AudioFormat[]>(['wav', 'mp3'])
  const [preset, setPreset] = useState<'none' | 'voice_clean' | 'podcast'>('voice_clean')
  const [trimStart, setTrimStart] = useState(0)
  const [trimEnd, setTrimEnd] = useState('')
  const [gain, setGain] = useState(0)
  const [segmentStart, setSegmentStart] = useState(0)
  const [segmentEnd, setSegmentEnd] = useState(0)
  const [segmentGain, setSegmentGain] = useState(0)
  const [fadeIn, setFadeIn] = useState(0)
  const [fadeOut, setFadeOut] = useState(0)
  const [normalize, setNormalize] = useState(true)
  const [trimSilence, setTrimSilence] = useState(false)
  const [targetLufs, setTargetLufs] = useState(-16)
  const [artist, setArtist] = useState('')
  const [album, setAlbum] = useState('')
  const [waveform, setWaveform] = useState<number[]>([])
  const [durationMs, setDurationMs] = useState(0)
  const [playheadMs, setPlayheadMs] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<AudioExportResult | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [discovered, setDiscovered] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)

  const previewSource = useMemo(
    () => sourceState.find((source) => source.selected) ?? sourceState[0],
    [sourceState],
  )

  const toggleFormat = (format: AudioFormat) => {
    setFormats((items) => items.includes(format) ? items.filter((item) => item !== format) : [...items, format])
  }

  const loadWaveform = async () => {
    if (!previewSource) return
    setBusy(true)
    setMessage('')
    try {
      const data = await fetchWaveform(previewSource.path, projectDir, 256)
      setWaveform(data.peaks)
      setDurationMs(data.duration_ms)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const seekWaveform = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!audioRef.current || !durationMs) return
    const ratio = (event.clientX - event.currentTarget.getBoundingClientRect().left) / event.currentTarget.clientWidth
    const nextMs = Math.max(0, Math.min(1, ratio)) * durationMs
    audioRef.current.currentTime = nextMs / 1000
    setPlayheadMs(nextMs)
  }

  const seekWaveformByKeyboard = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!audioRef.current || !durationMs) return
    const currentMs = audioRef.current.currentTime * 1000
    const stepMs = event.shiftKey ? 10_000 : 1_000
    let nextMs = currentMs
    if (event.key === 'ArrowLeft') nextMs -= stepMs
    else if (event.key === 'ArrowRight') nextMs += stepMs
    else if (event.key === 'Home') nextMs = 0
    else if (event.key === 'End') nextMs = durationMs
    else return
    event.preventDefault()
    const bounded = Math.max(0, Math.min(durationMs, nextMs))
    audioRef.current.currentTime = bounded / 1000
    setPlayheadMs(bounded)
  }

  const startExport = async () => {
    if (!formats.length) {
      setMessage('Chọn ít nhất một định dạng.')
      throw new Error('Chọn ít nhất một định dạng.')
    }
    setMessage('Đang hậu kỳ và xuất audio...')
    const started = await exportAudio({
        project_id: projectId,
        workflow_id: workflowId,
        workspace,
        project_dir: projectDir,
        title,
        sources: sourceState.map((source) => ({
          source_id: source.source_id,
          path: source.path,
          role: source.role,
          selected: source.selected,
          gain_db: source.gain_db,
        })),
        formats,
        chain: {
          trim_start_ms: trimStart,
          trim_end_ms: trimEnd ? Number(trimEnd) : null,
          gain_db: gain,
          segment_gains: segmentEnd > segmentStart
            ? [{ start_ms: segmentStart, end_ms: segmentEnd, gain_db: segmentGain }]
            : [],
          fade_in_ms: fadeIn,
          fade_out_ms: fadeOut,
          normalize,
          target_lufs: targetLufs,
          true_peak_db: -1,
          loudness_range: 11,
          preset,
          trim_silence: trimSilence,
        },
        metadata: { title, artist, album, comment: `Galaxy ${workspace} export` },
        sample_rate: 48_000,
        channels: 2,
        bitrate_kbps: 192,
    })
    return started.task_id
  }

  const finishExport = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setResult(task.result as AudioExportResult)
      setMessage('Đã xuất và ghi manifest vào project.')
      return
    }
    if (task.status === 'cancelled') {
      setMessage('Đã hủy xuất audio.')
      return
    }
    setMessage(task.error || 'Xuất audio thất bại.')
  }

  const expandPanel = async () => {
    setExpanded(true)
    if (discovered) return
    setDiscovered(true)
    try {
      const found = await discoverProjectAudio(projectDir)
      setSourceState((current) => {
        const paths = new Set(current.map((source) => source.path.toLocaleLowerCase()))
        return [...current, ...found.filter((source) => !paths.has(source.path.toLocaleLowerCase())).map((source) => ({ ...source, selected: false, gain_db: source.gain_db ?? 0 }))]
      })
    } catch {
      // Explicit sources remain usable when discovery is unavailable.
    }
  }

  return (
    <details className="audio-post section-card" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary onClick={() => { if (!expanded) void expandPanel() }}><span>Hậu kỳ & xuất audio</span><small>Gain, mastering, waveform, stem và metadata</small></summary>
      {expanded && <div className="audio-post-body">
        {previewSource?.preview_url && <audio ref={audioRef} controls preload="metadata" src={previewSource.preview_url} onTimeUpdate={(event) => setPlayheadMs(event.currentTarget.currentTime * 1000)} />}
        <div
          className="audio-waveform"
          role="slider"
          tabIndex={previewSource?.preview_url ? 0 : -1}
          onClick={seekWaveform}
          onKeyDown={seekWaveformByKeyboard}
          aria-label="Vị trí phát audio"
          aria-valuemin={0}
          aria-valuemax={durationMs}
          aria-valuenow={Math.round(playheadMs)}
          aria-valuetext={`${(playheadMs / 1000).toFixed(1)} giây`}
        >
          {waveform.length
            ? waveform.map((peak, index) => <i key={index} style={{ height: `${Math.max(3, peak * 100)}%` }} />)
            : <button className="btn quiet" type="button" disabled={busy || !previewSource} onClick={(event) => { event.stopPropagation(); void loadWaveform() }}>Tải dạng sóng</button>}
        </div>

        <div className="audio-source-list">
          {sourceState.map((source) => (
            <div key={source.source_id} className="audio-source-row">
              <label><input type="checkbox" checked={source.selected} onChange={(event) => setSourceState((items) => items.map((item) => item.source_id === source.source_id ? { ...item, selected: event.target.checked } : item))} />{source.label}<small>{source.role}</small></label>
              <label>Gain dB<input type="number" min={-60} max={24} step={0.5} value={source.gain_db} onChange={(event) => setSourceState((items) => items.map((item) => item.source_id === source.source_id ? { ...item, gain_db: Number(event.target.value) } : item))} /></label>
            </div>
          ))}
        </div>

        <div className="field-grid compact audio-post-grid">
          <div className="field"><label>Preset</label><select value={preset} onChange={(event) => setPreset(event.target.value as typeof preset)}><option value="none">Không xử lý màu âm</option><option value="voice_clean">Voice sạch</option><option value="podcast">Podcast</option></select></div>
          <div className="field"><label>Gain tổng (dB)</label><input type="number" min={-60} max={24} step={0.5} value={gain} onChange={(event) => setGain(Number(event.target.value))} /></div>
          <div className="field"><label>Cắt đầu (ms)</label><input type="number" min={0} value={trimStart} onChange={(event) => setTrimStart(Number(event.target.value))} /></div>
          <div className="field"><label>Cắt cuối tại (ms)</label><input type="number" min={1} value={trimEnd} placeholder="Giữ đến hết" onChange={(event) => setTrimEnd(event.target.value)} /></div>
          <div className="field"><label>Fade in (ms)</label><input type="number" min={0} value={fadeIn} onChange={(event) => setFadeIn(Number(event.target.value))} /></div>
          <div className="field"><label>Fade out (ms)</label><input type="number" min={0} value={fadeOut} onChange={(event) => setFadeOut(Number(event.target.value))} /></div>
          <div className="field"><label>Đoạn gain từ (ms)</label><input type="number" min={0} value={segmentStart} onChange={(event) => setSegmentStart(Number(event.target.value))} /></div>
          <div className="field"><label>Đến (ms)</label><input type="number" min={0} value={segmentEnd} onChange={(event) => setSegmentEnd(Number(event.target.value))} /></div>
          <div className="field"><label>Gain đoạn (dB)</label><input type="number" min={-60} max={24} step={0.5} value={segmentGain} onChange={(event) => setSegmentGain(Number(event.target.value))} /></div>
          <div className="field"><label>Target LUFS</label><input type="number" min={-36} max={-5} value={targetLufs} onChange={(event) => setTargetLufs(Number(event.target.value))} /></div>
          <div className="field"><label>Nghệ sĩ</label><input value={artist} onChange={(event) => setArtist(event.target.value)} /></div>
          <div className="field"><label>Album</label><input value={album} onChange={(event) => setAlbum(event.target.value)} /></div>
        </div>
        <div className="audio-post-options">
          <label><input type="checkbox" checked={normalize} onChange={(event) => setNormalize(event.target.checked)} /> Chuẩn hóa loudness</label>
          <label><input type="checkbox" checked={trimSilence} onChange={(event) => setTrimSilence(event.target.checked)} /> Cắt im lặng đầu/cuối</label>
          {(['wav', 'mp3', 'flac', 'm4a'] as AudioFormat[]).map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={() => toggleFormat(format)} /> {format.toUpperCase()}</label>)}
        </div>
        <div className="audio-post-actions">
          <TaskButton
            label="Xuất bản hậu kỳ"
            variant="accent"
            onStart={startExport}
            onFinish={finishExport}
          />
          {result && Object.entries(result.media_urls).map(([format, url]) => <a className="btn" key={format} href={`${url}&download=true`}>Tải {format.toUpperCase()}</a>)}
        </div>
        {result && (result.media_urls.mp3 || result.media_urls.wav || result.media_urls.m4a || result.media_urls.flac) && <audio controls preload="metadata" src={result.media_urls.mp3 || result.media_urls.wav || result.media_urls.m4a || result.media_urls.flac} />}
        {message && <p className="audio-post-message">{message}</p>}
      </div>}
    </details>
  )
}

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { startBatchRun, type BatchRun } from '../api/batch'
import { loadEditorCues, loadEditorMedia, startEditorExport } from '../api/editor'
import type { EditorExportResult, EditorMedia, EditorSubtitleAsset } from '../api/editor'
import { fetchSettings, fetchSettingsMeta, updateSettings } from '../api/settings'
import { openPath } from '../api/voice'
import { fetchLibraryVoices, libraryVoiceRequest } from '../api/voiceLibrary'
import type { LibraryVoice } from '../api/voiceLibrary'
import { Timeline } from '../components/timeline/Timeline'
import { clamp, formatClock, parseClock } from '../components/timeline/geometry'
import {
  clipDuration,
  clipEnd,
  createDefaultTracks,
  createTrack,
  cueWithId,
  editorDuration,
  mediaClip,
  placeAudioClips,
  reindexTrackCues,
} from '../components/timeline/tracks'
import type {
  EditorTrack,
  EditorTrackKind,
  TimelineCue,
  TimelineMediaClip,
  TimelineSelection,
} from '../components/timeline/tracks'
import { useActiveProjectId } from '../hooks/useActiveProjectId'
import { hasNativeDialogs, pickAudioFile, pickFolder, pickSrtFile, pickVideoFile } from '../lib/dialogs'
import { useTasks } from '../ws/useTasks'
import { isTaskActive } from '../ws/types'

type EditorMediaAsset<K extends 'video' | 'audio'> = Omit<EditorMedia, 'kind'> & { id: string; kind: K }
type EditorAsset = EditorMediaAsset<'video'> | EditorMediaAsset<'audio'> | ({ id: string; kind: 'subtitle' } & EditorSubtitleAsset)
type TtsScope = 'selected' | 'track' | 'all'

interface PendingSpeech {
  itemId: string
  trackId: string
  cueId: string
  startMs: number
}

function numberSetting(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringSetting(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function fitCues(cues: TimelineCue[], durationMs: number): TimelineCue[] {
  if (!cues.length || durationMs <= 0) return cues
  const sorted = [...cues].sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms)
  const first = sorted[0].start_ms
  const last = Math.max(...sorted.map((cue) => cue.end_ms))
  const scale = durationMs / Math.max(1, last - first)
  return reindexTrackCues(sorted.map((cue) => {
    const startMs = Math.round((cue.start_ms - first) * scale)
    return { ...cue, start_ms: startMs, end_ms: Math.min(durationMs, Math.max(startMs + 1, Math.round((cue.end_ms - first) * scale))) }
  }))
}

export function EditorPage() {
  const galaxyProjectId = useActiveProjectId()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const settingsMetaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const voicesQuery = useQuery({ queryKey: ['voice-library-picker'], queryFn: () => fetchLibraryVoices() })
  const { tasks, cancelTask } = useTasks()
  const videoRef = useRef<HTMLVideoElement>(null)
  const seeded = useRef(false)
  const handledSpeechTask = useRef('')

  const [assets, setAssets] = useState<EditorAsset[]>([])
  const [tracks, setTracks] = useState<EditorTrack[]>(createDefaultTracks)
  const [selection, setSelection] = useState<TimelineSelection | null>(null)
  const [playheadMs, setPlayheadMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [zoom, setZoom] = useState(8)
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [resolution, setResolution] = useState('original')
  const [fps, setFps] = useState('source')
  const [encoder, setEncoder] = useState('auto')
  const [audioMode, setAudioMode] = useState('mix')
  const [sourceVolume, setSourceVolume] = useState(100)
  const [externalVolume, setExternalVolume] = useState(100)
  const [fontSize, setFontSize] = useState(22)
  const [subtitleMargin, setSubtitleMargin] = useState(36)
  const [quality, setQuality] = useState(20)
  const [manualPath, setManualPath] = useState('')
  const [message, setMessage] = useState('')
  const [previewError, setPreviewError] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [result, setResult] = useState<EditorExportResult | null>(null)
  const [voiceId, setVoiceId] = useState('')
  const [ttsScope, setTtsScope] = useState<TtsScope>('selected')
  const [ttsTaskId, setTtsTaskId] = useState('')
  const [pendingSpeech, setPendingSpeech] = useState<PendingSpeech[]>([])

  const exportTask = taskId ? tasks.find((item) => item.taskId === taskId) : undefined
  const speechTask = ttsTaskId ? tasks.find((item) => item.taskId === ttsTaskId) : undefined
  const running = isTaskActive(exportTask?.status)
  const speechRunning = isTaskActive(speechTask?.status)
  const durationMs = Math.max(1, editorDuration(tracks))
  const videoTrackClips = useMemo(
    () => tracks.flatMap((track, trackOrder) => track.kind === 'video' && track.enabled ? track.clips.map((clip) => ({ track, trackOrder, clip })) : []),
    [tracks],
  )
  const audioTrackClips = useMemo(
    () => tracks.flatMap((track, trackOrder) => track.kind === 'audio' && track.enabled ? track.clips.map((clip) => ({ track, trackOrder, clip })) : []),
    [tracks],
  )
  const primaryVideo = videoTrackClips[0]?.clip ?? null
  const previewClip = videoTrackClips.find(({ clip }) => clip.timeline_start_ms <= playheadMs && clipEnd(clip) > playheadMs)?.clip ?? primaryVideo
  const activeAudioClips = audioTrackClips.filter(({ clip }) => clip.timeline_start_ms <= playheadMs && clipEnd(clip) > playheadMs)
  const selectedTrack = selection ? tracks.find((track) => track.id === selection.trackId) : undefined
  const activeSubtitleTrack = selectedTrack?.kind === 'subtitle'
    ? selectedTrack
    : tracks.find((track): track is Extract<EditorTrack, { kind: 'subtitle' }> => track.kind === 'subtitle')
  const activeCue = activeSubtitleTrack && selection?.trackId === activeSubtitleTrack.id
    ? activeSubtitleTrack.cues.find((cue) => cue.id === selection.itemId) ?? null
    : null
  const selectedClip = selectedTrack && selectedTrack.kind !== 'subtitle' && selection
    ? selectedTrack.clips.find((clip) => clip.id === selection.itemId) ?? null
    : null
  const selectedVoice = (voicesQuery.data ?? []).find((voice) => voice.voice_id === voiceId)
  const subtitleAtPlayhead = useMemo(() => tracks
    .filter((track): track is Extract<EditorTrack, { kind: 'subtitle' }> => track.kind === 'subtitle' && track.enabled)
    .flatMap((track) => track.cues)
    .find((cue) => cue.start_ms <= playheadMs && cue.end_ms >= playheadMs)?.text ?? '', [tracks, playheadMs])

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings || seeded.current) return
    seeded.current = true
    setOutputDir(stringSetting(settings.editor_output_dir, stringSetting(settings.output_dir, '')))
    setResolution(stringSetting(settings.editor_resolution, 'original'))
    setFps(stringSetting(settings.editor_fps, 'source'))
    setEncoder(stringSetting(settings.editor_encoder, 'auto'))
    setAudioMode(stringSetting(settings.editor_audio_mode, 'mix'))
    setSourceVolume(clamp(numberSetting(settings.editor_source_volume, 100), 0, 100))
    setExternalVolume(clamp(numberSetting(settings.editor_external_volume, 100), 0, 100))
    setFontSize(numberSetting(settings.editor_subtitle_font_size, 22))
    setSubtitleMargin(numberSetting(settings.editor_subtitle_margin, 36))
    setZoom(clamp(numberSetting(settings.editor_timeline_zoom, 8), 0.1, 300))
  }, [settingsQuery.data])

  useEffect(() => {
    if (!exportTask || isTaskActive(exportTask.status)) return
    if (exportTask.status === 'done' && exportTask.result) { setResult(exportTask.result as EditorExportResult); setMessage('Xuất video hoàn tất.') }
    else if (exportTask.status === 'cancelled') setMessage('Đã dừng xuất video.')
    else if (exportTask.status === 'failed') setMessage(exportTask.error ?? 'Xuất video thất bại.')
  }, [exportTask])

  useEffect(() => {
    if (!speechTask || isTaskActive(speechTask.status) || handledSpeechTask.current === speechTask.taskId) return
    handledSpeechTask.current = speechTask.taskId
    if (speechTask.status !== 'done' || !speechTask.result) {
      setMessage(speechTask.error ?? 'Chuyển phụ đề thành giọng nói thất bại.')
      return
    }
    const run = speechTask.result as BatchRun
    const pendingByItem = new Map(pendingSpeech.map((item) => [item.itemId, item]))
    void Promise.all(run.items.filter((item) => item.status === 'done' && item.wav_path).map(async (item) => {
      const pending = pendingByItem.get(item.item_id)
      if (!pending || !item.wav_path) return null
      const path = `${run.root_dir}/${item.wav_path}`.replaceAll('/', '\\')
      const media = await loadEditorMedia(path, 'audio')
      return { pending, media, clip: mediaClip(media, pending.startMs) }
    })).then((generated) => {
      const ready = generated.filter((item): item is NonNullable<typeof item> => item !== null)
      setAssets((current) => [...current, ...ready.map(({ media }) => ({ ...media, id: `audio:${media.source_id}` } as EditorMediaAsset<'audio'>))])
      setTracks((current) => {
        let next = current
        for (const trackId of [...new Set(ready.map(({ pending }) => pending.trackId))]) {
          const clips = ready.filter(({ pending }) => pending.trackId === trackId).map(({ clip }) => clip)
          next = placeAudioClips(next, clips, trackId).tracks
        }
        return next
      })
      const failed = run.items.filter((item) => item.status !== 'done').length
      setMessage(`Đã tạo ${ready.length} audio từ phụ đề${failed ? `, ${failed} câu lỗi` : ''}. Audio chồng nhau đã tự xuống lane dưới.`)
    }).catch((cause) => setMessage(cause instanceof Error ? cause.message : String(cause)))
  }, [pendingSpeech, speechTask])

  useEffect(() => {
    const player = videoRef.current
    if (!player || !previewClip) return
    player.volume = clamp(sourceVolume / 100, 0, 1)
    const target = (previewClip.source_start_ms + Math.max(0, playheadMs - previewClip.timeline_start_ms)) / 1000
    if (Math.abs(player.currentTime - target) > 0.12) player.currentTime = target
  }, [playheadMs, previewClip, sourceVolume])

  const addAsset = (asset: EditorAsset) => {
    setAssets((current) => [...current.filter((item) => item.path !== asset.path), asset])
    setMessage(`Đã nhập ${asset.name}. Kéo xuống đúng track hoặc bấm dấu + của tệp.`)
  }

  const importMedia = async (kind: 'video' | 'audio', selectedPath?: string | null) => {
    const path = selectedPath ?? (kind === 'video' ? await pickVideoFile() : await pickAudioFile())
    if (!path) return
    setMessage(`Đang đọc ${kind}...`)
    try {
      const media = await loadEditorMedia(path, kind)
      addAsset({ ...media, id: `${kind}:${media.source_id}` })
      setManualPath('')
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : String(cause)) }
  }

  const importSrt = async (selectedPath?: string | null) => {
    const path = selectedPath ?? await pickSrtFile()
    if (!path) return
    setMessage('Đang đọc phụ đề...')
    try {
      const subtitle = await loadEditorCues(path)
      addAsset({ ...subtitle, id: `subtitle:${crypto.randomUUID()}`, kind: 'subtitle' })
      setManualPath('')
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : String(cause)) }
  }

  const activateAsset = (assetId: string, dropMs = playheadMs, targetTrackId?: string) => {
    const asset = assets.find((item) => item.id === assetId)
    if (!asset) return
    const kind = asset.kind
    let target = targetTrackId ? tracks.find((track) => track.id === targetTrackId) : tracks.find((track) => track.kind === kind)
    if (target && target.kind !== kind) { setMessage(`Hãy thả ${kind === 'subtitle' ? 'SRT' : kind} vào đúng loại track.`); return }
    if (!target) {
      const created = createTrack(kind, tracks.filter((track) => track.kind === kind).length + 1)
      target = created
      setTracks((current) => [...current, created])
    }
    const targetId = target.id
    if (asset.kind === 'subtitle') {
      const importedCues = asset.cues.map(cueWithId)
      setTracks((current) => current.map((track) => track.id === targetId && track.kind === 'subtitle' ? { ...track, cues: reindexTrackCues([...track.cues, ...importedCues]) } : track))
      if (importedCues[0]) setSelection({ trackId: targetId, itemId: importedCues[0].id })
    } else {
      const clip = mediaClip(asset, dropMs)
      setTracks((current) => current.map((track) => track.id === targetId && track.kind === asset.kind ? { ...track, clips: [...track.clips, clip] } : track))
      setSelection({ trackId: targetId, itemId: clip.id })
      if (asset.kind === 'video') setPreviewError(false)
    }
    setMessage(`Đã thêm ${asset.name} vào ${target.name}.`)
  }

  const seek = (milliseconds: number) => setPlayheadMs(clamp(milliseconds, 0, durationMs))
  const updateCue = (trackId: string, cueId: string, cue: TimelineCue) => setTracks((current) => current.map((track) => track.id === trackId && track.kind === 'subtitle' ? { ...track, cues: reindexTrackCues(track.cues.map((item) => item.id === cueId ? cue : item)) } : track))
  const updateClip = (trackId: string, clipId: string, clip: TimelineMediaClip) => setTracks((current) => current.map((track) => track.id === trackId && track.kind !== 'subtitle' ? { ...track, clips: track.clips.map((item) => item.id === clipId ? clip : item) } : track))

  const updateActiveTime = (field: 'start_ms' | 'end_ms', value: string) => {
    const parsed = parseClock(value)
    if (!activeCue || !activeSubtitleTrack || parsed === null) return
    const next = field === 'start_ms'
      ? { ...activeCue, start_ms: clamp(parsed, 0, activeCue.end_ms - 1) }
      : { ...activeCue, end_ms: clamp(parsed, activeCue.start_ms + 1, durationMs) }
    updateCue(activeSubtitleTrack.id, activeCue.id, next)
  }

  const splitAtPlayhead = () => {
    if (!selectedClip || !selectedTrack || selectedTrack.kind === 'subtitle' || selectedTrack.locked) { setMessage('Chọn một clip video hoặc audio đang mở khóa.'); return }
    const offset = playheadMs - selectedClip.timeline_start_ms
    if (offset < 100 || offset > clipDuration(selectedClip) - 100) { setMessage('Đưa playhead vào giữa clip, cách mép ít nhất 0,1 giây.'); return }
    const sourceSplit = selectedClip.source_start_ms + offset
    const left = { ...selectedClip, source_end_ms: sourceSplit }
    const right = { ...selectedClip, id: `${selectedTrack.kind}:${crypto.randomUUID()}`, timeline_start_ms: playheadMs, source_start_ms: sourceSplit }
    setTracks((current) => current.map((track) => track.id === selectedTrack.id && track.kind !== 'subtitle' ? { ...track, clips: track.clips.flatMap((clip) => clip.id === selectedClip.id ? [left, right] : [clip]) } : track))
    setSelection({ trackId: selectedTrack.id, itemId: right.id })
    setMessage('Đã tách clip tại playhead.')
  }

  const deleteSelection = () => {
    if (!selection || !selectedTrack || selectedTrack.locked) return
    setTracks((current) => current.map((track) => {
      if (track.id !== selection.trackId) return track
      return track.kind === 'subtitle'
        ? { ...track, cues: reindexTrackCues(track.cues.filter((cue) => cue.id !== selection.itemId)) }
        : { ...track, clips: track.clips.filter((clip) => clip.id !== selection.itemId) }
    }))
    setSelection(null)
  }

  const ttsTargets = () => {
    if (ttsScope === 'selected') return activeCue && activeSubtitleTrack ? [{ track: activeSubtitleTrack, cue: activeCue }] : []
    if (ttsScope === 'track') return activeSubtitleTrack?.cues.map((cue) => ({ track: activeSubtitleTrack, cue })) ?? []
    return tracks.flatMap((track) => track.kind === 'subtitle' && track.enabled ? track.cues.map((cue) => ({ track, cue })) : [])
  }

  const generateSpeech = async () => {
    const targets = ttsTargets()
    if (!selectedVoice) { setMessage('Chọn một giọng trong Thư viện giọng.'); return }
    if (!targets.length) { setMessage('Không có câu phụ đề phù hợp với phạm vi đã chọn.'); return }
    const speechOutput = stringSetting(settingsQuery.data?.omnivoice_output_dir, outputDir)
    if (!speechOutput) { setMessage('Chọn thư mục xuất trước khi tạo giọng.'); return }
    const pending = targets.map(({ track, cue }, index) => ({ itemId: `editor-${String(index + 1).padStart(4, '0')}`, trackId: track.id, cueId: cue.id, startMs: cue.start_ms }))
    const voice = libraryVoiceRequest(selectedVoice)
    try {
      const response = await startBatchRun({
        project_id: galaxyProjectId,
        title: `Editor TTS ${new Date().toLocaleString('vi-VN')}`,
        output_dir: speechOutput,
        device: stringSetting(settingsQuery.data?.omnivoice_device, 'auto'),
        language: selectedVoice.language || 'vi',
        speed: 1,
        formats: ['wav'],
        voice,
        combine: false,
        gap_ms: 0,
        items: targets.map(({ cue }, index) => ({
          item_id: pending[index].itemId,
          text: cue.text,
          language: selectedVoice.language || 'vi',
          speed: null,
          duration: null,
          voice_source: '',
          profile_id: '',
          instruction: '',
          formats: ['wav'],
        })),
      })
      setPendingSpeech(pending)
      setTtsTaskId(response.task_id)
      setMessage(`Đang tạo giọng cho ${targets.length} câu phụ đề...`)
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : String(cause)) }
  }

  const startExport = async () => {
    if (!primaryVideo) { setMessage('Đưa ít nhất một video vào timeline trước.'); return }
    if (!outputDir.trim()) { setMessage('Chọn thư mục xuất trước.'); return }
    setResult(null)
    setMessage('Đang chuẩn bị xuất video...')
    try {
      await updateSettings({
        editor_output_dir: outputDir, editor_resolution: resolution, editor_fps: fps, editor_encoder: encoder,
        editor_audio_mode: audioMode, editor_source_volume: sourceVolume, editor_external_volume: externalVolume,
        editor_subtitle_font_size: fontSize, editor_subtitle_margin: subtitleMargin, editor_timeline_zoom: zoom,
      })
      const cues = tracks
        .filter((track): track is Extract<EditorTrack, { kind: 'subtitle' }> => track.kind === 'subtitle' && track.enabled)
        .flatMap((track) => track.cues)
        .sort((left, right) => left.start_ms - right.start_ms)
        .map(({ id: _id, ...cue }, index) => ({ ...cue, index: index + 1 }))
      setTaskId(await startEditorExport({
        galaxy_project_id: galaxyProjectId,
        video_path: primaryVideo.media.path,
        output_dir: outputDir,
        project_name: projectName,
        cues,
        segments: [],
        audio_offset_ms: 0,
        audio_mode: audioMode,
        source_volume: sourceVolume,
        external_volume: externalVolume,
        resolution, fps, encoder, quality,
        subtitle_font_size: fontSize,
        subtitle_margin: subtitleMargin,
        video_clips: videoTrackClips.map(({ clip, trackOrder }) => ({ path: clip.media.path, timeline_start_ms: clip.timeline_start_ms, source_start_ms: clip.source_start_ms, source_end_ms: clip.source_end_ms, track_order: trackOrder, volume: sourceVolume, has_audio: clip.media.has_audio })),
        audio_clips: audioTrackClips.map(({ clip, trackOrder }) => ({ path: clip.media.path, timeline_start_ms: clip.timeline_start_ms, source_start_ms: clip.source_start_ms, source_end_ms: clip.source_end_ms, track_order: trackOrder, volume: externalVolume, has_audio: true })),
      }))
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : String(cause)) }
  }

  const addTrack = (kind: EditorTrackKind) => setTracks((current) => [...current, createTrack(kind, current.filter((track) => track.kind === kind).length + 1)])
  const removeTrack = (trackId: string) => {
    const track = tracks.find((candidate) => candidate.id === trackId)
    if (!track) return
    const itemCount = track.kind === 'subtitle' ? track.cues.length : track.clips.length
    if (itemCount > 0 && !window.confirm(`Xóa ${track.name} và ${itemCount} mục đang có trên track?`)) return
    setTracks((current) => current.filter((candidate) => candidate.id !== trackId))
    if (selection?.trackId === trackId) setSelection(null)
    setMessage(`Đã xóa ${track.name}.`)
  }
  const toggleTrack = (trackId: string, field: 'enabled' | 'locked') => setTracks((current) => current.map((track) => track.id === trackId ? { ...track, [field]: !track[field] } : track))

  return (
    <div className="editor-page">
      <header className="workspace-heading editor-heading">
        <div><h1>Dựng video</h1><p>Ghép nhiều lớp video, voice và phụ đề trên một timeline gọn nhẹ.</p></div>
        <span className="editor-project-state">{primaryVideo ? `${primaryVideo.media.width}×${primaryVideo.media.height} · ${primaryVideo.media.fps.toFixed(2)} fps · ${formatClock(durationMs)}` : 'Chưa có project'}</span>
      </header>

      <div className="editor-workspace-grid">
        <aside className="section-card editor-media-bin">
          <div className="section-header compact"><h2 className="section-title">Tệp phương tiện</h2><span className="field-hint">{assets.length} tệp</span></div>
          <div className="editor-import-actions"><button className="btn" onClick={() => void importMedia('video')}>Thêm video</button><button className="btn" onClick={() => void importMedia('audio')}>Thêm audio</button><button className="btn" onClick={() => void importSrt()}>Thêm SRT</button></div>
          {!hasNativeDialogs() && <div className="input-action editor-manual-path"><input value={manualPath} placeholder="Đường dẫn tệp" onChange={(event) => setManualPath(event.target.value)} /><button className="btn" onClick={() => void importMedia('video', manualPath)}>Nạp</button></div>}
          <div className="editor-asset-list">
            {assets.map((asset) => <div className="editor-asset" key={asset.id} draggable onDragStart={(event) => event.dataTransfer.setData('application/x-galaxy-editor-asset', asset.id)}>
              <span className={`asset-kind ${asset.kind}`}>{asset.kind === 'subtitle' ? 'SRT' : asset.kind === 'video' ? 'VID' : 'AUD'}</span>
              <div><strong>{asset.name}</strong><small>{asset.kind === 'subtitle' ? `${asset.cues.length} câu` : formatClock(asset.duration_seconds * 1000)}</small></div>
              <button className="asset-add" title="Đưa vào timeline" onClick={() => activateAsset(asset.id)}>+</button>
              <button className="asset-remove" title="Gỡ khỏi danh sách" onClick={() => setAssets((current) => current.filter((item) => item.id !== asset.id))}>×</button>
            </div>)}
            {!assets.length && <div className="editor-empty-bin">Nhập tệp, sau đó kéo xuống đúng line trên timeline.</div>}
          </div>
        </aside>

        <section className="section-card editor-preview-panel">
          <div className="editor-video-stage" style={{ aspectRatio: previewClip ? `${previewClip.media.width}/${previewClip.media.height}` : '16/9' }}>
            {previewClip ? <>
              <video
                key={previewClip.id}
                ref={videoRef}
                src={previewClip.media.url}
                controls
                preload="metadata"
                muted={audioMode === 'replace'}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onCanPlay={() => setPreviewError(false)}
                onError={() => setPreviewError(true)}
                onTimeUpdate={(event) => {
                  const sourceMs = Math.round(event.currentTarget.currentTime * 1000)
                  const next = previewClip.timeline_start_ms + sourceMs - previewClip.source_start_ms
                  if (next >= clipEnd(previewClip)) { event.currentTarget.pause(); seek(clipEnd(previewClip)) }
                  else setPlayheadMs(clamp(next, previewClip.timeline_start_ms, clipEnd(previewClip)))
                }}
              />
              {subtitleAtPlayhead && <div className="editor-subtitle-preview" style={{ fontSize: `${Math.max(12, fontSize)}px`, bottom: `${subtitleMargin}px` }}>{subtitleAtPlayhead}</div>}
              {previewError && <div className="editor-preview-error">WebView2 không phát được codec của video này. Engine xuất vẫn có thể xử lý file nguồn.</div>}
            </> : <div className="editor-video-empty">Đưa video vào timeline để xem trước</div>}
          </div>
          {activeAudioClips.map(({ clip }) => <AudioPreview key={clip.id} clip={clip} playheadMs={playheadMs} playing={playing} volume={externalVolume} />)}
        </section>

        <aside className="section-card editor-inspector">
          <div className="section-header compact"><h2 className="section-title">Phụ đề & giọng nói</h2><span className="field-hint">{activeSubtitleTrack?.name ?? 'Chưa có track'}</span></div>
          <CueList cues={activeSubtitleTrack?.cues ?? []} selectedId={activeCue?.id ?? ''} onSelect={(cue) => { if (!activeSubtitleTrack) return; setSelection({ trackId: activeSubtitleTrack.id, itemId: cue.id }); seek(cue.start_ms) }} />
          {activeCue && activeSubtitleTrack ? <div className="cue-editor">
            <div className="field-grid"><div className="field"><label>Bắt đầu</label><ClockInput value={activeCue.start_ms} onCommit={(value) => updateActiveTime('start_ms', value)} /></div><div className="field"><label>Kết thúc</label><ClockInput value={activeCue.end_ms} onCommit={(value) => updateActiveTime('end_ms', value)} /></div></div>
            <textarea className="srt-editor" rows={3} value={activeCue.text} onChange={(event) => updateCue(activeSubtitleTrack.id, activeCue.id, { ...activeCue, text: event.target.value })} />
          </div> : <p className="field-hint">Chọn một câu phụ đề để sửa hoặc chuyển riêng câu đó thành giọng nói.</p>}
          <div className="editor-tts-panel">
            <div className="field"><label>Giọng từ Thư viện</label><select aria-label="Giọng từ Thư viện" value={voiceId} onChange={(event) => setVoiceId(event.target.value)}><option value="">Chọn giọng</option>{(voicesQuery.data ?? []).map((voice) => <VoiceOption key={voice.voice_id} voice={voice} />)}</select></div>
            <div className="seg-control editor-tts-scope" aria-label="Phạm vi chuyển giọng">
              <button className={`seg-item${ttsScope === 'selected' ? ' active' : ''}`} onClick={() => setTtsScope('selected')}>Câu chọn</button>
              <button className={`seg-item${ttsScope === 'track' ? ' active' : ''}`} onClick={() => setTtsScope('track')}>Cả line</button>
              <button className={`seg-item${ttsScope === 'all' ? ' active' : ''}`} onClick={() => setTtsScope('all')}>Tất cả SRT</button>
            </div>
            <button className="btn accent" disabled={speechRunning || !voiceId} onClick={() => void generateSpeech()}>{speechRunning ? 'Đang chuyển...' : 'Chuyển thành audio'}</button>
          </div>
          <div className="toolbar-row editor-cue-tools"><button className="btn" disabled={!activeSubtitleTrack} onClick={() => {
            if (!activeSubtitleTrack) return
            const cue = cueWithId({ index: activeSubtitleTrack.cues.length + 1, start_ms: playheadMs, end_ms: playheadMs + 2_000, text: 'Phụ đề mới' })
            setTracks((current) => current.map((track) => track.id === activeSubtitleTrack.id && track.kind === 'subtitle' ? { ...track, cues: reindexTrackCues([...track.cues, cue]) } : track))
            setSelection({ trackId: activeSubtitleTrack.id, itemId: cue.id })
          }}>Thêm câu</button><button className="btn" disabled={!activeSubtitleTrack?.cues.length} onClick={() => activeSubtitleTrack && setTracks((current) => current.map((track) => track.id === activeSubtitleTrack.id && track.kind === 'subtitle' ? { ...track, cues: fitCues(track.cues, Math.max(...videoTrackClips.map(({ clip }) => clipEnd(clip)), 1)) } : track))}>Căn theo video</button><button className="btn danger" disabled={!selection} onClick={deleteSelection}>Xóa mục chọn</button></div>
        </aside>
      </div>

      <section className="section-card editor-timeline-panel">
        <div className="editor-timeline-toolbar">
          <div><strong>Timeline</strong><span>{formatClock(playheadMs, true)} / {formatClock(durationMs, true)}</span></div>
          <div className="editor-cut-tools"><button className="btn" disabled={!selectedClip} onClick={splitAtPlayhead}>Tách tại playhead</button><button className="btn danger" disabled={!selection} onClick={deleteSelection}>Xóa mục chọn</button></div>
          <label>Thu phóng <input type="range" min="0.1" max="120" step="0.1" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /><output>{zoom.toFixed(1)} px/s</output></label>
        </div>
        <Timeline durationMs={durationMs} tracks={tracks} selection={selection} playheadMs={playheadMs} zoom={zoom} onSeek={seek} onSelect={setSelection} onChangeCue={updateCue} onChangeClip={updateClip} onDropAsset={activateAsset} onToggleTrackEnabled={(id) => toggleTrack(id, 'enabled')} onToggleTrackLocked={(id) => toggleTrack(id, 'locked')} onAddTrack={addTrack} onRemoveTrack={removeTrack} />
      </section>

      <section className="section-card editor-export-panel">
        <div className="section-header compact"><h2 className="section-title">Xuất video</h2><span className="field-hint">MP4 · H.264 · AAC</span></div>
        <div className="field-grid editor-export-grid">
          <div className="field field-wide"><label>Thư mục xuất</label><div className="input-action"><input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} /><button className="btn" onClick={() => void pickFolder().then((path) => { if (path) setOutputDir(path) })}>Chọn</button></div></div>
          <div className="field"><label>Tên project</label><input value={projectName} onChange={(event) => setProjectName(event.target.value)} /></div>
          <OptionField label="Độ phân giải" value={resolution} onChange={setResolution} options={settingsMetaQuery.data?.editor_resolutions} /><OptionField label="FPS" value={fps} onChange={setFps} options={settingsMetaQuery.data?.editor_fps} /><OptionField label="Encoder" value={encoder} onChange={setEncoder} options={settingsMetaQuery.data?.editor_encoders} /><OptionField label="Âm thanh" value={audioMode} onChange={setAudioMode} options={settingsMetaQuery.data?.editor_audio_modes} />
          <div className="field"><label>Âm lượng video: {sourceVolume}%</label><input type="range" min="0" max="100" value={sourceVolume} onChange={(event) => setSourceVolume(Number(event.target.value))} /></div><div className="field"><label>Âm lượng audio: {externalVolume}%</label><input type="range" min="0" max="100" value={externalVolume} onChange={(event) => setExternalVolume(Number(event.target.value))} /></div><div className="field"><label>Chất lượng CRF: {quality}</label><input type="range" min="14" max="32" value={quality} onChange={(event) => setQuality(Number(event.target.value))} /></div><div className="field"><label>Cỡ chữ sub</label><input type="number" min="10" max="72" value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} /></div><div className="field"><label>Lề sub</label><input type="number" min="0" max="500" value={subtitleMargin} onChange={(event) => setSubtitleMargin(Number(event.target.value))} /></div>
        </div>
        <div className="editor-export-actions"><button className="btn accent" disabled={!primaryVideo || running} onClick={() => void startExport()}>{running ? 'Đang xuất...' : 'Xuất video'}</button><button className="btn danger" disabled={!running || !taskId} onClick={() => taskId && void cancelTask(taskId)}>Dừng</button>{result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}<span>{message}</span></div>
        {result && <div className="editor-result"><video controls preload="metadata" src={result.video_url} /><div><strong>{result.video_path}</strong>{result.warnings.map((warning) => <small key={warning}>{warning}</small>)}</div></div>}
      </section>
    </div>
  )
}

function AudioPreview({ clip, playheadMs, playing, volume }: { clip: TimelineMediaClip; playheadMs: number; playing: boolean; volume: number }) {
  const ref = useRef<HTMLAudioElement>(null)
  useEffect(() => {
    const audio = ref.current
    if (!audio) return
    const target = (clip.source_start_ms + playheadMs - clip.timeline_start_ms) / 1000
    audio.volume = clamp(volume / 100, 0, 1)
    if (Math.abs(audio.currentTime - target) > 0.15) audio.currentTime = Math.max(0, target)
    if (playing) void audio.play().catch(() => undefined)
    else audio.pause()
  }, [clip, playheadMs, playing, volume])
  return <audio ref={ref} src={clip.media.url} preload="metadata" />
}

function VoiceOption({ voice }: { voice: LibraryVoice }) {
  return <option value={voice.voice_id} disabled={!voice.compatibility.batch}>{voice.name} · {voice.language}{voice.compatibility.batch ? '' : ' · không hỗ trợ Batch'}</option>
}

function OptionField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options?: { code: string; label: string }[] }) {
  return <div className="field"><label>{label}</label><select value={value} onChange={(event) => onChange(event.target.value)}>{(options ?? [{ code: value, label: value }]).map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}</select></div>
}

function ClockInput({ value, onCommit }: { value: number; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(() => formatClock(value, true))
  useEffect(() => setDraft(formatClock(value, true)), [value])
  return <input value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => onCommit(draft)} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
}

function CueList({ cues, selectedId, onSelect }: { cues: TimelineCue[]; selectedId: string; onSelect: (cue: TimelineCue) => void }) {
  const rowHeight = 48
  const height = 238
  const [scrollTop, setScrollTop] = useState(0)
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 3)
  const end = Math.min(cues.length, Math.ceil((scrollTop + height) / rowHeight) + 3)
  return <div className="cue-list" style={{ height }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}><div style={{ height: cues.length * rowHeight, position: 'relative' }}>{cues.slice(start, end).map((cue, offset) => { const index = start + offset; return <button key={cue.id} className={`cue-row${selectedId === cue.id ? ' selected' : ''}`} style={{ top: index * rowHeight, height: rowHeight }} onClick={() => onSelect(cue)}><span>{cue.index}</span><time>{formatClock(cue.start_ms, true)}</time><strong>{cue.text.replace(/\n/g, ' ')}</strong></button> })}</div></div>
}

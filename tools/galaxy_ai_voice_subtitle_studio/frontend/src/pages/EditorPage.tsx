import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  loadEditorCues,
  loadEditorMedia,
  startEditorExport,
} from '../api/editor'
import type { EditorCue, EditorExportResult, EditorMedia, EditorSubtitleAsset } from '../api/editor'
import { fetchSettings, fetchSettingsMeta, updateSettings } from '../api/settings'
import { openPath } from '../api/voice'
import { Timeline } from '../components/timeline/Timeline'
import { clamp, formatClock, parseClock } from '../components/timeline/geometry'
import type { VideoSegment } from '../components/timeline/segments'
import { useActiveProjectId } from '../hooks/useActiveProjectId'
import {
  projectDuration,
  rippleDeleteCues,
  segmentDuration,
  segmentTimelineStart,
  splitVideoSegment,
  timelineToSource,
} from '../components/timeline/segments'
import { hasNativeDialogs, pickAudioFile, pickFolder, pickSrtFile, pickVideoFile } from '../lib/dialogs'
import { useTasks } from '../ws/useTasks'
import { isTaskActive } from '../ws/types'

type EditorMediaAsset<K extends 'video' | 'audio'> = Omit<EditorMedia, 'kind'> & {
  id: string
  kind: K
}

type EditorAsset =
  | EditorMediaAsset<'video'>
  | EditorMediaAsset<'audio'>
  | ({ id: string; kind: 'subtitle' } & EditorSubtitleAsset)

function numberSetting(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringSetting(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function reindex(cues: EditorCue[]): EditorCue[] {
  return cues.map((cue, index) => ({ ...cue, index: index + 1 }))
}

function fitCues(cues: EditorCue[], durationMs: number): EditorCue[] {
  if (!cues.length || durationMs <= 0) return cues
  const sorted = [...cues].sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms)
  const first = sorted[0].start_ms
  const last = Math.max(...sorted.map((cue) => cue.end_ms))
  const scale = durationMs / Math.max(1, last - first)
  return reindex(sorted.map((cue) => {
    const startMs = Math.round((cue.start_ms - first) * scale)
    return {
      ...cue,
      start_ms: startMs,
      end_ms: Math.min(durationMs, Math.max(startMs + 1, Math.round((cue.end_ms - first) * scale))),
    }
  }))
}

export function EditorPage() {
  const galaxyProjectId = useActiveProjectId()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const settingsMetaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const { tasks, cancelTask } = useTasks()
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const segmentsRef = useRef<VideoSegment[]>([])
  const activeSegmentRef = useRef(0)
  const playheadRef = useRef(0)
  const seeded = useRef(false)

  const [assets, setAssets] = useState<EditorAsset[]>([])
  const [video, setVideo] = useState<EditorMedia | null>(null)
  const [audio, setAudio] = useState<EditorMedia | null>(null)
  const [videoSegments, setVideoSegments] = useState<VideoSegment[]>([])
  const [selectedSegment, setSelectedSegment] = useState<number | null>(null)
  const [cues, setCues] = useState<EditorCue[]>([])
  const [selectedCue, setSelectedCue] = useState<number | null>(null)
  const [playheadMs, setPlayheadMs] = useState(0)
  const [audioOffsetMs, setAudioOffsetMs] = useState(0)
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
  const [subtitleVisible, setSubtitleVisible] = useState(true)
  const [subtitleLocked, setSubtitleLocked] = useState(false)
  const [videoVisible, setVideoVisible] = useState(true)
  const [videoLocked, setVideoLocked] = useState(false)
  const [audioMuted, setAudioMuted] = useState(false)
  const [audioLocked, setAudioLocked] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [result, setResult] = useState<EditorExportResult | null>(null)

  const task = taskId ? tasks.find((item) => item.taskId === taskId) : undefined
  const running = isTaskActive(task?.status)
  const sourceDurationMs = Math.round((video?.duration_seconds ?? 0) * 1000)
  const durationMs = projectDuration(videoSegments)
  const activeCue = selectedCue === null ? null : cues[selectedCue] ?? null
  const subtitleAtPlayhead = useMemo(
    () => subtitleVisible ? cues.find((cue) => cue.start_ms <= playheadMs && cue.end_ms >= playheadMs)?.text ?? '' : '',
    [cues, playheadMs, subtitleVisible],
  )

  useEffect(() => { segmentsRef.current = videoSegments }, [videoSegments])
  useEffect(() => { playheadRef.current = playheadMs }, [playheadMs])

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
    if (!task || isTaskActive(task.status)) return
    if (task.status === 'done' && task.result) {
      setResult(task.result as EditorExportResult)
      setMessage('Xuất video hoàn tất.')
    } else if (task.status === 'cancelled') {
      setMessage('Đã dừng xuất video.')
    } else if (task.status === 'failed') {
      setMessage(task.error ?? 'Xuất video thất bại.')
    }
  }, [task])

  useEffect(() => {
    const player = videoRef.current
    const external = audioRef.current
    if (!player || !external || !audio) return
    const sync = () => {
      const segments = segmentsRef.current
      const index = clamp(activeSegmentRef.current, 0, Math.max(0, segments.length - 1))
      const segment = segments[index]
      const timelineMs = segment
        ? segmentTimelineStart(segments, index) + clamp(Math.round(player.currentTime * 1000) - segment.source_start_ms, 0, segmentDuration(segment))
        : playheadRef.current
      const target = timelineMs / 1000 - audioOffsetMs / 1000
      if (target < 0 || target > audio.duration_seconds) {
        external.pause()
        return
      }
      if (Math.abs(external.currentTime - target) > 0.18) external.currentTime = target
      if (!player.paused && external.paused) void external.play().catch(() => undefined)
    }
    const play = () => sync()
    const pause = () => external.pause()
    player.addEventListener('play', play)
    player.addEventListener('pause', pause)
    player.addEventListener('seeking', sync)
    player.addEventListener('timeupdate', sync)
    return () => {
      player.removeEventListener('play', play)
      player.removeEventListener('pause', pause)
      player.removeEventListener('seeking', sync)
      player.removeEventListener('timeupdate', sync)
    }
  }, [audio, audioOffsetMs])

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.muted = Boolean(audio && audioMode === 'replace')
      videoRef.current.volume = clamp(sourceVolume / 100, 0, 1)
    }
    if (audioRef.current) audioRef.current.volume = clamp(externalVolume / 100, 0, 1)
  }, [audio, audioMode, sourceVolume, externalVolume])

  const addAsset = (asset: EditorAsset) => {
    setAssets((current) => [...current.filter((item) => item.path !== asset.path), asset])
    setMessage(`Đã nhập ${asset.name}. Kéo xuống timeline hoặc bấm Đưa vào timeline.`)
  }

  const importMedia = async (kind: 'video' | 'audio', selectedPath?: string | null) => {
    const path = selectedPath ?? (kind === 'video' ? await pickVideoFile() : await pickAudioFile())
    if (!path) return
    setMessage(`Đang đọc ${kind}...`)
    try {
      const media = await loadEditorMedia(path, kind)
      addAsset({ ...media, id: `${kind}:${media.source_id}` })
      setManualPath('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const importSrt = async (selectedPath?: string | null) => {
    const path = selectedPath ?? await pickSrtFile()
    if (!path) return
    setMessage('Đang đọc phụ đề...')
    try {
      const subtitle = await loadEditorCues(path, durationMs || undefined)
      addAsset({ ...subtitle, id: `subtitle:${crypto.randomUUID()}`, kind: 'subtitle' })
      setManualPath('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const activateAsset = (assetId: string, dropMs = 0) => {
    const asset = assets.find((item) => item.id === assetId)
    if (!asset) return
    if (asset.kind === 'video') {
      setVideo(asset)
      const sourceEnd = Math.round(asset.duration_seconds * 1000)
      const initialSegment = { id: `video:${asset.source_id}`, source_start_ms: 0, source_end_ms: sourceEnd }
      setVideoSegments([initialSegment])
      segmentsRef.current = [initialSegment]
      setSelectedSegment(0)
      activeSegmentRef.current = 0
      setPreviewError(false)
      setPlayheadMs(0)
      setCues((current) => current.filter((cue) => cue.start_ms < asset.duration_seconds * 1000).map((cue) => ({ ...cue, end_ms: Math.min(cue.end_ms, Math.round(asset.duration_seconds * 1000)) })))
    } else if (asset.kind === 'audio') {
      setAudio(asset)
      setAudioOffsetMs(clamp(dropMs, 0, Math.max(0, durationMs - 1)))
    } else {
      const shifted = asset.cues
        .map((cue) => ({ ...cue, start_ms: cue.start_ms + dropMs, end_ms: cue.end_ms + dropMs }))
        .filter((cue) => !durationMs || cue.start_ms < durationMs)
        .map((cue) => ({ ...cue, end_ms: durationMs ? Math.min(durationMs, cue.end_ms) : cue.end_ms }))
      setCues(reindex(shifted))
      setSelectedCue(asset.cues.length ? 0 : null)
    }
    setMessage(`Đã đưa ${asset.name} vào timeline.`)
  }

  const removeAsset = (assetId: string) => {
    setAssets((current) => current.filter((item) => item.id !== assetId))
  }

  const seek = (milliseconds: number) => {
    const currentSegments = segmentsRef.current
    const next = clamp(milliseconds, 0, projectDuration(currentSegments))
    setPlayheadMs(next)
    playheadRef.current = next
    const position = timelineToSource(currentSegments, next)
    if (position && videoRef.current) {
      activeSegmentRef.current = position.index
      videoRef.current.currentTime = position.sourceMs / 1000
    }
  }

  const syncPlayheadFromVideo = (player: HTMLVideoElement) => {
    const segments = segmentsRef.current
    if (!segments.length) return
    const index = clamp(activeSegmentRef.current, 0, segments.length - 1)
    const segment = segments[index]
    const sourceMs = Math.round(player.currentTime * 1000)
    const timelineStart = segmentTimelineStart(segments, index)
    if (sourceMs >= segment.source_end_ms - 15) {
      const next = segments[index + 1]
      if (next) {
        activeSegmentRef.current = index + 1
        player.currentTime = next.source_start_ms / 1000
        const nextTimeline = timelineStart + segmentDuration(segment)
        playheadRef.current = nextTimeline
        setPlayheadMs(nextTimeline)
      } else {
        player.pause()
        playheadRef.current = durationMs
        setPlayheadMs(durationMs)
      }
      return
    }
    const nextTimeline = timelineStart + clamp(sourceMs - segment.source_start_ms, 0, segmentDuration(segment))
    playheadRef.current = nextTimeline
    setPlayheadMs(nextTimeline)
  }

  const splitAtPlayhead = () => {
    if (videoLocked) { setMessage('Mở khóa track video trước khi tách.'); return }
    const result = splitVideoSegment(videoSegments, playheadMs)
    if (!result) { setMessage('Đưa playhead vào giữa clip, cách mép ít nhất 0,1 giây.'); return }
    setVideoSegments(result.segments)
    segmentsRef.current = result.segments
    setSelectedSegment(result.selectedIndex)
    activeSegmentRef.current = result.selectedIndex
    setMessage('Đã tách clip tại playhead.')
  }

  const deleteSelectedSegment = () => {
    if (videoLocked) { setMessage('Mở khóa track video trước khi xóa.'); return }
    if (selectedSegment === null || videoSegments.length <= 1) { setMessage('Chọn một đoạn đã tách để xóa.'); return }
    const removedStart = segmentTimelineStart(videoSegments, selectedSegment)
    const removedDuration = segmentDuration(videoSegments[selectedSegment])
    const nextSegments = videoSegments.filter((_segment, index) => index !== selectedSegment)
    const nextDuration = projectDuration(nextSegments)
    setVideoSegments(nextSegments)
    segmentsRef.current = nextSegments
    setSelectedSegment(Math.min(selectedSegment, nextSegments.length - 1))
    activeSegmentRef.current = Math.min(selectedSegment, nextSegments.length - 1)
    setCues((current) => reindex(rippleDeleteCues(current, removedStart, removedDuration)))
    seek(Math.min(removedStart, nextDuration))
    setMessage('Đã xóa đoạn và dồn các đoạn phía sau sang trái.')
  }

  const changeVideoSegment = (index: number, segment: VideoSegment) => {
    const next = videoSegments.map((item, itemIndex) => itemIndex === index ? segment : item)
    setVideoSegments(next)
    segmentsRef.current = next
    const nextDuration = projectDuration(next)
    seek(Math.min(playheadMs, nextDuration))
  }

  const updateCue = (index: number, cue: EditorCue) => {
    setCues((current) => reindex(current.map((item, cueIndex) => cueIndex === index ? cue : item)))
  }

  const updateActiveTime = (field: 'start_ms' | 'end_ms', value: string) => {
    const parsed = parseClock(value)
    if (activeCue === null || selectedCue === null || parsed === null) return
    const next = field === 'start_ms'
      ? { ...activeCue, start_ms: clamp(parsed, 0, activeCue.end_ms - 1) }
      : { ...activeCue, end_ms: clamp(parsed, activeCue.start_ms + 1, durationMs) }
    updateCue(selectedCue, next)
  }

  const startExport = async () => {
    if (!video) { setMessage('Đưa một video vào timeline trước.'); return }
    if (!outputDir.trim()) { setMessage('Chọn thư mục xuất trước.'); return }
    if (audio && audioOffsetMs >= durationMs) { setMessage('Audio phải bắt đầu trước khi video kết thúc.'); return }
    setResult(null)
    setMessage('Đang chuẩn bị xuất video...')
    try {
      await updateSettings({
        editor_output_dir: outputDir,
        editor_resolution: resolution,
        editor_fps: fps,
        editor_encoder: encoder,
        editor_audio_mode: audioMode,
        editor_source_volume: sourceVolume,
        editor_external_volume: externalVolume,
        editor_subtitle_font_size: fontSize,
        editor_subtitle_margin: subtitleMargin,
        editor_timeline_zoom: zoom,
      })
      setTaskId(await startEditorExport({
        galaxy_project_id: galaxyProjectId,
        video_path: video.path,
        output_dir: outputDir,
        project_name: projectName,
        audio_path: audioMuted ? undefined : audio?.path,
        cues: subtitleVisible ? cues : [],
        segments: videoSegments.length === 1
          && videoSegments[0].source_start_ms === 0
          && videoSegments[0].source_end_ms === sourceDurationMs
          ? []
          : videoSegments.map(({ source_start_ms, source_end_ms }) => ({ source_start_ms, source_end_ms })),
        audio_offset_ms: audioOffsetMs,
        audio_mode: audioMode,
        source_volume: sourceVolume,
        external_volume: externalVolume,
        resolution,
        fps,
        encoder,
        quality,
        subtitle_font_size: fontSize,
        subtitle_margin: subtitleMargin,
      }))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const removeTimelineAudio = () => { audioRef.current?.pause(); setAudio(null); setAudioOffsetMs(0) }
  const removeTimelineCues = () => { setCues([]); setSelectedCue(null) }

  return (
    <div className="editor-page">
      <header className="workspace-heading editor-heading">
        <div><h1>Dựng video</h1><p>Ghép video, voice và phụ đề trên một timeline gọn nhẹ.</p></div>
        <span className="editor-project-state">{video ? `${video.width}×${video.height} · ${video.fps.toFixed(2)} fps · ${formatClock(durationMs)}` : 'Chưa có project'}</span>
      </header>

      <div className="editor-workspace-grid">
        <aside className="section-card editor-media-bin">
          <div className="section-header compact"><h2 className="section-title">Tệp phương tiện</h2><span className="field-hint">{assets.length} tệp</span></div>
          <div className="editor-import-actions">
            <button className="btn" onClick={() => void importMedia('video')}>Thêm video</button>
            <button className="btn" onClick={() => void importMedia('audio')}>Thêm audio</button>
            <button className="btn" onClick={() => void importSrt()}>Thêm SRT</button>
          </div>
          {!hasNativeDialogs() && <div className="input-action editor-manual-path"><input value={manualPath} placeholder="Đường dẫn tệp" onChange={(event) => setManualPath(event.target.value)} /><button className="btn" onClick={() => void importMedia('video', manualPath)}>Nạp</button></div>}
          <div className="editor-asset-list">
            {assets.map((asset) => (
              <div
                className="editor-asset"
                key={asset.id}
                draggable
                onDragStart={(event) => event.dataTransfer.setData('application/x-galaxy-editor-asset', asset.id)}
              >
                <span className={`asset-kind ${asset.kind}`}>{asset.kind === 'subtitle' ? 'SRT' : asset.kind === 'video' ? 'VID' : 'AUD'}</span>
                <div><strong>{asset.name}</strong><small>{asset.kind === 'subtitle' ? `${asset.cues.length} câu` : formatClock(asset.duration_seconds * 1000)}</small></div>
                <button className="asset-add" title="Đưa vào timeline" onClick={() => activateAsset(asset.id)}>+</button>
                <button className="asset-remove" title="Gỡ khỏi danh sách" onClick={() => removeAsset(asset.id)}>×</button>
              </div>
            ))}
            {!assets.length && <div className="editor-empty-bin">Nhập tệp, sau đó kéo xuống timeline.</div>}
          </div>
        </aside>

        <section className="section-card editor-preview-panel">
          <div className="editor-video-stage" style={{ aspectRatio: video ? `${video.width}/${video.height}` : '16/9' }}>
            {video ? (
              <>
                <video
                  ref={videoRef}
                  src={video.url}
                  controls
                  style={{ visibility: videoVisible ? 'visible' : 'hidden' }}
                  preload="metadata"
                  onTimeUpdate={(event) => syncPlayheadFromVideo(event.currentTarget)}
                  onSeeked={(event) => syncPlayheadFromVideo(event.currentTarget)}
                  onCanPlay={() => setPreviewError(false)}
                  onError={() => setPreviewError(true)}
                />
                {subtitleAtPlayhead && <div className="editor-subtitle-preview" style={{ fontSize: `${Math.max(12, fontSize)}px`, bottom: `${subtitleMargin}px` }}>{subtitleAtPlayhead}</div>}
                {previewError && <div className="editor-preview-error">WebView2 không phát được codec của video này. Hãy đổi sang MP4 H.264/AAC để xem trước; engine xuất vẫn giữ nguyên file nguồn.</div>}
              </>
            ) : <div className="editor-video-empty">Đưa video vào timeline để xem trước</div>}
          </div>
          {audio && <audio ref={audioRef} src={audio.url} preload="metadata" />}
        </section>

        <aside className="section-card editor-inspector">
          <h2 className="section-title">Phụ đề</h2>
          <CueList cues={cues} selected={selectedCue} onSelect={(index) => { setSelectedCue(index); seek(cues[index].start_ms) }} />
          {activeCue ? (
            <div className="cue-editor">
              <div className="field-grid">
                <div className="field"><label>Bắt đầu</label><ClockInput value={activeCue.start_ms} onCommit={(value) => updateActiveTime('start_ms', value)} /></div>
                <div className="field"><label>Kết thúc</label><ClockInput value={activeCue.end_ms} onCommit={(value) => updateActiveTime('end_ms', value)} /></div>
              </div>
              <textarea className="srt-editor" rows={3} value={activeCue.text} onChange={(event) => updateCue(selectedCue!, { ...activeCue, text: event.target.value })} />
              <div className="toolbar-row"><button className="btn" onClick={() => { setCues((current) => reindex(current.filter((_cue, index) => index !== selectedCue))); setSelectedCue(null) }}>Xóa câu</button><button className="btn" disabled={durationMs < 2} onClick={() => { const start = Math.min(playheadMs, durationMs - 1); setCues((current) => reindex([...current, { index: current.length + 1, start_ms: start, end_ms: Math.min(durationMs, start + 2000), text: 'Phụ đề mới' }].sort((a, b) => a.start_ms - b.start_ms))) }}>Thêm câu</button></div>
            </div>
          ) : <p className="field-hint">Chọn một cue trên bảng hoặc timeline để sửa.</p>}
          <div className="toolbar-row editor-cue-tools"><button className="btn" disabled={!cues.length || !durationMs} onClick={() => setCues(fitCues(cues, durationMs))}>Căn theo video</button><button className="btn" disabled={!cues.length} onClick={removeTimelineCues}>Xóa track sub</button></div>
        </aside>
      </div>

      <section className="section-card editor-timeline-panel">
        <div className="editor-timeline-toolbar">
          <div><strong>Timeline</strong><span>{formatClock(playheadMs, true)} / {formatClock(durationMs, true)}</span></div>
          <div className="editor-cut-tools">
            <button className="btn" disabled={!video || videoLocked} onClick={splitAtPlayhead}>Tách tại playhead</button>
            <button className="btn danger" disabled={selectedSegment === null || videoSegments.length <= 1 || videoLocked} onClick={deleteSelectedSegment}>Xóa đoạn</button>
          </div>
          <label>Thu phóng <input type="range" min="0.1" max="120" step="0.1" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /><output>{zoom.toFixed(1)} px/s</output></label>
          {audio && <button className="btn" onClick={removeTimelineAudio}>Xóa audio</button>}
        </div>
        <Timeline
          durationMs={Math.max(1, durationMs)}
          videoName={video?.name}
          videoSegments={videoSegments}
          sourceDurationMs={sourceDurationMs}
          selectedSegment={selectedSegment}
          audioName={audio?.name}
          audioDurationMs={Math.round((audio?.duration_seconds ?? 0) * 1000)}
          audioOffsetMs={audioOffsetMs}
          cues={cues}
          selectedCue={selectedCue}
          playheadMs={playheadMs}
          zoom={zoom}
          onSeek={seek}
          onSelectCue={setSelectedCue}
          onSelectSegment={setSelectedSegment}
          onChangeVideoSegment={changeVideoSegment}
          onChangeCue={updateCue}
          onAudioOffset={setAudioOffsetMs}
          onDropAsset={activateAsset}
          subtitleVisible={subtitleVisible}
          subtitleLocked={subtitleLocked}
          videoVisible={videoVisible}
          videoLocked={videoLocked}
          audioMuted={audioMuted}
          audioLocked={audioLocked}
          onToggleSubtitleVisible={() => setSubtitleVisible((value) => !value)}
          onToggleSubtitleLocked={() => setSubtitleLocked((value) => !value)}
          onToggleVideoVisible={() => setVideoVisible((value) => !value)}
          onToggleVideoLocked={() => setVideoLocked((value) => !value)}
          onToggleAudioMuted={() => setAudioMuted((value) => !value)}
          onToggleAudioLocked={() => setAudioLocked((value) => !value)}
        />
      </section>

      <section className="section-card editor-export-panel">
        <div className="section-header compact"><h2 className="section-title">Xuất video</h2><span className="field-hint">MP4 · H.264 · AAC</span></div>
        <div className="field-grid editor-export-grid">
          <div className="field field-wide"><label>Thư mục xuất</label><div className="input-action"><input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} /><button className="btn" onClick={() => void pickFolder().then((path) => { if (path) setOutputDir(path) })}>Chọn</button></div></div>
          <div className="field"><label>Tên project</label><input type="text" value={projectName} onChange={(event) => setProjectName(event.target.value)} /></div>
          <OptionField label="Độ phân giải" value={resolution} onChange={setResolution} options={settingsMetaQuery.data?.editor_resolutions} />
          <OptionField label="FPS" value={fps} onChange={setFps} options={settingsMetaQuery.data?.editor_fps} />
          <OptionField label="Encoder" value={encoder} onChange={setEncoder} options={settingsMetaQuery.data?.editor_encoders} />
          <OptionField label="Âm thanh" value={audioMode} onChange={setAudioMode} options={settingsMetaQuery.data?.editor_audio_modes} />
          <div className="field"><label>Âm lượng video: {sourceVolume}%</label><input type="range" min="0" max="100" value={sourceVolume} onChange={(event) => setSourceVolume(Number(event.target.value))} /></div>
          <div className="field"><label>Âm lượng audio: {externalVolume}%</label><input type="range" min="0" max="100" value={externalVolume} onChange={(event) => setExternalVolume(Number(event.target.value))} /></div>
          <div className="field"><label>Chất lượng CRF: {quality}</label><input type="range" min="14" max="32" value={quality} onChange={(event) => setQuality(Number(event.target.value))} /></div>
          <div className="field"><label>Cỡ chữ sub</label><input type="number" min="10" max="72" value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} /></div>
          <div className="field"><label>Lề sub</label><input type="number" min="0" max="500" value={subtitleMargin} onChange={(event) => setSubtitleMargin(Number(event.target.value))} /></div>
        </div>
        <div className="editor-export-actions">
          <button className="btn accent" disabled={!video || running} onClick={() => void startExport()}>{running ? 'Đang xuất...' : 'Xuất video'}</button>
          <button className="btn danger" disabled={!running || !taskId} onClick={() => { if (taskId) void cancelTask(taskId) }}>Dừng</button>
          {result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}
          <span>{message}</span>
        </div>
        {result && <div className="editor-result"><video controls preload="metadata" src={result.video_url} /><div><strong>{result.video_path}</strong>{result.warnings.map((warning) => <small key={warning}>{warning}</small>)}</div></div>}
      </section>
    </div>
  )
}

function OptionField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options?: { code: string; label: string }[] }) {
  return <div className="field"><label>{label}</label><select value={value} onChange={(event) => onChange(event.target.value)}>{(options ?? [{ code: value, label: value }]).map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}</select></div>
}

function ClockInput({ value, onCommit }: { value: number; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(() => formatClock(value, true))
  useEffect(() => setDraft(formatClock(value, true)), [value])
  return <input type="text" value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => onCommit(draft)} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
}

function CueList({ cues, selected, onSelect }: { cues: EditorCue[]; selected: number | null; onSelect: (index: number) => void }) {
  const rowHeight = 48
  const height = 238
  const [scrollTop, setScrollTop] = useState(0)
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 3)
  const end = Math.min(cues.length, Math.ceil((scrollTop + height) / rowHeight) + 3)
  return (
    <div className="cue-list" style={{ height }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
      <div style={{ height: cues.length * rowHeight, position: 'relative' }}>
        {cues.slice(start, end).map((cue, offset) => {
          const index = start + offset
          return <button key={`${cue.index}-${cue.start_ms}`} className={`cue-row${selected === index ? ' selected' : ''}`} style={{ top: index * rowHeight, height: rowHeight }} onClick={() => onSelect(index)}><span>{cue.index}</span><time>{formatClock(cue.start_ms, true)}</time><strong>{cue.text.replace(/\n/g, ' ')}</strong></button>
        })}
      </div>
    </div>
  )
}

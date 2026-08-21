import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

import type { EditorCue } from '../../api/editor'
import {
  MIN_CUE_DURATION_MS,
  TRACK_LABEL_WIDTH,
  clamp,
  cueOverviewIntervals,
  formatClock,
  msToPx,
  pxToMs,
  rulerStepSeconds,
  snapMs,
  visibleCues,
  visibleTimeRange,
} from './geometry'
import type { VideoSegment } from './segments'
import { MIN_VIDEO_SEGMENT_MS, segmentDuration, segmentTimelineStart } from './segments'

interface TimelineProps {
  durationMs: number
  videoName?: string
  videoSegments?: VideoSegment[]
  sourceDurationMs?: number
  selectedSegment?: number | null
  audioName?: string
  audioDurationMs?: number
  audioOffsetMs: number
  cues: EditorCue[]
  selectedCue: number | null
  playheadMs: number
  zoom: number
  onSeek: (milliseconds: number) => void
  onSelectCue: (index: number) => void
  onChangeCue: (index: number, cue: EditorCue) => void
  onSelectSegment?: (index: number) => void
  onChangeVideoSegment?: (index: number, segment: VideoSegment) => void
  onAudioOffset: (milliseconds: number) => void
  onDropAsset: (assetId: string, milliseconds: number) => void
  subtitleVisible?: boolean
  subtitleLocked?: boolean
  videoVisible?: boolean
  videoLocked?: boolean
  audioMuted?: boolean
  audioLocked?: boolean
  onToggleSubtitleVisible?: () => void
  onToggleSubtitleLocked?: () => void
  onToggleVideoVisible?: () => void
  onToggleVideoLocked?: () => void
  onToggleAudioMuted?: () => void
  onToggleAudioLocked?: () => void
}

interface DragState {
  type: 'audio' | 'cue-move' | 'cue-start' | 'cue-end' | 'video-start' | 'video-end'
  index?: number
  startX: number
  startMs: number
  endMs: number
  sourceStartMs?: number
  sourceEndMs?: number
}

const RULER_HEIGHT = 28
const TRACK_HEIGHT = 52
const SVG_HEIGHT = RULER_HEIGHT + TRACK_HEIGHT * 3

export function Timeline({
  durationMs,
  videoName,
  videoSegments = [],
  sourceDurationMs = durationMs,
  selectedSegment = null,
  audioName,
  audioDurationMs = 0,
  audioOffsetMs,
  cues,
  selectedCue,
  playheadMs,
  zoom,
  onSeek,
  onSelectCue,
  onChangeCue,
  onSelectSegment = () => undefined,
  onChangeVideoSegment = () => undefined,
  onAudioOffset,
  onDropAsset,
  subtitleVisible = true,
  subtitleLocked = false,
  videoVisible = true,
  videoLocked = false,
  audioMuted = false,
  audioLocked = false,
  onToggleSubtitleVisible = () => undefined,
  onToggleSubtitleLocked = () => undefined,
  onToggleVideoVisible = () => undefined,
  onToggleVideoLocked = () => undefined,
  onToggleAudioMuted = () => undefined,
  onToggleAudioLocked = () => undefined,
}: TimelineProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const playheadPointerRef = useRef<number | null>(null)
  const [viewport, setViewport] = useState({ left: 0, width: 900 })
  const pixelsPerSecond = clamp(zoom, 0.1, 300)
  const contentWidth = Math.max(viewport.width, TRACK_LABEL_WIDTH + msToPx(durationMs, pixelsPerSecond) + 24)
  const [visibleStart, visibleEnd] = visibleTimeRange(viewport.left, viewport.width, pixelsPerSecond)
  const cuesInView = useMemo(() => visibleCues(cues, visibleStart, visibleEnd), [cues, visibleStart, visibleEnd])
  const useOverview = cuesInView.length > 320
  const renderedCues = useOverview ? cuesInView.filter((cue) => cues.indexOf(cue) === selectedCue) : cuesInView
  const overviewIntervals = useMemo(() => useOverview ? cueOverviewIntervals(cuesInView, pixelsPerSecond) : [], [cuesInView, pixelsPerSecond, useOverview])
  const stepSeconds = rulerStepSeconds(pixelsPerSecond)
  const firstTick = Math.max(0, Math.floor(visibleStart / 1000 / stepSeconds) * stepSeconds)
  const lastTick = Math.min(Math.ceil(durationMs / 1000), Math.ceil(visibleEnd / 1000 / stepSeconds) * stepSeconds)
  const ticks: number[] = []
  for (let second = firstTick; second <= lastTick; second += stepSeconds) ticks.push(second)

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const update = () => setViewport({ left: element.scrollLeft, width: element.clientWidth })
    update()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    observer?.observe(element)
    return () => observer?.disconnect()
  }, [])

  const positionX = (milliseconds: number) => TRACK_LABEL_WIDTH + msToPx(milliseconds, pixelsPerSecond)
  const eventTime = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return clamp(snapMs(pxToMs(event.clientX - rect.left - TRACK_LABEL_WIDTH, pixelsPerSecond)), 0, durationMs)
  }
  const beginDrag = (event: ReactPointerEvent<SVGElement>, state: Omit<DragState, 'startX'>) => {
    event.stopPropagation()
    if (state.index !== undefined) {
      if (state.type.startsWith('video')) onSelectSegment(state.index)
      else onSelectCue(state.index)
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { ...state, startX: event.clientX }
  }
  const moveDrag = (event: ReactPointerEvent<SVGElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const delta = snapMs(pxToMs(event.clientX - drag.startX, pixelsPerSecond))
    if (drag.type === 'video-start' || drag.type === 'video-end') {
      if (drag.index === undefined || drag.sourceStartMs === undefined || drag.sourceEndMs === undefined) return
      const segment = videoSegments[drag.index]
      if (!segment) return
      const next = drag.type === 'video-start'
        ? { ...segment, source_start_ms: clamp(drag.sourceStartMs + delta, 0, drag.sourceEndMs - MIN_VIDEO_SEGMENT_MS) }
        : { ...segment, source_end_ms: clamp(drag.sourceEndMs + delta, drag.sourceStartMs + MIN_VIDEO_SEGMENT_MS, sourceDurationMs) }
      onChangeVideoSegment(drag.index, next)
      return
    }
    if (drag.type === 'audio') {
      onAudioOffset(clamp(drag.startMs + delta, 0, Math.max(0, durationMs - 1)))
      return
    }
    if (drag.index === undefined) return
    const cue = cues[drag.index]
    if (!cue) return
    if (drag.type === 'cue-move') {
      const length = drag.endMs - drag.startMs
      const start = clamp(drag.startMs + delta, 0, Math.max(0, durationMs - length))
      onChangeCue(drag.index, { ...cue, start_ms: start, end_ms: start + length })
    } else if (drag.type === 'cue-start') {
      onChangeCue(drag.index, { ...cue, start_ms: clamp(drag.startMs + delta, 0, drag.endMs - MIN_CUE_DURATION_MS) })
    } else {
      onChangeCue(drag.index, { ...cue, end_ms: clamp(drag.endMs + delta, drag.startMs + MIN_CUE_DURATION_MS, durationMs) })
    }
  }
  const endDrag = () => { dragRef.current = null }
  const audioEnd = Math.min(durationMs, audioOffsetMs + audioDurationMs)

  return (
    <div className="editor-timeline-drop" onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' }} onDrop={(event) => {
      event.preventDefault()
      const assetId = event.dataTransfer.getData('application/x-galaxy-editor-asset')
      const rect = event.currentTarget.getBoundingClientRect()
      const milliseconds = clamp(snapMs(pxToMs(event.clientX - rect.left + viewport.left - TRACK_LABEL_WIDTH, pixelsPerSecond)), 0, durationMs)
      if (assetId) onDropAsset(assetId, milliseconds)
    }}>
      <div className="editor-timeline-viewport" ref={viewportRef} onScroll={(event) => setViewport({ left: event.currentTarget.scrollLeft, width: event.currentTarget.clientWidth })}>
        <svg className="editor-timeline-svg" width={contentWidth} height={SVG_HEIGHT} viewBox={`0 0 ${contentWidth} ${SVG_HEIGHT}`} onPointerDown={(event) => {
          if (event.button !== 0) return
          event.currentTarget.setPointerCapture?.(event.pointerId)
          playheadPointerRef.current = event.pointerId
          onSeek(eventTime(event))
        }} onPointerMove={(event) => { if (playheadPointerRef.current === event.pointerId) onSeek(eventTime(event)) }} onPointerUp={(event) => {
          if (playheadPointerRef.current !== event.pointerId) return
          playheadPointerRef.current = null
          event.currentTarget.releasePointerCapture?.(event.pointerId)
        }} onPointerCancel={() => { playheadPointerRef.current = null }}>
          <rect width={contentWidth} height={SVG_HEIGHT} className="timeline-bg" />
          {ticks.map((second) => {
            const x = positionX(second * 1000)
            return <g key={second}><line x1={x} x2={x} y1={12} y2={SVG_HEIGHT} className="timeline-grid-line" /><text x={x + 5} y={18} className="timeline-time">{formatClock(second * 1000)}</text></g>
          })}
          {[0, 1, 2].map((track) => <rect key={track} x={TRACK_LABEL_WIDTH} y={RULER_HEIGHT + track * TRACK_HEIGHT} width={contentWidth - TRACK_LABEL_WIDTH} height={TRACK_HEIGHT} className="timeline-track" />)}

          {subtitleVisible && overviewIntervals.map(([start, end], index) => <rect key={`${start}-${end}-${index}`} x={TRACK_LABEL_WIDTH + start} y={RULER_HEIGHT + 14} width={Math.max(1, end - start)} height={TRACK_HEIGHT - 28} className="timeline-cue-overview" />)}
          {subtitleVisible && renderedCues.map((cue) => {
            const index = cues.indexOf(cue)
            const x = positionX(cue.start_ms)
            const width = Math.max(4, msToPx(cue.end_ms - cue.start_ms, pixelsPerSecond))
            return <g key={`${cue.index}-${cue.start_ms}`} onPointerDown={() => onSelectCue(index)}>
              <Clip x={x} y={RULER_HEIGHT + 7} width={width} label={cue.text.replace(/\n/g, ' ')} kind={selectedCue === index ? 'cue selected' : 'cue'} onPointerDown={subtitleLocked ? undefined : (event) => beginDrag(event, { type: 'cue-move', index, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={subtitleLocked ? undefined : moveDrag} onPointerUp={subtitleLocked ? undefined : endDrag} />
              {!subtitleLocked && <rect x={x} y={RULER_HEIGHT + 7} width={6} height={TRACK_HEIGHT - 14} className="timeline-handle" onPointerDown={(event) => beginDrag(event, { type: 'cue-start', index, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
              {!subtitleLocked && <rect x={x + width - 6} y={RULER_HEIGHT + 7} width={6} height={TRACK_HEIGHT - 14} className="timeline-handle" onPointerDown={(event) => beginDrag(event, { type: 'cue-end', index, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
            </g>
          })}

          {videoVisible && videoName && videoSegments.map((segment, index) => {
            const timelineStart = segmentTimelineStart(videoSegments, index)
            const x = positionX(timelineStart)
            const width = Math.max(4, msToPx(segmentDuration(segment), pixelsPerSecond))
            return <g key={segment.id} onPointerDown={(event) => { event.stopPropagation(); onSelectSegment(index) }}>
              <Clip x={x} y={RULER_HEIGHT + TRACK_HEIGHT + 7} width={width} label={`${videoName} · ${index + 1}`} kind={selectedSegment === index ? 'video selected' : 'video'} />
              {!videoLocked && <rect x={x} y={RULER_HEIGHT + TRACK_HEIGHT + 7} width={7} height={TRACK_HEIGHT - 14} className="timeline-video-handle" onPointerDown={(event) => beginDrag(event, { type: 'video-start', index, startMs: timelineStart, endMs: timelineStart + segmentDuration(segment), sourceStartMs: segment.source_start_ms, sourceEndMs: segment.source_end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
              {!videoLocked && <rect x={x + width - 7} y={RULER_HEIGHT + TRACK_HEIGHT + 7} width={7} height={TRACK_HEIGHT - 14} className="timeline-video-handle" onPointerDown={(event) => beginDrag(event, { type: 'video-end', index, startMs: timelineStart, endMs: timelineStart + segmentDuration(segment), sourceStartMs: segment.source_start_ms, sourceEndMs: segment.source_end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
            </g>
          })}

          {audioName && audioEnd > audioOffsetMs && <Clip x={positionX(audioOffsetMs)} y={RULER_HEIGHT + TRACK_HEIGHT * 2 + 7} width={Math.max(4, msToPx(audioEnd - audioOffsetMs, pixelsPerSecond))} label={audioName} kind={audioMuted ? 'audio muted' : 'audio'} onPointerDown={audioLocked ? undefined : (event) => beginDrag(event, { type: 'audio', startMs: audioOffsetMs, endMs: audioEnd })} onPointerMove={audioLocked ? undefined : moveDrag} onPointerUp={audioLocked ? undefined : endDrag} />}
          <line x1={positionX(playheadMs)} x2={positionX(playheadMs)} y1={0} y2={SVG_HEIGHT} className="timeline-playhead-hit" />
          <line x1={positionX(playheadMs)} x2={positionX(playheadMs)} y1={0} y2={SVG_HEIGHT} className="timeline-playhead" />
          <path d={`M ${positionX(playheadMs) - 5} 0 L ${positionX(playheadMs) + 5} 0 L ${positionX(playheadMs)} 8 Z`} className="timeline-playhead-head" />
        </svg>
        <div className="timeline-labels" style={{ left: viewport.left }}>
          <div className="timeline-label-spacer" />
          <TrackLabel label="Phụ đề" enabled={subtitleVisible} locked={subtitleLocked} onToggleEnabled={onToggleSubtitleVisible} onToggleLocked={onToggleSubtitleLocked} />
          <TrackLabel label="Video" enabled={videoVisible} locked={videoLocked} onToggleEnabled={onToggleVideoVisible} onToggleLocked={onToggleVideoLocked} />
          <TrackLabel label="Audio" enabled={!audioMuted} locked={audioLocked} audio onToggleEnabled={onToggleAudioMuted} onToggleLocked={onToggleAudioLocked} />
        </div>
      </div>
    </div>
  )
}

function TrackLabel({ label, enabled, locked, audio = false, onToggleEnabled, onToggleLocked }: { label: string; enabled: boolean; locked: boolean; audio?: boolean; onToggleEnabled: () => void; onToggleLocked: () => void }) {
  return <div className="timeline-track-label"><strong>{label}</strong><button type="button" aria-pressed={enabled} title={enabled ? 'Track đang bật' : 'Track đang tắt'} onClick={onToggleEnabled}>{audio ? (enabled ? 'Bật' : 'Tắt') : (enabled ? 'Hiện' : 'Ẩn')}</button><button type="button" aria-pressed={locked} title={locked ? 'Track đang khóa' : 'Track đang mở'} onClick={onToggleLocked}>{locked ? 'Khóa' : 'Mở'}</button></div>
}

interface ClipProps {
  x: number
  y: number
  width: number
  label: string
  kind: string
  onPointerDown?: (event: ReactPointerEvent<SVGElement>) => void
  onPointerMove?: (event: ReactPointerEvent<SVGElement>) => void
  onPointerUp?: (event: ReactPointerEvent<SVGElement>) => void
}

function Clip({ x, y, width, label, kind, onPointerDown, onPointerMove, onPointerUp }: ClipProps) {
  return <g className={`timeline-clip ${kind}`} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}><rect x={x} y={y} width={width} height={TRACK_HEIGHT - 14} rx={3} />{width > 28 && <text x={x + 9} y={y + 24}>{label.slice(0, Math.max(4, Math.floor(width / 7)))}</text>}</g>
}

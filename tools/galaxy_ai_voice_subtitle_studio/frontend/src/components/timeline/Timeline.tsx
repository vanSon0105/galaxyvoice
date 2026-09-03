import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

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
  visibleTimeRange,
} from './geometry'
import type {
  EditorTrack,
  EditorTrackKind,
  TimelineCue,
  TimelineMediaClip,
  TimelineSelection,
} from './tracks'
import { clipDuration } from './tracks'

interface TimelineProps {
  durationMs: number
  tracks: EditorTrack[]
  selection: TimelineSelection | null
  playheadMs: number
  zoom: number
  onSeek: (milliseconds: number) => void
  onSelect: (selection: TimelineSelection | null) => void
  onChangeCue: (trackId: string, cueId: string, cue: TimelineCue) => void
  onChangeClip: (trackId: string, clipId: string, clip: TimelineMediaClip) => void
  onDropAsset: (assetId: string, milliseconds: number, trackId: string) => void
  onToggleTrackEnabled: (trackId: string) => void
  onToggleTrackLocked: (trackId: string) => void
  onAddTrack: (kind: EditorTrackKind) => void
}

interface DragState {
  type: 'cue-move' | 'cue-start' | 'cue-end' | 'clip-move' | 'clip-start' | 'clip-end'
  trackId: string
  itemId: string
  startX: number
  startMs: number
  endMs: number
  sourceStartMs?: number
  sourceEndMs?: number
}

const RULER_HEIGHT = 28
const TRACK_HEIGHT = 52
const MIN_MEDIA_CLIP_MS = 100

export function Timeline({
  durationMs,
  tracks,
  selection,
  playheadMs,
  zoom,
  onSeek,
  onSelect,
  onChangeCue,
  onChangeClip,
  onDropAsset,
  onToggleTrackEnabled,
  onToggleTrackLocked,
  onAddTrack,
}: TimelineProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const playheadPointerRef = useRef<number | null>(null)
  const [viewport, setViewport] = useState({ left: 0, width: 900 })
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const pixelsPerSecond = clamp(zoom, 0.1, 300)
  const svgHeight = RULER_HEIGHT + TRACK_HEIGHT * Math.max(1, tracks.length)
  const contentWidth = Math.max(viewport.width, TRACK_LABEL_WIDTH + msToPx(durationMs, pixelsPerSecond) + 24)
  const [visibleStart, visibleEnd] = visibleTimeRange(viewport.left, viewport.width, pixelsPerSecond)
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
    onSelect({ trackId: state.trackId, itemId: state.itemId })
    event.currentTarget.setPointerCapture?.(event.pointerId)
    dragRef.current = { ...state, startX: event.clientX }
  }
  const moveDrag = (event: ReactPointerEvent<SVGElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const delta = snapMs(pxToMs(event.clientX - drag.startX, pixelsPerSecond))
    const track = tracks.find((candidate) => candidate.id === drag.trackId)
    if (!track || track.locked) return
    if (drag.type.startsWith('cue') && track.kind === 'subtitle') {
      const cue = track.cues.find((candidate) => candidate.id === drag.itemId)
      if (!cue) return
      if (drag.type === 'cue-move') {
        const length = drag.endMs - drag.startMs
        const start = clamp(drag.startMs + delta, 0, Math.max(0, durationMs - length))
        onChangeCue(track.id, cue.id, { ...cue, start_ms: start, end_ms: start + length })
      } else if (drag.type === 'cue-start') {
        onChangeCue(track.id, cue.id, { ...cue, start_ms: clamp(drag.startMs + delta, 0, drag.endMs - MIN_CUE_DURATION_MS) })
      } else {
        onChangeCue(track.id, cue.id, { ...cue, end_ms: clamp(drag.endMs + delta, drag.startMs + MIN_CUE_DURATION_MS, durationMs) })
      }
      return
    }
    if (!drag.type.startsWith('clip') || track.kind === 'subtitle') return
    const clip = track.clips.find((candidate) => candidate.id === drag.itemId)
    if (!clip || drag.sourceStartMs === undefined || drag.sourceEndMs === undefined) return
    if (drag.type === 'clip-move') {
      onChangeClip(track.id, clip.id, { ...clip, timeline_start_ms: Math.max(0, drag.startMs + delta) })
    } else if (drag.type === 'clip-start') {
      const applied = clamp(delta, -drag.sourceStartMs, drag.sourceEndMs - drag.sourceStartMs - MIN_MEDIA_CLIP_MS)
      onChangeClip(track.id, clip.id, {
        ...clip,
        timeline_start_ms: Math.max(0, drag.startMs + applied),
        source_start_ms: drag.sourceStartMs + applied,
      })
    } else {
      const sourceDuration = Math.round(clip.media.duration_seconds * 1000)
      onChangeClip(track.id, clip.id, {
        ...clip,
        source_end_ms: clamp(drag.sourceEndMs + delta, drag.sourceStartMs + MIN_MEDIA_CLIP_MS, sourceDuration),
      })
    }
  }
  const endDrag = () => { dragRef.current = null }

  return (
    <div className="editor-timeline-drop">
      <div className="editor-timeline-viewport" ref={viewportRef} onScroll={(event) => setViewport({ left: event.currentTarget.scrollLeft, width: event.currentTarget.clientWidth })}>
        <svg
          className="editor-timeline-svg"
          width={contentWidth}
          height={svgHeight}
          viewBox={`0 0 ${contentWidth} ${svgHeight}`}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' }}
          onDrop={(event) => {
            event.preventDefault()
            const assetId = event.dataTransfer.getData('application/x-galaxy-editor-asset')
            const rect = event.currentTarget.getBoundingClientRect()
            const milliseconds = clamp(snapMs(pxToMs(event.clientX - rect.left - TRACK_LABEL_WIDTH, pixelsPerSecond)), 0, durationMs)
            const trackIndex = clamp(Math.floor((event.clientY - rect.top - RULER_HEIGHT) / TRACK_HEIGHT), 0, tracks.length - 1)
            if (assetId && tracks[trackIndex]) onDropAsset(assetId, milliseconds, tracks[trackIndex].id)
          }}
          onPointerDown={(event) => {
            if (event.button !== 0) return
            event.currentTarget.setPointerCapture?.(event.pointerId)
            playheadPointerRef.current = event.pointerId
            onSelect(null)
            onSeek(eventTime(event))
          }}
          onPointerMove={(event) => { if (playheadPointerRef.current === event.pointerId) onSeek(eventTime(event)) }}
          onPointerUp={(event) => {
            if (playheadPointerRef.current !== event.pointerId) return
            playheadPointerRef.current = null
            event.currentTarget.releasePointerCapture?.(event.pointerId)
          }}
          onPointerCancel={() => { playheadPointerRef.current = null }}
        >
          <rect width={contentWidth} height={svgHeight} className="timeline-bg" />
          {ticks.map((second) => {
            const x = positionX(second * 1000)
            return <g key={second}><line x1={x} x2={x} y1={12} y2={svgHeight} className="timeline-grid-line" /><text x={x + 5} y={18} className="timeline-time">{formatClock(second * 1000)}</text></g>
          })}
          {tracks.map((track, index) => <rect key={track.id} x={TRACK_LABEL_WIDTH} y={RULER_HEIGHT + index * TRACK_HEIGHT} width={contentWidth - TRACK_LABEL_WIDTH} height={TRACK_HEIGHT} className="timeline-track" />)}
          {tracks.map((track, trackIndex) => (
            <TrackItems
              key={track.id}
              track={track}
              trackIndex={trackIndex}
              selection={selection}
              visibleStart={visibleStart}
              visibleEnd={visibleEnd}
              pixelsPerSecond={pixelsPerSecond}
              positionX={positionX}
              beginDrag={beginDrag}
              moveDrag={moveDrag}
              endDrag={endDrag}
              onSelect={onSelect}
            />
          ))}
          <line x1={positionX(playheadMs)} x2={positionX(playheadMs)} y1={0} y2={svgHeight} className="timeline-playhead-hit" />
          <line x1={positionX(playheadMs)} x2={positionX(playheadMs)} y1={0} y2={svgHeight} className="timeline-playhead" />
          <path d={`M ${positionX(playheadMs) - 5} 0 L ${positionX(playheadMs) + 5} 0 L ${positionX(playheadMs)} 8 Z`} className="timeline-playhead-head" />
        </svg>
        <div className="timeline-labels" style={{ left: viewport.left, height: svgHeight }}>
          <div className="timeline-label-spacer" />
          {tracks.map((track) => (
            <TrackLabel key={track.id} track={track} onToggleEnabled={() => onToggleTrackEnabled(track.id)} onToggleLocked={() => onToggleTrackLocked(track.id)} />
          ))}
        </div>
      </div>
      <div className="timeline-add-track">
        <button type="button" className="timeline-add-button" title="Thêm track" aria-expanded={addMenuOpen} onClick={() => setAddMenuOpen((open) => !open)}>+</button>
        {addMenuOpen && <div className="timeline-add-menu" role="menu">
          {([['subtitle', 'Thêm line SRT'], ['video', 'Thêm line video'], ['audio', 'Thêm line audio']] as const).map(([kind, label]) => (
            <button key={kind} type="button" role="menuitem" onClick={() => { onAddTrack(kind); setAddMenuOpen(false) }}>{label}</button>
          ))}
        </div>}
        <span>Thêm track</span>
      </div>
    </div>
  )
}

function TrackItems({ track, trackIndex, selection, visibleStart, visibleEnd, pixelsPerSecond, positionX, beginDrag, moveDrag, endDrag, onSelect }: {
  track: EditorTrack
  trackIndex: number
  selection: TimelineSelection | null
  visibleStart: number
  visibleEnd: number
  pixelsPerSecond: number
  positionX: (milliseconds: number) => number
  beginDrag: (event: ReactPointerEvent<SVGElement>, state: Omit<DragState, 'startX'>) => void
  moveDrag: (event: ReactPointerEvent<SVGElement>) => void
  endDrag: () => void
  onSelect: (selection: TimelineSelection | null) => void
}) {
  const y = RULER_HEIGHT + trackIndex * TRACK_HEIGHT + 7
  const selected = (itemId: string) => selection?.trackId === track.id && selection.itemId === itemId
  const cuesInView = useMemo(
    () => track.kind === 'subtitle' ? track.cues.filter((cue) => cue.end_ms >= visibleStart && cue.start_ms <= visibleEnd) : [],
    [track, visibleStart, visibleEnd],
  )
  const useOverview = cuesInView.length > 320
  const overviewIntervals = useMemo(
    () => useOverview ? cueOverviewIntervals(cuesInView, pixelsPerSecond) : [],
    [cuesInView, pixelsPerSecond, useOverview],
  )
  if (!track.enabled) return null
  if (track.kind === 'subtitle') {
    const rendered = useOverview ? cuesInView.filter((cue) => selected(cue.id)) : cuesInView
    return <>
      {overviewIntervals.map(([start, end], index) => <rect key={`${start}-${end}-${index}`} x={TRACK_LABEL_WIDTH + start} y={y + 7} width={Math.max(1, end - start)} height={TRACK_HEIGHT - 28} className="timeline-cue-overview" />)}
      {rendered.map((cue) => {
        const x = positionX(cue.start_ms)
        const width = Math.max(4, msToPx(cue.end_ms - cue.start_ms, pixelsPerSecond))
        return <g key={cue.id} onPointerDown={(event) => { event.stopPropagation(); onSelect({ trackId: track.id, itemId: cue.id }) }}>
          <Clip x={x} y={y} width={width} label={cue.text.replace(/\n/g, ' ')} kind={selected(cue.id) ? 'cue selected' : 'cue'} onPointerDown={track.locked ? undefined : (event) => beginDrag(event, { type: 'cue-move', trackId: track.id, itemId: cue.id, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={track.locked ? undefined : moveDrag} onPointerUp={track.locked ? undefined : endDrag} />
          {!track.locked && <rect x={x} y={y} width={6} height={TRACK_HEIGHT - 14} className="timeline-handle" onPointerDown={(event) => beginDrag(event, { type: 'cue-start', trackId: track.id, itemId: cue.id, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
          {!track.locked && <rect x={x + width - 6} y={y} width={6} height={TRACK_HEIGHT - 14} className="timeline-handle" onPointerDown={(event) => beginDrag(event, { type: 'cue-end', trackId: track.id, itemId: cue.id, startMs: cue.start_ms, endMs: cue.end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
        </g>
      })}
    </>
  }
  return <>{track.clips.filter((clip) => clip.timeline_start_ms <= visibleEnd && clip.timeline_start_ms + clipDuration(clip) >= visibleStart).map((clip) => {
    const x = positionX(clip.timeline_start_ms)
    const width = Math.max(4, msToPx(clipDuration(clip), pixelsPerSecond))
    const kind = `${track.kind}${selected(clip.id) ? ' selected' : ''}`
    return <g key={clip.id} onPointerDown={(event) => { event.stopPropagation(); onSelect({ trackId: track.id, itemId: clip.id }) }}>
      <Clip x={x} y={y} width={width} label={clip.media.name} kind={kind} onPointerDown={track.locked ? undefined : (event) => beginDrag(event, { type: 'clip-move', trackId: track.id, itemId: clip.id, startMs: clip.timeline_start_ms, endMs: clip.timeline_start_ms + clipDuration(clip), sourceStartMs: clip.source_start_ms, sourceEndMs: clip.source_end_ms })} onPointerMove={track.locked ? undefined : moveDrag} onPointerUp={track.locked ? undefined : endDrag} />
      {!track.locked && <rect x={x} y={y} width={7} height={TRACK_HEIGHT - 14} className="timeline-video-handle" onPointerDown={(event) => beginDrag(event, { type: 'clip-start', trackId: track.id, itemId: clip.id, startMs: clip.timeline_start_ms, endMs: clip.timeline_start_ms + clipDuration(clip), sourceStartMs: clip.source_start_ms, sourceEndMs: clip.source_end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
      {!track.locked && <rect x={x + width - 7} y={y} width={7} height={TRACK_HEIGHT - 14} className="timeline-video-handle" onPointerDown={(event) => beginDrag(event, { type: 'clip-end', trackId: track.id, itemId: clip.id, startMs: clip.timeline_start_ms, endMs: clip.timeline_start_ms + clipDuration(clip), sourceStartMs: clip.source_start_ms, sourceEndMs: clip.source_end_ms })} onPointerMove={moveDrag} onPointerUp={endDrag} />}
    </g>
  })}</>
}

function TrackLabel({ track, onToggleEnabled, onToggleLocked }: { track: EditorTrack; onToggleEnabled: () => void; onToggleLocked: () => void }) {
  const enabledLabel = track.kind === 'audio' ? (track.enabled ? 'Bật' : 'Tắt') : (track.enabled ? 'Hiện' : 'Ẩn')
  return <div className="timeline-track-label"><strong>{track.name}</strong><button type="button" aria-pressed={track.enabled} title={track.enabled ? 'Track đang bật' : 'Track đang tắt'} onClick={onToggleEnabled}>{enabledLabel}</button><button type="button" aria-pressed={track.locked} title={track.locked ? 'Track đang khóa' : 'Track đang mở'} onClick={onToggleLocked}>{track.locked ? 'Khóa' : 'Mở'}</button></div>
}

function Clip({ x, y, width, label, kind, onPointerDown, onPointerMove, onPointerUp }: {
  x: number
  y: number
  width: number
  label: string
  kind: string
  onPointerDown?: (event: ReactPointerEvent<SVGElement>) => void
  onPointerMove?: (event: ReactPointerEvent<SVGElement>) => void
  onPointerUp?: (event: ReactPointerEvent<SVGElement>) => void
}) {
  return <g className={`timeline-clip ${kind}`} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}><rect x={x} y={y} width={width} height={TRACK_HEIGHT - 14} rx={3} />{width > 28 && <text x={x + 9} y={y + 24}>{label.slice(0, Math.max(4, Math.floor(width / 7)))}</text>}</g>
}

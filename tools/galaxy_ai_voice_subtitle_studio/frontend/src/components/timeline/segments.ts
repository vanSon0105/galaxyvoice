import { clamp } from './geometry'
import type { EditorCue } from '../../api/editor'

export const MIN_VIDEO_SEGMENT_MS = 100

export interface VideoSegment {
  id: string
  source_start_ms: number
  source_end_ms: number
}

export interface TimelineSourcePosition {
  index: number
  sourceMs: number
  timelineStartMs: number
  timelineEndMs: number
}

export function segmentDuration(segment: VideoSegment): number {
  return Math.max(0, segment.source_end_ms - segment.source_start_ms)
}

export function projectDuration(segments: VideoSegment[]): number {
  return segments.reduce((total, segment) => total + segmentDuration(segment), 0)
}

export function segmentTimelineStart(segments: VideoSegment[], index: number): number {
  return segments.slice(0, index).reduce((total, segment) => total + segmentDuration(segment), 0)
}

export function timelineToSource(
  segments: VideoSegment[],
  timelineMs: number,
): TimelineSourcePosition | null {
  if (!segments.length) return null
  const duration = projectDuration(segments)
  const target = clamp(timelineMs, 0, duration)
  let timelineStartMs = 0
  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index]
    const timelineEndMs = timelineStartMs + segmentDuration(segment)
    if (target < timelineEndMs || index === segments.length - 1) {
      return {
        index,
        sourceMs: segment.source_start_ms + clamp(target - timelineStartMs, 0, segmentDuration(segment)),
        timelineStartMs,
        timelineEndMs,
      }
    }
    timelineStartMs = timelineEndMs
  }
  return null
}

export function splitVideoSegment(
  segments: VideoSegment[],
  timelineMs: number,
): { segments: VideoSegment[]; selectedIndex: number } | null {
  const position = timelineToSource(segments, timelineMs)
  if (!position) return null
  const segment = segments[position.index]
  if (
    position.sourceMs - segment.source_start_ms < MIN_VIDEO_SEGMENT_MS
    || segment.source_end_ms - position.sourceMs < MIN_VIDEO_SEGMENT_MS
  ) return null
  const left = { ...segment, id: `${segment.id}-left`, source_end_ms: position.sourceMs }
  const right = { ...segment, id: `${segment.id}-right`, source_start_ms: position.sourceMs }
  return {
    segments: [
      ...segments.slice(0, position.index),
      left,
      right,
      ...segments.slice(position.index + 1),
    ],
    selectedIndex: position.index + 1,
  }
}

export function trimVideoSegment(
  segments: VideoSegment[],
  index: number,
  edge: 'start' | 'end',
  deltaMs: number,
): VideoSegment[] {
  const segment = segments[index]
  if (!segment) return segments
  const next = edge === 'start'
    ? {
        ...segment,
        source_start_ms: clamp(
          segment.source_start_ms + deltaMs,
          0,
          segment.source_end_ms - MIN_VIDEO_SEGMENT_MS,
        ),
      }
    : {
        ...segment,
        source_end_ms: clamp(
          segment.source_end_ms + deltaMs,
          segment.source_start_ms + MIN_VIDEO_SEGMENT_MS,
          Number.MAX_SAFE_INTEGER,
        ),
      }
  return segments.map((item, itemIndex) => itemIndex === index ? next : item)
}

export function rippleDeleteCues(
  cues: EditorCue[],
  removedStartMs: number,
  removedDurationMs: number,
): EditorCue[] {
  const removedEndMs = removedStartMs + removedDurationMs
  return cues.flatMap((cue) => {
    if (cue.end_ms <= removedStartMs) return [cue]
    if (cue.start_ms >= removedEndMs) {
      return [{ ...cue, start_ms: cue.start_ms - removedDurationMs, end_ms: cue.end_ms - removedDurationMs }]
    }
    if (cue.start_ms < removedStartMs && cue.end_ms > removedEndMs) {
      return [{ ...cue, end_ms: cue.end_ms - removedDurationMs }]
    }
    if (cue.start_ms < removedStartMs) return [{ ...cue, end_ms: removedStartMs }]
    if (cue.end_ms > removedEndMs) return [{ ...cue, start_ms: removedStartMs, end_ms: cue.end_ms - removedDurationMs }]
    return []
  }).filter((cue) => cue.end_ms > cue.start_ms)
}

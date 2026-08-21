import type { EditorCue } from '../../api/editor'

export const TRACK_LABEL_WIDTH = 88
export const MIN_CUE_DURATION_MS = 100

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}

export function msToPx(milliseconds: number, pixelsPerSecond: number): number {
  return milliseconds * pixelsPerSecond / 1000
}

export function pxToMs(pixels: number, pixelsPerSecond: number): number {
  return pixels * 1000 / Math.max(0.1, pixelsPerSecond)
}

export function snapMs(milliseconds: number, intervalMs = 100): number {
  return Math.round(milliseconds / intervalMs) * intervalMs
}

export function visibleTimeRange(
  scrollLeft: number,
  viewportWidth: number,
  pixelsPerSecond: number,
  overscanPx = 160,
): [number, number] {
  const left = Math.max(0, scrollLeft - TRACK_LABEL_WIDTH - overscanPx)
  const right = Math.max(0, scrollLeft + viewportWidth - TRACK_LABEL_WIDTH + overscanPx)
  return [Math.floor(pxToMs(left, pixelsPerSecond)), Math.ceil(pxToMs(right, pixelsPerSecond))]
}

export function visibleCues(cues: EditorCue[], startMs: number, endMs: number): EditorCue[] {
  return cues.filter((cue) => cue.end_ms >= startMs && cue.start_ms <= endMs)
}

export function cueOverviewIntervals(cues: EditorCue[], pixelsPerSecond: number): Array<[number, number]> {
  const intervals: Array<[number, number]> = []
  for (const cue of cues) {
    const start = Math.floor(msToPx(cue.start_ms, pixelsPerSecond))
    const end = Math.max(start + 1, Math.ceil(msToPx(cue.end_ms, pixelsPerSecond)))
    const previous = intervals.at(-1)
    if (previous && start <= previous[1] + 2) previous[1] = Math.max(previous[1], end)
    else intervals.push([start, end])
  }
  return intervals
}

export function hitTestCue(cues: EditorCue[], milliseconds: number): number | null {
  const index = cues.findIndex((cue) => cue.start_ms <= milliseconds && cue.end_ms >= milliseconds)
  return index >= 0 ? index : null
}

export function rulerStepSeconds(pixelsPerSecond: number): number {
  const candidates = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800]
  return candidates.find((step) => step * pixelsPerSecond >= 72) ?? 3600
}

export function formatClock(milliseconds: number, precise = false): string {
  const totalMs = Math.max(0, Math.round(milliseconds))
  const totalSeconds = Math.floor(totalMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor(totalSeconds % 3600 / 60)
  const seconds = totalSeconds % 60
  const base = hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return precise ? `${base}.${String(totalMs % 1000).padStart(3, '0')}` : base
}

export function parseClock(value: string): number | null {
  const normalized = value.trim().replace(',', '.')
  const parts = normalized.split(':')
  if (parts.length < 2 || parts.length > 3) return null
  const seconds = Number(parts.pop())
  const minutes = Number(parts.pop())
  const hours = parts.length ? Number(parts[0]) : 0
  if (![seconds, minutes, hours].every(Number.isFinite) || seconds < 0 || minutes < 0 || hours < 0) return null
  return Math.round((hours * 3600 + minutes * 60 + seconds) * 1000)
}

import type { EditorMedia } from '../../api/editor'
import type { RemovalMask, RemovalRegion } from '../../api/removal'
import type { VideoOcrCue } from '../../api/videoOcr'

const MASK_PADDING_PERCENT = 1

export function sameMediaPath(left: string, right: string): boolean {
  return left.replace(/\\/g, '/').toLocaleLowerCase() === right.replace(/\\/g, '/').toLocaleLowerCase()
}

function clampRegion(region: RemovalRegion): RemovalRegion {
  const width = Math.max(1, Math.min(100, Math.round(region.width)))
  const height = Math.max(1, Math.min(100, Math.round(region.height)))
  return {
    x: Math.max(0, Math.min(100 - width, Math.round(region.x))),
    y: Math.max(0, Math.min(100 - height, Math.round(region.y))),
    width,
    height,
  }
}

function cueRegion(cue: VideoOcrCue, source: EditorMedia, fallback: RemovalRegion): RemovalRegion {
  if (!cue.boxes.length || source.width <= 0 || source.height <= 0) return clampRegion(fallback)
  const left = Math.min(...cue.boxes.map((box) => box.x)) * 100 / source.width
  const top = Math.min(...cue.boxes.map((box) => box.y)) * 100 / source.height
  const right = Math.max(...cue.boxes.map((box) => box.x + box.width)) * 100 / source.width
  const bottom = Math.max(...cue.boxes.map((box) => box.y + box.height)) * 100 / source.height
  return clampRegion({
    x: Math.floor(left - MASK_PADDING_PERCENT),
    y: Math.floor(top - MASK_PADDING_PERCENT),
    width: Math.ceil(right + MASK_PADDING_PERCENT) - Math.floor(left - MASK_PADDING_PERCENT),
    height: Math.ceil(bottom + MASK_PADDING_PERCENT) - Math.floor(top - MASK_PADDING_PERCENT),
  })
}

function unionRegions(regions: RemovalRegion[]): RemovalRegion {
  const left = Math.min(...regions.map((region) => region.x))
  const top = Math.min(...regions.map((region) => region.y))
  const right = Math.max(...regions.map((region) => region.x + region.width))
  const bottom = Math.max(...regions.map((region) => region.y + region.height))
  return clampRegion({ x: left, y: top, width: right - left, height: bottom - top })
}

export function buildOcrRemovalMasks(
  cues: VideoOcrCue[],
  source: EditorMedia,
  fallback: RemovalRegion,
  maximumMasks = 12,
): RemovalMask[] {
  if (!cues.length || maximumMasks < 1) return []
  const ordered = [...cues].sort((left, right) => left.start_ms - right.start_ms || left.end_ms - right.end_ms)
  const batchSize = Math.max(1, Math.ceil(ordered.length / maximumMasks))
  const masks: RemovalMask[] = []
  for (let offset = 0; offset < ordered.length; offset += batchSize) {
    const batch = ordered.slice(offset, offset + batchSize)
    const first = batch[0]
    const last = batch.at(-1) ?? first
    masks.push({
      id: crypto.randomUUID(),
      name: `OCR ${masks.length + 1}`,
      region: unionRegions(batch.map((cue) => cueRegion(cue, source, fallback))),
      start_seconds: first.start_ms / 1_000,
      end_seconds: last.end_ms / 1_000,
    })
  }
  return masks
}

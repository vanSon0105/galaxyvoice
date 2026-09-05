import { z } from 'zod'

export const MEDIA_TICKS_PER_SECOND = 120_000

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(left)
  let b = Math.abs(right)
  while (b !== 0) {
    const remainder = a % b
    a = b
    b = remainder
  }
  return a || 1
}

export const MediaTimeSchema = z.number().int().safe().brand<'MediaTime'>()
export type MediaTime = z.infer<typeof MediaTimeSchema>

export const FrameRateSchema = z.object({
  numerator: z.number().int().positive().safe(),
  denominator: z.number().int().positive().safe(),
}).strict().refine(
  (value) => greatestCommonDivisor(value.numerator, value.denominator) === 1,
  'Frame rate must be a normalized rational value.',
)
export type FrameRate = z.infer<typeof FrameRateSchema>

export function mediaTime(ticks: number): MediaTime {
  const result = MediaTimeSchema.safeParse(ticks)
  if (!result.success) throw new RangeError('Media time must be a safe integer tick count.')
  return result.data
}

export function frameRate(numerator: number, denominator = 1): FrameRate {
  if (!Number.isSafeInteger(numerator) || numerator <= 0) {
    throw new RangeError('Frame-rate numerator must be a positive integer.')
  }
  if (!Number.isSafeInteger(denominator) || denominator <= 0) {
    throw new RangeError('Frame-rate denominator must be a positive integer.')
  }
  const divisor = greatestCommonDivisor(numerator, denominator)
  return FrameRateSchema.parse({ numerator: numerator / divisor, denominator: denominator / divisor })
}

const COMMON_FRAME_RATES = [
  frameRate(24_000, 1_001),
  frameRate(24),
  frameRate(25),
  frameRate(30_000, 1_001),
  frameRate(30),
  frameRate(48),
  frameRate(50),
  frameRate(60_000, 1_001),
  frameRate(60),
]

export function frameRateFromNumber(value: number): FrameRate {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError('Frame rate must be positive.')
  }
  const common = COMMON_FRAME_RATES.find(
    (candidate) => Math.abs(candidate.numerator / candidate.denominator - value) < 0.001,
  )
  if (common) return common
  return frameRate(Math.round(value * 1_000_000), 1_000_000)
}

export function millisecondsToMediaTime(milliseconds: number): MediaTime {
  if (!Number.isFinite(milliseconds)) {
    throw new RangeError('Milliseconds must be finite.')
  }
  return mediaTime(Math.round(milliseconds * MEDIA_TICKS_PER_SECOND / 1_000))
}

export function secondsToMediaTime(seconds: number): MediaTime {
  if (!Number.isFinite(seconds)) {
    throw new RangeError('Seconds must be finite.')
  }
  return mediaTime(Math.round(seconds * MEDIA_TICKS_PER_SECOND))
}

export function mediaTimeToMilliseconds(value: MediaTime): number {
  return value * 1_000 / MEDIA_TICKS_PER_SECOND
}

export function mediaTimeToSeconds(value: MediaTime): number {
  return value / MEDIA_TICKS_PER_SECOND
}

export function frameDuration(rate: FrameRate): MediaTime {
  const normalized = frameRate(rate.numerator, rate.denominator)
  return mediaTime(Math.round(MEDIA_TICKS_PER_SECOND * normalized.denominator / normalized.numerator))
}

export function snapToFrame(
  value: MediaTime,
  rate: FrameRate,
  mode: 'nearest' | 'floor' | 'ceil' = 'nearest',
): MediaTime {
  const normalized = frameRate(rate.numerator, rate.denominator)
  const framePosition = value * normalized.numerator
    / (MEDIA_TICKS_PER_SECOND * normalized.denominator)
  const frameIndex = mode === 'floor'
    ? Math.floor(framePosition)
    : mode === 'ceil'
      ? Math.ceil(framePosition)
      : Math.round(framePosition)
  return mediaTime(Math.round(
    frameIndex * MEDIA_TICKS_PER_SECOND * normalized.denominator / normalized.numerator,
  ))
}

export function addMediaTime(left: MediaTime, right: MediaTime): MediaTime {
  return mediaTime(left + right)
}

export function subtractMediaTime(left: MediaTime, right: MediaTime): MediaTime {
  return mediaTime(left - right)
}

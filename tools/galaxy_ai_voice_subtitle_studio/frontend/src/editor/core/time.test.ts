import { describe, expect, it } from 'vitest'

import {
  frameDuration,
  frameRate,
  frameRateFromNumber,
  mediaTime,
  mediaTimeToMilliseconds,
  millisecondsToMediaTime,
  snapToFrame,
} from './time'

describe('editor media time', () => {
  it('represents standard fractional frame rates with an exact integer frame duration', () => {
    const rate = frameRate(24_000, 1_001)

    expect(frameDuration(rate)).toBe(5_005)
    expect(snapToFrame(mediaTime(5_005 * 10_000 + 2_000), rate)).toBe(5_005 * 10_000)
  })

  it('recognizes decimal NTSC rates instead of storing a rounded float', () => {
    expect(frameRateFromNumber(29.97)).toEqual({ numerator: 30_000, denominator: 1_001 })
    expect(frameRateFromNumber(59.94)).toEqual({ numerator: 60_000, denominator: 1_001 })
  })

  it('bridges legacy millisecond timing without cumulative drift', () => {
    const value = millisecondsToMediaTime(3_723_250)

    expect(mediaTimeToMilliseconds(value)).toBe(3_723_250)
  })
})

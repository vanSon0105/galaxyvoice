import { describe, expect, it } from 'vitest'

import pageSource from './SeparationPage.tsx?raw'

describe('Separation model manager', () => {
  it('exposes the downloadable model catalog and model refresh flow', () => {
    expect(pageSource).toContain('Kho model')
    expect(pageSource).toContain('fetchAudioModelCatalog')
    expect(pageSource).toContain('startAudioModelDownload')
  })
})

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as settingsApi from '../api/settings'
import type { AppSettings, SettingsMeta } from '../api/settings'
import { SettingsPage } from './SettingsPage'


const EMPTY_META: SettingsMeta = {
  tts_engines: [],
  default_tts_engine: '',
  whisper_models: [],
  translation_providers: [],
  default_translation_provider: '',
  source_languages: [],
  target_languages: [],
  processing_devices: [],
  audio_methods: [],
  audio_devices: [],
  audio_formats: [],
  removal_modes: [],
  editor_resolutions: [],
  editor_fps: [],
  editor_encoders: [],
  editor_audio_modes: [],
  omnivoice_devices: [],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SettingsPage', () => {
  it('keeps the latest draft when save responses arrive out of order', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/old' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(EMPTY_META)
    const first = deferred<AppSettings>()
    const second = deferred<AppSettings>()
    const update = vi
      .spyOn(settingsApi, 'updateSettings')
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <SettingsPage />
      </QueryClientProvider>,
    )

    await screen.findByDisplayValue('D:/old')
    const input = document.querySelector<HTMLInputElement>('#setting-output_dir')
    expect(input).not.toBeNull()
    if (input === null) throw new Error('Missing output directory input')
    fireEvent.change(input, { target: { value: 'D:/first' } })
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1), { timeout: 1000 })
    fireEvent.change(input, { target: { value: 'D:/latest' } })
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2), { timeout: 1000 })

    await act(async () => {
      second.resolve({ output_dir: 'D:/latest' })
      first.resolve({ output_dir: 'D:/first' })
      await Promise.all([first.promise, second.promise])
    })

    expect(input).toHaveValue('D:/latest')
  })
})

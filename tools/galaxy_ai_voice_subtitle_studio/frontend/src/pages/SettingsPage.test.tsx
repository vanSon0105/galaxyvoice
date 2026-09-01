import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as extensionsApi from '../api/extensions'
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

function renderSettings(queryClient: QueryClient) {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <SettingsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  vi.spyOn(extensionsApi, 'fetchExtensionCapabilities').mockResolvedValue({ capabilities: [] })
})

describe('SettingsPage', () => {
  it('loads the extension catalogue while editable settings are pending', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockImplementation(() => new Promise(() => undefined))
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockImplementation(() => new Promise(() => undefined))
    vi.mocked(extensionsApi.fetchExtensionCapabilities).mockResolvedValue({
      capabilities: [{
        capability_id: 'dictation.live', label: 'Live dictation', category: 'voice_input',
        disposition: 'extension', summary: 'Microphone transcription.', boundary: 'Use Transcript ASR.',
        constraints: [], revisit_triggers: [], extension_capability_ids: ['asr.faster-whisper'],
        default_enabled: false,
      }],
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderSettings(queryClient)

    expect(await screen.findByText('Live dictation')).toBeInTheDocument()
    expect(screen.getByText('Microphone transcription.')).toBeInTheDocument()
  })

  it('keeps the extension catalogue visible when editable settings fail', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockRejectedValue(new Error('settings unavailable'))
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(EMPTY_META)
    vi.mocked(extensionsApi.fetchExtensionCapabilities).mockResolvedValue({
      capabilities: [{
        capability_id: 'backend.remote', label: 'Remote backend', category: 'deployment',
        disposition: 'deferred', summary: 'Remote service.', boundary: 'Keep loopback.',
        constraints: [], revisit_triggers: [], extension_capability_ids: [], default_enabled: false,
      }],
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderSettings(queryClient)

    expect(await screen.findByText('Remote backend')).toBeInTheDocument()
    expect(screen.getByText('Remote service.')).toBeInTheDocument()
  })

  it('keeps editable settings usable when the extension catalogue fails', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/ready' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(EMPTY_META)
    vi.mocked(extensionsApi.fetchExtensionCapabilities).mockRejectedValue(
      new Error('catalogue unavailable'),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderSettings(queryClient)

    const input = await screen.findByDisplayValue('D:/ready')
    expect(input).toBeEnabled()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Không thể tải danh mục tính năng mở rộng',
    )
  })

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

    renderSettings(queryClient)

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

  it('offers parity validation as one Settings-owned navigation command', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({ output_dir: 'D:/ready' })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(EMPTY_META)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderSettings(queryClient)

    const link = await screen.findByRole('link', { name: 'Mở đối chiếu parity' })
    expect(link).toHaveAttribute('href', '/settings/parity')
  })
})

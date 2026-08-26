/** Native file/folder dialogs via the pywebview js_api bridge (no-op in a
 *  plain browser — callers fall back to manual path entry). */
interface PywebviewApi {
  choose_video_file?: () => Promise<string[] | string | null>
  choose_srt_file?: () => Promise<string[] | string | null>
  choose_audio_file?: () => Promise<string[] | string | null>
  choose_media_file?: () => Promise<string[] | string | null>
  choose_book_file?: () => Promise<string[] | string | null>
  choose_voice_bundle_file?: () => Promise<string[] | string | null>
  choose_folder?: () => Promise<string[] | string | null>
  [key: string]: unknown
}

interface PywebviewWindow extends Window {
  pywebview?: { api?: PywebviewApi }
}

function firstOf(result: string[] | string | null | undefined): string | null {
  if (Array.isArray(result)) return result[0] ?? null
  return result ?? null
}

async function call(name: keyof PywebviewApi): Promise<string | null> {
  const api = (window as PywebviewWindow).pywebview?.api
  const fn = api?.[name]
  if (typeof fn !== 'function') return null
  try {
    return firstOf(await fn())
  } catch {
    return null
  }
}

export function pickVideoFile(): Promise<string | null> {
  return call('choose_video_file')
}

export function pickSrtFile(): Promise<string | null> {
  return call('choose_srt_file')
}

export function pickAudioFile(): Promise<string | null> {
  return call('choose_audio_file')
}

export function pickMediaFile(): Promise<string | null> {
  return call('choose_media_file')
}

export function pickBookFile(): Promise<string | null> {
  return call('choose_book_file')
}

export function pickVoiceBundleFile(): Promise<string | null> {
  return call('choose_voice_bundle_file')
}

export function pickFolder(): Promise<string | null> {
  return call('choose_folder')
}

export function hasNativeDialogs(): boolean {
  const api = (window as PywebviewWindow).pywebview?.api
  return Boolean(api && typeof api.choose_folder === 'function')
}

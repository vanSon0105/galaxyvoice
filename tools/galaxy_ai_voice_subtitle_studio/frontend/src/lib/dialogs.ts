/** Native file/folder dialogs via pywebview (no-op in a plain browser). */
interface PywebviewApi {
  create_file_dialog?: (mode: unknown) => Promise<string[] | string | null>
  [key: string]: unknown
}

interface PywebviewWindow extends Window {
  pywebview?: {
    api?: PywebviewApi
    FileDialog?: { OPEN: unknown; FOLDER_DIALOG: unknown }
  }
}

function dialog(mode: 'OPEN' | 'FOLDER_DIALOG'): Promise<string | null> {
  const w = window as PywebviewWindow
  const api = w.pywebview?.api
  if (!api?.create_file_dialog) return Promise.resolve(null)
  const modeValue = w.pywebview?.FileDialog?.[mode]
  return api
    .create_file_dialog(modeValue)
    .then((result) => (Array.isArray(result) ? (result[0] ?? null) : result))
    .catch(() => null)
}

export function pickFile(): Promise<string | null> {
  return dialog('OPEN')
}

export function pickFolder(): Promise<string | null> {
  return dialog('FOLDER_DIALOG')
}

export function hasNativeDialogs(): boolean {
  const w = window as PywebviewWindow
  return Boolean(w.pywebview?.api?.create_file_dialog)
}

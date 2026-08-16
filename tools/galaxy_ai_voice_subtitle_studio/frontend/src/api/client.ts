/** Fetch wrapper with retry/backoff + jitter. 4xx never retries; 5xx and
 *  network errors retry up to `retries` times with exponential backoff. */
export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

const DEFAULT_RETRIES = 3
const BASE_BACKOFF_MS = 400

function backoffDelay(attempt: number): number {
  return BASE_BACKOFF_MS * 2 ** attempt + Math.random() * 200
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  options: { retries?: number } = {},
): Promise<Response> {
  const retries = options.retries ?? DEFAULT_RETRIES
  let lastError: unknown
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(path, init)
      if (response.status >= 500 && attempt < retries) {
        lastError = new ApiError(`Máy chủ lỗi ${response.status}`, response.status)
        await sleep(backoffDelay(attempt))
        continue
      }
      return response
    } catch (error) {
      lastError = error
      if (attempt < retries) {
        await sleep(backoffDelay(attempt))
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init)
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

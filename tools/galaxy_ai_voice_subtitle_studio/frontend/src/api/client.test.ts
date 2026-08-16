import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, apiJson } from './client'

const originalFetch = globalThis.fetch

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('apiFetch', () => {
  it('returns the response on success without retrying', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    globalThis.fetch = fetchMock
    const response = await apiFetch('/api/test')
    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries 5xx responses with backoff then succeeds', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(503, {}))
      .mockResolvedValueOnce(jsonResponse(500, {}))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    globalThis.fetch = fetchMock
    const response = await apiFetch('/api/test', {}, { retries: 3 })
    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not retry 4xx responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'missing' }))
    globalThis.fetch = fetchMock
    const response = await apiFetch('/api/test')
    expect(response.status).toBe(404)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries network errors', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    globalThis.fetch = fetchMock
    const response = await apiFetch('/api/test', {}, { retries: 1 })
    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('apiJson', () => {
  it('throws ApiError with the server detail on failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse(422, { detail: 'Sai dữ liệu' }))
    await expect(apiJson('/api/settings', { method: 'PUT' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: 'Sai dữ liệu',
    })
  })

  it('throws ApiError with a generic message for non-JSON bodies', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(new Response('boom', { status: 500 }))
    await expect(apiJson('/api/settings')).rejects.toBeInstanceOf(ApiError)
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  acceptParityRun,
  cancelParityTask,
  downloadParityReport,
  recordParityManualAnswer,
  startParityRun,
} from './parity'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('parity API', () => {
  it('sends typed run and manual evidence payloads to the parity boundary', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'task-1', run_id: 'run-1' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ready_for_acceptance: true })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ready_for_acceptance: false })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
    vi.stubGlobal('fetch', fetchMock)

    await startParityRun({ manifest_path: 'D:/fixtures/manifest.json', approved_roots: ['D:/fixtures'] })
    await recordParityManualAnswer('run/1', 'case/1', { accepted: false, note: 'Nghe thấy lỗi.' })
    await acceptParityRun('run/1', { note: 'Đã kiểm tra đầy đủ.' })
    await cancelParityTask('task/1')

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/parity/runs', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ manifest_path: 'D:/fixtures/manifest.json', approved_roots: ['D:/fixtures'] }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/parity/runs/run%2F1/manual-items/case%2F1',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ accepted: false, note: 'Nghe thấy lỗi.' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/parity/runs/run%2F1/accept',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/tasks/task%2F1/cancel',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('keeps report responses outside the JSON parser', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('# Parity', { headers: { 'Content-Type': 'text/markdown' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const report = await downloadParityReport('run 1', 'markdown')

    expect(await report.text()).toBe('# Parity')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/parity/runs/run%201/report?format=markdown',
      {},
    )
  })
})

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as parityApi from '../api/parity'
import type {
  CatalogueResponse,
  CorpusInspection,
  MigrationInspection,
  ParityRun,
  ParityRunSummary,
} from '../api/parity'
import { ParityPage } from './ParityPage'

const catalogue: CatalogueResponse = {
  version: '2026-08-30',
  cases: [{
    case_id: 'shared.project_portability',
    area: 'shared',
    title: 'Project portability',
    required: true,
    fixture_roles: ['portable_project'],
    checks: ['project_reopen', 'manual_review'],
    manual_prompts: ['Nghe và xác nhận bản xuất.'],
    thresholds: { duration_absolute_ms: 250 },
  }],
}

const blockedRun: ParityRun = {
  run_id: 'run-1',
  task_id: 'task-1',
  status: 'completed',
  ready_for_acceptance: false,
  catalogue_version: '2026-08-30',
  catalogue_hash: 'c'.repeat(64),
  manifest_path: 'D:/fixtures/manifest.json',
  manifest_hash: 'd'.repeat(64),
  manifest_snapshot_path: 'inputs/manifest.json',
  app_version: '15.0',
  created_at: '2026-08-30T00:00:00Z',
  completed_at: '2026-08-30T00:01:00Z',
  report_json_path: 'reports/run-1/report.json',
  report_markdown_path: 'reports/run-1/report.md',
  required_case_ids: ['shared.project_portability'],
  manual_items: [{
    item_id: 'shared.project_portability.manual.1',
    case_id: 'shared.project_portability',
    prompt: 'Nghe và xác nhận bản xuất.',
    required: true,
  }],
  thresholds: { 'shared.project_portability': { duration_absolute_ms: 250 } },
  threshold_overrides: [],
  source_fingerprints: {},
  reference_fingerprints: {},
  case_results: [{
    case_id: 'shared.project_portability',
    status: 'blocked',
    checks: [
      {
        check_id: 'project_reopen',
        status: 'blocked',
        message: 'Thiếu project fixture.',
        measurements: { duration_ms: 0 },
      },
      {
        check_id: 'manual_review',
        status: 'manual_pending',
        message: 'Cần người dùng nghe.',
        measurements: {},
      },
    ],
  }],
  warnings: [],
  manual_answers: {},
  acceptance: null,
}

const summary: ParityRunSummary = {
  run_id: 'run-1',
  task_id: 'task-1',
  status: 'completed',
  catalogue_version: '2026-08-30',
  app_version: '15.0',
  created_at: '2026-08-30T00:00:00Z',
  completed_at: '2026-08-30T00:01:00Z',
  accepted: false,
}

const corpus: CorpusInspection = {
  manifest: {
    schema_version: 1,
    corpus_id: 'phase-15',
    created_at: '2026-08-30T00:00:00Z',
    cases: [{
      case_id: 'shared.project_portability',
      assets: [{
        role: 'portable_project',
        path: 'portable.json',
        sha256: 'a'.repeat(64),
        byte_size: 12,
        media: null,
      }],
    }],
  },
  assets_by_role: {
    portable_project: {
      role: 'portable_project',
      path: 'D:/fixtures/portable.json',
      status: 'ready',
      findings: [{ code: 'ready', message: 'Fixture sẵn sàng.' }],
      media: null,
    },
    missing_audio: {
      role: 'missing_audio',
      path: null,
      status: 'missing',
      findings: [{ code: 'missing', message: 'Thiếu audio.' }],
      media: null,
    },
  },
  roles_by_case: { 'shared.project_portability': ['portable_project', 'missing_audio'] },
}

const fingerprint = {
  kind: 'file' as const,
  sha256: 'b'.repeat(64),
  byte_size: 42,
  entry_count: 1,
}

const candidate = {
  source_id: 'voice-1',
  target: 'voice_profile',
  data: { name: 'Narrator' },
  assets: [{
    role: 'reference_audio',
    hint: 'voice.wav',
    state: 'missing' as const,
    expected_sha256: '',
    byte_size: 0,
  }],
  warnings: ['Cần xác nhận consent.'],
  consent: {
    confirmed: false,
    basis: '',
    statement: '',
    recorded_at: '',
    provenance: '',
  },
}

const migration: MigrationInspection = {
  source_before: fingerprint,
  source_after: fingerprint,
  voice_profiles: [candidate],
  persona_bundles: [],
  generation_history: [],
  dub_history: [],
  studio_projects: [],
  export_history: [],
  glossary_terms: [],
  pronunciation_entries: [],
  discovered_documents: [],
  assets: candidate.assets,
  unsupported: [{ source: 'settings', reason: 'Không di chuyển credential.' }],
  warnings: ['Dry-run only.'],
}

function renderPage(
  run: ParityRun = blockedRun,
  getRun: (runId: string) => Promise<ParityRun> = async () => run,
) {
  vi.mocked(parityApi.getParityRun).mockImplementation(getRun)
  vi.mocked(parityApi.listParityRuns).mockResolvedValue({
    runs: [{ ...summary, run_id: run.run_id, task_id: run.task_id, status: run.status }],
  })
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ParityPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.spyOn(parityApi, 'fetchParityCatalogue').mockResolvedValue(catalogue)
  vi.spyOn(parityApi, 'listParityRuns').mockResolvedValue({ runs: [summary] })
  vi.spyOn(parityApi, 'getParityRun').mockResolvedValue(blockedRun)
  vi.spyOn(parityApi, 'inspectParityCorpus').mockResolvedValue(corpus)
  vi.spyOn(parityApi, 'inspectParityMigration').mockResolvedValue(migration)
  vi.spyOn(parityApi, 'startParityRun').mockResolvedValue({ task_id: 'task-2', run_id: 'run-2' })
  vi.spyOn(parityApi, 'cancelParityTask').mockResolvedValue({ ok: true })
  vi.spyOn(parityApi, 'downloadParityReport').mockResolvedValue(new Blob(['{}']))
  vi.spyOn(parityApi, 'recordParityManualAnswer').mockResolvedValue(blockedRun)
  vi.spyOn(parityApi, 'acceptParityRun').mockResolvedValue(blockedRun)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ParityPage', () => {
  it('keeps blocked and manual-pending results visibly non-successful', async () => {
    renderPage()

    expect((await screen.findAllByText('Bị chặn')).length).toBeGreaterThan(0)
    expect(screen.getByText('Chờ đánh giá')).toHaveClass('manual_pending')
    expect(screen.getByRole('button', { name: 'Chấp nhận kết quả' })).toBeDisabled()
  })

  it('shows corpus readiness and migration grouped totals from inspection responses', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Manifest corpus'), {
      target: { value: 'D:/fixtures/manifest.json' },
    })
    fireEvent.change(screen.getByLabelText('Thư mục được phép'), {
      target: { value: 'D:/fixtures' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra corpus' }))

    expect(await screen.findByText('1 sẵn sàng')).toBeVisible()
    expect(screen.getByText('1 thiếu')).toBeVisible()
    expect(screen.getByText('D:/fixtures')).toBeVisible()

    fireEvent.change(screen.getByLabelText('Nguồn VoiceStudio đã sao chép'), {
      target: { value: 'D:/copied-voice' },
    })
    fireEvent.click(screen.getByLabelText('Tôi xác nhận đây là bản sao chỉ đọc'))
    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra migration' }))

    expect(await screen.findByText('1 có thể nhập')).toBeVisible()
    expect(screen.getByText('1 cần liên kết lại')).toBeVisible()
    expect(screen.getByText('1 không hỗ trợ')).toBeVisible()
    expect(screen.getByText('2 cảnh báo')).toBeVisible()
  })

  it('uses a keyboard-focusable native disclosure for each case', async () => {
    renderPage()

    const title = await screen.findByText('Project portability')
    const disclosure = title.closest('summary')
    expect(disclosure).not.toBeNull()
    disclosure?.focus()
    expect(disclosure).toHaveFocus()
    expect(disclosure?.parentElement).not.toHaveAttribute('open')
    if (disclosure) fireEvent.click(disclosure)
    expect(disclosure?.parentElement).toHaveAttribute('open')
    expect(screen.getByText('duration_ms')).toBeVisible()
  })

  it.each([
    ['Đạt', true, 'Đã ghi nhận: Đạt'],
    ['Không đạt', false, 'Đã ghi nhận: Không đạt'],
  ] as const)('records a %s manual answer with its note', async (label, accepted, resultText) => {
    const answeredRun: ParityRun = {
      ...blockedRun,
      ready_for_acceptance: accepted,
      manual_answers: {
        'shared.project_portability.manual.1': {
          item_id: 'shared.project_portability.manual.1',
          accepted,
          note: 'Đã nghe kỹ.',
          answered_at: '2026-08-30T00:02:00Z',
        },
      },
    }
    vi.mocked(parityApi.recordParityManualAnswer).mockResolvedValue(answeredRun)
    renderPage()

    const manual = await screen.findByRole('group', { name: 'Nghe và xác nhận bản xuất.' })
    fireEvent.change(within(manual).getByLabelText('Ghi chú'), {
      target: { value: 'Đã nghe kỹ.' },
    })
    fireEvent.click(within(manual).getByRole('button', { name: label }))

    await waitFor(() => expect(parityApi.recordParityManualAnswer).toHaveBeenCalledWith(
      'run-1',
      'shared.project_portability.manual.1',
      { accepted, note: 'Đã nghe kỹ.' },
    ))
    expect(await screen.findByText(resultText)).toBeVisible()
  })

  it('enables final acceptance only when the refreshed backend response is ready', async () => {
    renderPage({
      ...blockedRun,
      case_results: [{
        case_id: 'shared.project_portability',
        status: 'pass',
        checks: [{ check_id: 'project_reopen', status: 'pass', message: 'ok', measurements: {} }],
      }],
    })
    const note = await screen.findByLabelText('Ghi chú chấp nhận cuối cùng')
    fireEvent.change(note, { target: { value: 'Đã xem toàn bộ bằng chứng.' } })
    expect(screen.getByRole('button', { name: 'Chấp nhận kết quả' })).toBeDisabled()

    cleanup()
    renderPage({ ...blockedRun, ready_for_acceptance: true })
    fireEvent.change(await screen.findByLabelText('Ghi chú chấp nhận cuối cùng'), {
      target: { value: 'Đã xem toàn bộ bằng chứng.' },
    })
    expect(screen.getByRole('button', { name: 'Chấp nhận kết quả' })).toBeEnabled()
  })

  it('starts, cancels, and refreshes runs with the selected source', async () => {
    const runningRun: ParityRun = {
      ...blockedRun,
      run_id: 'run-2',
      task_id: 'task-2',
      status: 'running',
      completed_at: null,
      case_results: [],
      manual_items: [],
    }
    renderPage(blockedRun, async (runId) => (runId === 'run-2' ? runningRun : blockedRun))
    fireEvent.change(screen.getByLabelText('Manifest corpus'), {
      target: { value: 'D:/fixtures/manifest.json' },
    })
    fireEvent.change(screen.getByLabelText('Thư mục được phép'), {
      target: { value: 'D:/fixtures' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Chạy đối chiếu' }))

    await waitFor(() => expect(parityApi.startParityRun).toHaveBeenCalledWith({
      manifest_path: 'D:/fixtures/manifest.json',
      approved_roots: ['D:/fixtures'],
    }))
    expect(await screen.findByText('Đang chạy')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Hủy lần chạy' }))
    await waitFor(() => expect(parityApi.cancelParityTask).toHaveBeenCalledWith('task-2'))

    const callsBeforeRefresh = vi.mocked(parityApi.listParityRuns).mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Làm mới' }))
    await waitFor(() => {
      expect(vi.mocked(parityApi.listParityRuns).mock.calls.length).toBeGreaterThan(callsBeforeRefresh)
    })
  })

  it('keeps an optional report error isolated from the visible run', async () => {
    vi.mocked(parityApi.downloadParityReport).mockRejectedValue(new Error('report unavailable'))
    renderPage()

    expect(await screen.findByText('Project portability')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Tải báo cáo Markdown' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được báo cáo')
    expect(screen.getByText('Project portability')).toBeVisible()
  })

  it('keeps run evidence usable when the catalogue query fails', async () => {
    vi.mocked(parityApi.fetchParityCatalogue).mockRejectedValue(new Error('catalogue unavailable'))
    renderPage()

    expect(await screen.findByText('shared.project_portability')).toBeVisible()
    expect(screen.getByText('Không tải được danh mục case.')).toHaveAttribute('role', 'alert')
    expect(screen.getByRole('button', { name: 'Tải báo cáo JSON' })).toBeEnabled()
  })
})

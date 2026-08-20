import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  fetchVoiceStudioStatus,
  installVoiceStudio,
  launchVoiceStudio,
  stopVoiceStudio,
} from '../../api/voiceStudio'
import { TaskButton } from '../../components/TaskButton'
import type { TaskState } from '../../ws/useTasks'

type PageState = 'checking' | 'not-installed' | 'launching' | 'ready' | 'error'

export function VoiceStudioPage() {
  const queryClient = useQueryClient()
  const launchAttempted = useRef(false)
  const [pageState, setPageState] = useState<PageState>('checking')
  const [iframeSrc, setIframeSrc] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const statusQuery = useQuery({
    queryKey: ['voicestudio-status'],
    queryFn: fetchVoiceStudioStatus,
    refetchInterval: iframeSrc ? 10_000 : false,
  })
  const status = statusQuery.data

  const startBackend = useCallback(async () => {
    setPageState('launching')
    setErrorMessage('')
    try {
      const response = await launchVoiceStudio()
      setIframeSrc(response.url)
      setPageState('ready')
    } catch (cause) {
      setPageState('error')
      setErrorMessage(cause instanceof Error ? cause.message : String(cause))
    }
  }, [])

  useEffect(() => {
    if (statusQuery.isPending) return
    if (statusQuery.isError || !status) {
      setPageState('error')
      setErrorMessage('Không tải được trạng thái VoiceStudio')
      return
    }
    if (!status.installed) {
      launchAttempted.current = false
      setIframeSrc('')
      setPageState('not-installed')
      return
    }
    if (!launchAttempted.current && !iframeSrc) {
      launchAttempted.current = true
      void startBackend()
    }
  }, [iframeSrc, startBackend, status, statusQuery.isError, statusQuery.isPending])

  const handleInstallStart = async (): Promise<string> => {
    setErrorMessage('')
    const response = await installVoiceStudio({})
    return response.task_id
  }

  const handleInstallFinish = (task: TaskState) => {
    if (task.status !== 'done') {
      setPageState('error')
      setErrorMessage(task.error ?? 'Cài đặt VoiceStudio thất bại')
      return
    }
    launchAttempted.current = false
    setPageState('checking')
    void queryClient.invalidateQueries({ queryKey: ['voicestudio-status'] })
  }

  const handleRetry = () => {
    launchAttempted.current = false
    setErrorMessage('')
    setPageState('checking')
    void queryClient.invalidateQueries({ queryKey: ['voicestudio-status'] })
  }

  const handleStop = async () => {
    try {
      await stopVoiceStudio()
      launchAttempted.current = true
      setIframeSrc('')
      setPageState('ready')
      await queryClient.invalidateQueries({ queryKey: ['voicestudio-status'] })
    } catch (cause) {
      setPageState('error')
      setErrorMessage(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <section className="section-card voicestudio-page">
      <div className="section-header">
        <div>
          <h2 className="section-title">VoiceStudio</h2>
          <p className="section-subtitle">{status?.message ?? 'Đang kiểm tra runtime local...'}</p>
        </div>
        <div className="toolbar-row">
          {iframeSrc && (
            <button className="btn" onClick={() => void handleStop()}>
              Dừng
            </button>
          )}
          {pageState === 'ready' && !iframeSrc && (
            <button
              className="btn accent"
              onClick={() => {
                launchAttempted.current = true
                void startBackend()
              }}
            >
              Khởi động lại
            </button>
          )}
        </div>
      </div>

      {pageState === 'ready' && iframeSrc ? (
        <iframe
          className="voicestudio-frame"
          src={iframeSrc}
          allow="clipboard-read; clipboard-write"
          title="VoiceStudio"
        />
      ) : (
        <div className="empty-state voicestudio-state">
          {pageState === 'checking' && <p>Đang kiểm tra VoiceStudio...</p>}
          {pageState === 'launching' && <p>Đang khởi động VoiceStudio...</p>}
          {pageState === 'ready' && <p>VoiceStudio đã dừng.</p>}
          {pageState === 'not-installed' && (
            <>
              <h3>Chưa có runtime VoiceStudio</h3>
              <p>
                Snapshot đã đi kèm Galaxy. Bước cài đặt chỉ chuẩn bị Python và dependency
                trong thư mục local của ứng dụng.
              </p>
              <TaskButton
                label={status?.update_required ? 'Cập nhật runtime' : 'Cài runtime local'}
                variant="accent"
                onStart={handleInstallStart}
                onFinish={handleInstallFinish}
              />
            </>
          )}
          {pageState === 'error' && (
            <>
              <h3>Không thể mở VoiceStudio</h3>
              <p className="error-text">{errorMessage}</p>
              <button className="btn accent" onClick={handleRetry}>
                Thử lại
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}

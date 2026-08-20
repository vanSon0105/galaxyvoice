import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  fetchVoiceStudioStatus,
  launchVoiceStudio,
  installVoiceStudio,
  stopVoiceStudio,
} from '../../api/voiceStudio'
import type { VoiceStudioStatus } from '../../api/voiceStudio'
import { TaskButton } from '../../components/TaskButton'

type State = 'checking' | 'not_installed' | 'installing' | 'ready' | 'error'

/** VoiceStudio iframe page: install → launch → embed. */
export function VoiceStudioPage() {
  const queryClient = useQueryClient()
  const [state, setState] = useState<State>('checking')
  const [iframeSrc, setIframeSrc] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  const statusQuery = useQuery({
    queryKey: ['voicestudio-status'],
    queryFn: fetchVoiceStudioStatus,
    refetchInterval: state === 'ready' ? 10000 : false,
  })

  const status: VoiceStudioStatus | undefined = statusQuery.data

  // State machine
  useEffect(() => {
    if (statusQuery.isPending) return
    if (!status) {
      setState('error')
      setErrorMsg('Không tải được trạng thái VoiceStudio')
      return
    }
    if (!status.installed) {
      setState('not_installed')
      return
    }
    if (status.backend_online) {
      setState('ready')
      setIframeSrc(status.backend_url ?? 'http://127.0.0.1:3900')
      return
    }
    // Installed but not running
    setState('ready')
  }, [status, statusQuery.isPending])

  const handleInstall = async (): Promise<string> => {
    setState('installing')
    setErrorMsg('')
    const response = await installVoiceStudio({})
    return response.task_id
  }

  const handleInstallDone = (task: { status: string; result?: unknown; error?: string }) => {
    if (task.status !== 'done') {
      setState('error')
      setErrorMsg(task.error ?? 'Cài đặt thất bại')
      return
    }
    void queryClient.invalidateQueries({ queryKey: ['voicestudio-status'] })
    setState('ready')
  }

  const handleLaunch = async () => {
    setErrorMsg('')
    try {
      const response = await launchVoiceStudio()
      setIframeSrc(response.url)
      setState('ready')
    } catch (cause) {
      setErrorMsg(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const handleStop = async () => {
    try {
      await stopVoiceStudio()
      setIframeSrc('')
      setState('ready')
    } catch (cause) {
      setErrorMsg(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const renderInstalling = () => (
    <div className="section-card" style={{ textAlign: 'center', padding: 40 }}>
      <div style={{ fontSize: 18, marginBottom: 16 }}>Đang cài đặt VoiceStudio…</div>
      <TaskButton label="Đang cài…" variant="accent" onStart={handleInstall} onFinish={handleInstallDone} />
    </div>
  )

  const renderNotInstalled = () => (
    <div className="section-card" style={{ textAlign: 'center', padding: 40 }}>
      <div style={{ fontSize: 18, marginBottom: 16 }}>
        VoiceStudio chưa được cài đặt
      </div>
      <p style={{ color: 'var(--color-fg-subtle)', marginBottom: 24 }}>
        VoiceStudio là ứng dụng riêng (AGPL-3.0) chạy trong iframe.
        Bấm nút bên dưới để cài runtime local (Python + WebView2).
      </p>
      <TaskButton label="Cài runtime VoiceStudio" variant="accent" onStart={handleInstall} onFinish={handleInstallDone} />
    </div>
  )

  const renderReady = () => (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 280px)', minHeight: 400 }}>
      {iframeSrc && (
        <div style={{ flex: 1, position: 'relative' }}>
          <iframe
            src={iframeSrc}
            style={{ width: '100%', height: '100%', border: 'none', borderRadius: 6 }}
            allow="clipboard-read; clipboard-write"
            title="VoiceStudio"
          />
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, marginTop: 12, justifyContent: 'flex-end' }}>
        <button className="btn" onClick={handleStop} disabled={!iframeSrc}>
          Dừng backend
        </button>
        <button className="btn accent" onClick={handleLaunch} disabled={!!iframeSrc}>
          Mở / Kết nối lại
        </button>
      </div>
    </div>
  )

  const renderError = () => (
    <div className="section-card" style={{ borderColor: 'rgba(220,118,111,0.4)' }}>
      <div style={{ color: 'var(--color-danger)', fontSize: 14, marginBottom: 12 }}>
        Lỗi: {errorMsg}
      </div>
      <button className="btn" onClick={() => void queryClient.invalidateQueries({ queryKey: ['voicestudio-status'] })}>
        Thử lại
      </button>
    </div>
  )

  const renderChecking = () => (
    <div className="section-card" style={{ textAlign: 'center', padding: 40 }}>
      <div>Đang kiểm tra VoiceStudio…</div>
    </div>
  )

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">VoiceStudio</h2>
        <div style={{ color: 'var(--color-fg-subtle)', fontSize: 12, marginBottom: 16 }}>
          {status?.message ?? 'Đang tải…'}
        </div>
        {state === 'checking' && renderChecking()}
        {state === 'not_installed' && renderNotInstalled()}
        {state === 'installing' && renderInstalling()}
        {state === 'ready' && renderReady()}
        {state === 'error' && renderError()}
      </section>
    </div>
  )
}
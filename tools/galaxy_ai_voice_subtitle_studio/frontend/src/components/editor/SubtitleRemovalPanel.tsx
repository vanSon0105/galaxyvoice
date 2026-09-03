import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchRemovalMeta,
  fetchRemovalPreview,
  installProPainter,
  startSubtitleRemoval,
} from '../../api/removal'
import type { RemovalRegion, RemovalResult } from '../../api/removal'
import type { EditorMedia } from '../../api/editor'
import { fetchSettings, fetchSettingsMeta, updateSettings } from '../../api/settings'
import { openPath } from '../../api/voice'
import { TaskButton } from '../TaskButton'
import type { TaskState } from '../../ws/useTasks'

const DEFAULT_REMOVAL_REGION: RemovalRegion = { x: 5, y: 75, width: 90, height: 20 }

function numberSetting(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringSetting(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function clampRemovalRegion(region: RemovalRegion): RemovalRegion {
  const width = Math.max(1, Math.min(100, Math.round(region.width)))
  const height = Math.max(1, Math.min(100, Math.round(region.height)))
  return {
    x: Math.max(0, Math.min(100 - width, Math.round(region.x))),
    y: Math.max(0, Math.min(100 - height, Math.round(region.y))),
    width,
    height,
  }
}

interface SubtitleRemovalPanelProps {
  galaxyProjectId: string
  source: EditorMedia | null
  outputDir: string
  onCompleted: (result: RemovalResult) => Promise<void> | void
}

export function SubtitleRemovalPanel({
  galaxyProjectId,
  source,
  outputDir,
  onCompleted,
}: SubtitleRemovalPanelProps) {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const settingsMetaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const metaQuery = useQuery({ queryKey: ['removal-meta'], queryFn: fetchRemovalMeta })
  const videoRef = useRef<HTMLVideoElement>(null)
  const seeded = useRef(false)
  const dragRef = useRef<{
    type: 'move' | 'resize'
    startX: number
    startY: number
    region: RemovalRegion
  } | null>(null)

  const [mode, setMode] = useState('blur')
  const [region, setRegion] = useState<RemovalRegion>(DEFAULT_REMOVAL_REGION)
  const [blurStrength, setBlurStrength] = useState(18)
  const [device, setDevice] = useState('auto')
  const [licenseAccepted, setLicenseAccepted] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [snapshotUrl, setSnapshotUrl] = useState('')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<RemovalResult | null>(null)
  const sourcePath = source?.path ?? ''
  const sourceName = source?.name ?? ''

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings || seeded.current) return
    seeded.current = true
    setMode(stringSetting(settings.subtitle_removal_mode, 'blur'))
    setRegion(clampRemovalRegion({
      x: numberSetting(settings.subtitle_region_x, DEFAULT_REMOVAL_REGION.x),
      y: numberSetting(settings.subtitle_region_y, DEFAULT_REMOVAL_REGION.y),
      width: numberSetting(settings.subtitle_region_width, DEFAULT_REMOVAL_REGION.width),
      height: numberSetting(settings.subtitle_region_height, DEFAULT_REMOVAL_REGION.height),
    }))
    setBlurStrength(numberSetting(settings.subtitle_blur_strength, 18))
    setDevice(stringSetting(settings.removal_processing_device, 'auto'))
    setLicenseAccepted(settings.propainter_license_accepted === true)
  }, [settingsQuery.data])

  useEffect(() => {
    setProjectName(sourceName ? `${sourceName.replace(/\.[^.]+$/, '')}-clean` : '')
    setResult(null)
    setMessage('')
    setSnapshotUrl((current) => {
      if (current) URL.revokeObjectURL(current)
      return ''
    })
  }, [sourceName, sourcePath])

  useEffect(() => () => {
    if (snapshotUrl) URL.revokeObjectURL(snapshotUrl)
  }, [snapshotUrl])

  const selectedMode = useMemo(
    () => metaQuery.data?.modes.find((item) => item.code === mode),
    [metaQuery.data, mode],
  )
  const usesAi = selectedMode?.uses_ai ?? false
  const usesRegion = mode !== 'strip'

  const updateRegionField = (key: keyof RemovalRegion, value: number) => {
    setRegion((current) => clampRemovalRegion({ ...current, [key]: value }))
  }

  const beginDrag = (event: React.PointerEvent<HTMLDivElement>, type: 'move' | 'resize') => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { type, startX: event.clientX, startY: event.clientY, region }
  }

  const moveRegion = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const bounds = event.currentTarget.closest('.editor-removal-stage')?.getBoundingClientRect()
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
    const dx = ((event.clientX - drag.startX) / bounds.width) * 100
    const dy = ((event.clientY - drag.startY) / bounds.height) * 100
    setRegion(clampRemovalRegion(drag.type === 'move'
      ? { ...drag.region, x: drag.region.x + dx, y: drag.region.y + dy }
      : { ...drag.region, width: drag.region.width + dx, height: drag.region.height + dy }))
  }

  const createSnapshot = async () => {
    if (!source) return
    setMessage('Đang tạo ảnh xem trước...')
    try {
      const blob = await fetchRemovalPreview(source.path, videoRef.current?.currentTime ?? 0, region)
      const nextUrl = URL.createObjectURL(blob)
      setSnapshotUrl((current) => {
        if (current) URL.revokeObjectURL(current)
        return nextUrl
      })
      setMessage('Đã tạo ảnh xem trước.')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const start = async (): Promise<string> => {
    if (!source) throw new Error('Chọn một clip video trên timeline.')
    if (!outputDir.trim()) throw new Error('Chọn thư mục xuất trong phần Xuất video.')
    if (usesAi && !licenseAccepted) throw new Error('Cần xác nhận license phi thương mại của ProPainter.')
    if (usesAi && !metaQuery.data?.propainter_ready) throw new Error('ProPainter chưa được cài đầy đủ.')
    setResult(null)
    setMessage('Đã gửi tác vụ xóa phụ đề.')
    await updateSettings({
      subtitle_removal_mode: mode,
      subtitle_region_x: region.x,
      subtitle_region_y: region.y,
      subtitle_region_width: region.width,
      subtitle_region_height: region.height,
      subtitle_blur_strength: blurStrength,
      removal_processing_device: device,
      propainter_license_accepted: licenseAccepted,
    })
    const response = await startSubtitleRemoval({
      galaxy_project_id: galaxyProjectId,
      video_path: source.path,
      output_dir: outputDir,
      project_name: projectName,
      mode,
      region,
      blur_strength: blurStrength,
      processing_device: device,
      license_accepted: licenseAccepted,
    })
    return response.task_id
  }

  const finish = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      const completed = task.result as RemovalResult
      setResult(completed)
      setMessage('Đã thêm video sạch vào Tệp phương tiện.')
      void Promise.resolve(onCompleted(completed)).catch((cause) => {
        setMessage(cause instanceof Error ? cause.message : String(cause))
      })
    } else if (task.status === 'failed') {
      setMessage(task.error ?? 'Xóa phụ đề thất bại.')
    } else if (task.status === 'cancelled') {
      setMessage('Đã dừng tác vụ xóa phụ đề.')
    }
  }

  if (!source) {
    return <div className="editor-removal-empty">Chọn một clip video trên timeline</div>
  }

  return (
    <div className="editor-removal-tool">
      <div className="editor-removal-stage" style={{ aspectRatio: `${source.width || 16}/${source.height || 9}` }}>
        <video ref={videoRef} controls preload="metadata" src={source.url} />
        {usesRegion && (
          <div
            className="removal-region"
            style={{ left: `${region.x}%`, top: `${region.y}%`, width: `${region.width}%`, height: `${region.height}%` }}
            onPointerDown={(event) => beginDrag(event, 'move')}
            onPointerMove={moveRegion}
            onPointerUp={() => { dragRef.current = null }}
            onPointerCancel={() => { dragRef.current = null }}
          >
            <span>Vùng xóa</span>
            <div
              className="region-resize"
              onPointerDown={(event) => { event.stopPropagation(); beginDrag(event, 'resize') }}
              onPointerMove={moveRegion}
              onPointerUp={() => { dragRef.current = null }}
              onPointerCancel={() => { dragRef.current = null }}
            />
          </div>
        )}
      </div>

      <div className="editor-removal-source" title={source.path}>
        <strong>{source.name}</strong>
        <span>{source.width}×{source.height}</span>
      </div>

      <div className="field">
        <label htmlFor="editor-removal-mode">Chế độ</label>
        <select id="editor-removal-mode" value={mode} onChange={(event) => setMode(event.target.value)}>
          {(metaQuery.data?.modes ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
        </select>
      </div>

      {usesRegion && (
        <div className="field-grid editor-removal-region-fields">
          {(['x', 'y', 'width', 'height'] as const).map((key) => (
            <div className="field" key={key}>
              <label>{{ x: 'X (%)', y: 'Y (%)', width: 'Rộng (%)', height: 'Cao (%)' }[key]}</label>
              <input
                type="number"
                min={key === 'x' || key === 'y' ? 0 : 1}
                max="100"
                value={region[key]}
                onChange={(event) => updateRegionField(key, Number(event.target.value))}
              />
            </div>
          ))}
        </div>
      )}

      {mode === 'blur' && (
        <div className="field">
          <label>Độ mờ: {blurStrength}</label>
          <input type="range" min="1" max="100" value={blurStrength} onChange={(event) => setBlurStrength(Number(event.target.value))} />
        </div>
      )}

      {usesAi && (
        <>
          <div className="field">
            <label htmlFor="editor-removal-device">Thiết bị xử lý</label>
            <select id="editor-removal-device" value={device} onChange={(event) => setDevice(event.target.value)}>
              {(settingsMetaQuery.data?.processing_devices ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
            </select>
          </div>
          <div className="field-check license-check">
            <input id="editor-propainter-license" type="checkbox" checked={licenseAccepted} onChange={(event) => setLicenseAccepted(event.target.checked)} />
            <label htmlFor="editor-propainter-license">Chấp nhận license phi thương mại của ProPainter.</label>
          </div>
          {!metaQuery.data?.propainter_ready && (
            <TaskButton
              label="Cài ProPainter"
              disabled={!metaQuery.data?.installer_available}
              onStart={async () => (await installProPainter(device)).task_id}
              onFinish={(task) => {
                if (task.status !== 'done') return
                setMessage('ProPainter đã sẵn sàng.')
                void metaQuery.refetch()
              }}
            />
          )}
        </>
      )}

      <div className="editor-removal-actions">
        <button className="btn" onClick={() => void createSnapshot()}>Xem trước vùng</button>
        <TaskButton label="Xóa phụ đề" variant="accent" onStart={start} onFinish={finish} />
        {result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}
      </div>
      {message && <p className="action-message editor-removal-message">{message}</p>}
      {snapshotUrl && <img className="editor-removal-snapshot" src={snapshotUrl} alt="Vùng xóa trên frame hiện tại" />}
    </div>
  )
}

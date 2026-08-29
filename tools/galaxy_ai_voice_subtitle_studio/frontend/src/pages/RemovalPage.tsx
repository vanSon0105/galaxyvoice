import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchRemovalMeta,
  fetchRemovalPreview,
  installProPainter,
  registerRemovalSource,
  startSubtitleRemoval,
} from '../api/removal'
import type { RemovalRegion, RemovalResult } from '../api/removal'
import { fetchSettings, fetchSettingsMeta, updateSettings } from '../api/settings'
import { openPath } from '../api/voice'
import { TaskButton } from '../components/TaskButton'
import { useActiveProjectId } from '../hooks/useActiveProjectId'
import { hasNativeDialogs, pickFolder, pickVideoFile } from '../lib/dialogs'
import type { TaskState } from '../ws/useTasks'

const DEFAULT_REGION: RemovalRegion = { x: 5, y: 75, width: 90, height: 20 }

function numberSetting(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringSetting(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function clampRegion(region: RemovalRegion): RemovalRegion {
  const width = Math.max(1, Math.min(100, Math.round(region.width)))
  const height = Math.max(1, Math.min(100, Math.round(region.height)))
  return {
    x: Math.max(0, Math.min(100 - width, Math.round(region.x))),
    y: Math.max(0, Math.min(100 - height, Math.round(region.y))),
    width,
    height,
  }
}

export function RemovalPage() {
  const galaxyProjectId = useActiveProjectId()
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

  const [videoPath, setVideoPath] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [videoRatio, setVideoRatio] = useState(16 / 9)
  const [outputDir, setOutputDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [mode, setMode] = useState('blur')
  const [region, setRegion] = useState<RemovalRegion>(DEFAULT_REGION)
  const [blurStrength, setBlurStrength] = useState(18)
  const [device, setDevice] = useState('auto')
  const [licenseAccepted, setLicenseAccepted] = useState(false)
  const [snapshotUrl, setSnapshotUrl] = useState('')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<RemovalResult | null>(null)

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings || seeded.current) return
    seeded.current = true
    setOutputDir(stringSetting(settings.output_dir, ''))
    setMode(stringSetting(settings.subtitle_removal_mode, 'blur'))
    setRegion(clampRegion({
      x: numberSetting(settings.subtitle_region_x, DEFAULT_REGION.x),
      y: numberSetting(settings.subtitle_region_y, DEFAULT_REGION.y),
      width: numberSetting(settings.subtitle_region_width, DEFAULT_REGION.width),
      height: numberSetting(settings.subtitle_region_height, DEFAULT_REGION.height),
    }))
    setBlurStrength(numberSetting(settings.subtitle_blur_strength, 18))
    setDevice(stringSetting(settings.removal_processing_device, 'auto'))
    setLicenseAccepted(settings.propainter_license_accepted === true)
  }, [settingsQuery.data])

  useEffect(() => () => {
    if (snapshotUrl) URL.revokeObjectURL(snapshotUrl)
  }, [snapshotUrl])

  const selectedMode = useMemo(
    () => metaQuery.data?.modes.find((item) => item.code === mode),
    [metaQuery.data, mode],
  )
  const usesAi = selectedMode?.uses_ai ?? false
  const usesRegion = mode !== 'strip'

  const loadVideo = async (path: string) => {
    if (!path.trim()) return
    setMessage('Đang đọc thông tin video...')
    setResult(null)
    try {
      const source = await registerRemovalSource(path)
      setVideoPath(path)
      setVideoUrl(source.url)
      setVideoRatio(source.width / source.height)
      setProjectName(`${source.name.replace(/\.[^.]+$/, '')}-clean`)
      setMessage(`${source.name} · ${source.width}×${source.height}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const chooseVideo = async () => {
    const path = await pickVideoFile()
    if (path) await loadVideo(path)
    else if (!hasNativeDialogs()) setMessage('Nhập đường dẫn video rồi bấm Nạp video.')
  }

  const chooseOutput = async () => {
    const path = await pickFolder()
    if (path) setOutputDir(path)
    else if (!hasNativeDialogs()) setMessage('Nhập trực tiếp đường dẫn thư mục xuất.')
  }

  const updateRegionField = (key: keyof RemovalRegion, value: number) => {
    setRegion((current) => clampRegion({ ...current, [key]: value }))
  }

  const beginDrag = (event: React.PointerEvent<HTMLDivElement>, type: 'move' | 'resize') => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { type, startX: event.clientX, startY: event.clientY, region }
  }

  const moveRegion = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const bounds = event.currentTarget.closest('.video-stage')?.getBoundingClientRect()
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
    const dx = ((event.clientX - drag.startX) / bounds.width) * 100
    const dy = ((event.clientY - drag.startY) / bounds.height) * 100
    if (drag.type === 'move') {
      setRegion(clampRegion({ ...drag.region, x: drag.region.x + dx, y: drag.region.y + dy }))
    } else {
      setRegion(clampRegion({
        ...drag.region,
        width: drag.region.width + dx,
        height: drag.region.height + dy,
      }))
    }
  }

  const createSnapshot = async () => {
    if (!videoPath) return
    setMessage('Đang lấy frame xem trước...')
    try {
      const blob = await fetchRemovalPreview(videoPath, videoRef.current?.currentTime ?? 0, region)
      const nextUrl = URL.createObjectURL(blob)
      setSnapshotUrl((current) => {
        if (current) URL.revokeObjectURL(current)
        return nextUrl
      })
      setMessage('Đã chụp frame tại vị trí hiện tại.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const start = async (): Promise<string> => {
    if (!videoPath) throw new Error('Chọn video đầu vào.')
    if (!outputDir.trim()) throw new Error('Chọn thư mục xuất.')
    if (usesAi && !licenseAccepted) throw new Error('Cần xác nhận license phi thương mại của ProPainter.')
    if (usesAi && !metaQuery.data?.propainter_ready) throw new Error('ProPainter chưa được cài đầy đủ.')
    setResult(null)
    setMessage('Đã gửi tác vụ xóa phụ đề.')
    await updateSettings({
      output_dir: outputDir,
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
      video_path: videoPath,
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

  const onFinished = (task: TaskState) => {
    if (task.status === 'done' && task.result) {
      setResult(task.result as RemovalResult)
      setMessage('Xóa phụ đề hoàn tất.')
    } else if (task.status === 'failed') {
      setMessage(task.error ?? 'Xóa phụ đề thất bại.')
    } else if (task.status === 'cancelled') {
      setMessage('Đã dừng tác vụ xóa phụ đề.')
    }
  }

  return (
    <div className="removal-page">
      <header className="workspace-heading">
        <div>
          <h1>Xóa phụ đề</h1>
          <p>Bỏ track sub hoặc làm sạch phụ đề cháy ngay trên vùng đã chọn.</p>
        </div>
        <div className={`runtime-pill ${metaQuery.data?.propainter_ready ? 'ready' : 'unavailable'}`}>
          <span className="status-dot" />
          {metaQuery.data?.propainter_ready ? 'ProPainter sẵn sàng' : 'ProPainter chưa cài'}
        </div>
      </header>

      <div className="removal-grid">
        <section className="section-card removal-preview-card">
          <div className="section-header compact">
            <h2 className="section-title">Xem trước và chọn vùng</h2>
            <button className="btn" disabled={!videoUrl} onClick={() => void createSnapshot()}>
              Chụp frame hiện tại
            </button>
          </div>
          <div className="video-stage" style={{ aspectRatio: videoRatio }}>
            {videoUrl ? (
              <>
                <video ref={videoRef} controls preload="metadata" src={videoUrl} />
                {usesRegion && (
                  <div
                    className="removal-region"
                    style={{ left: `${region.x}%`, top: `${region.y}%`, width: `${region.width}%`, height: `${region.height}%` }}
                    onPointerDown={(event) => beginDrag(event, 'move')}
                    onPointerMove={moveRegion}
                    onPointerUp={() => { dragRef.current = null }}
                    onPointerCancel={() => { dragRef.current = null }}
                  >
                    <span>Vùng phụ đề</span>
                    <div
                      className="region-resize"
                      onPointerDown={(event) => { event.stopPropagation(); beginDrag(event, 'resize') }}
                      onPointerMove={moveRegion}
                      onPointerUp={() => { dragRef.current = null }}
                      onPointerCancel={() => { dragRef.current = null }}
                    />
                  </div>
                )}
              </>
            ) : (
              <button className="video-empty" onClick={() => void chooseVideo()}>Chọn video để bắt đầu</button>
            )}
          </div>
          {snapshotUrl && (
            <div className="snapshot-row">
              <img src={snapshotUrl} alt="Frame xem trước" />
              <span>Frame tại vị trí thanh phát để đối chiếu vùng cần xử lý.</span>
            </div>
          )}
        </section>

        <aside>
          <section className="section-card">
            <h2 className="section-title">Nguồn và đầu ra</h2>
            <div className="field field-wide">
              <label htmlFor="removal-video-path">Video đầu vào</label>
              <div className="input-action">
                <input id="removal-video-path" value={videoPath} onChange={(event) => setVideoPath(event.target.value)} />
                <button className="btn" onClick={() => void chooseVideo()}>Chọn file</button>
                {!hasNativeDialogs() && <button className="btn" onClick={() => void loadVideo(videoPath)}>Nạp</button>}
              </div>
            </div>
            <div className="field field-wide">
              <label>Thư mục xuất</label>
              <div className="input-action">
                <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
                <button className="btn" onClick={() => void chooseOutput()}>Chọn</button>
              </div>
            </div>
            <div className="field">
              <label>Tên project</label>
              <input type="text" value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            </div>
          </section>

          <section className="section-card">
            <h2 className="section-title">Cách xử lý</h2>
            <div className="field-grid removal-controls">
              <div className="field field-wide">
                <label htmlFor="removal-mode">Chế độ</label>
                <select id="removal-mode" value={mode} onChange={(event) => setMode(event.target.value)}>
                  {(metaQuery.data?.modes ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                </select>
              </div>
              {usesRegion && (['x', 'y', 'width', 'height'] as const).map((key) => (
                <div className="field" key={key}>
                  <label>{{ x: 'X (%)', y: 'Y (%)', width: 'Rộng (%)', height: 'Cao (%)' }[key]}</label>
                  <input type="number" min={key === 'x' || key === 'y' ? 0 : 1} max={100} value={region[key]} onChange={(event) => updateRegionField(key, Number(event.target.value))} />
                </div>
              ))}
              {mode === 'blur' && (
                <div className="field field-wide">
                  <label>Độ mờ: {blurStrength}</label>
                  <input type="range" min="1" max="100" value={blurStrength} onChange={(event) => setBlurStrength(Number(event.target.value))} />
                </div>
              )}
              {usesAi && (
                <div className="field field-wide">
                  <label htmlFor="removal-device">Thiết bị xử lý</label>
                  <select id="removal-device" value={device} onChange={(event) => setDevice(event.target.value)}>
                    {(settingsMetaQuery.data?.processing_devices ?? []).map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                  </select>
                </div>
              )}
              {usesAi && (
                <div className="field-check field-wide license-check">
                  <input id="propainter-license" type="checkbox" checked={licenseAccepted} onChange={(event) => setLicenseAccepted(event.target.checked)} />
                  <label htmlFor="propainter-license">Tôi chấp nhận ProPainter chỉ dùng phi thương mại theo NTU S-Lab License 1.0.</label>
                </div>
              )}
            </div>
            {usesAi && !metaQuery.data?.propainter_ready && (
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
          </section>

          <section className="section-card action-card removal-actions">
            <TaskButton label="Xử lý video" variant="accent" onStart={start} onFinish={onFinished} />
            {result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}
          </section>
          {message && <p className="action-message removal-message">{message}</p>}
          {result && (
            <section className="section-card">
              <h2 className="section-title">Video đã làm sạch</h2>
              <video className="result-video" controls preload="metadata" src={result.video_url} />
              {result.warnings.map((warning) => <p className="field-hint" key={warning}>{warning}</p>)}
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}

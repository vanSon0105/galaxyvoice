import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchRemovalMeta,
  fetchRemovalPreview,
  installProPainter,
  startSubtitleRemoval,
} from '../../api/removal'
import type { RemovalMask, RemovalRegion, RemovalResult } from '../../api/removal'
import type { EditorMedia } from '../../api/editor'
import { fetchSettings, fetchSettingsMeta, updateSettings } from '../../api/settings'
import { openPath } from '../../api/voice'
import { TaskButton } from '../TaskButton'
import type { TaskState } from '../../ws/useTasks'

const DEFAULT_REMOVAL_REGION: RemovalRegion = { x: 5, y: 75, width: 90, height: 20 }
const MAX_REMOVAL_MASKS = 12

interface EditableRemovalMask extends RemovalMask {
  whole_video: boolean
}

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

function hasConcurrentMaskOverlap(masks: EditableRemovalMask[]): boolean {
  return masks.some((left, index) => masks.slice(index + 1).some((right) => {
    const regionsOverlap = left.region.x < right.region.x + right.region.width
      && right.region.x < left.region.x + left.region.width
      && left.region.y < right.region.y + right.region.height
      && right.region.y < left.region.y + left.region.height
    const leftStart = left.whole_video ? 0 : left.start_seconds
    const rightStart = right.whole_video ? 0 : right.start_seconds
    const leftEnd = left.whole_video || left.end_seconds === null ? Infinity : left.end_seconds
    const rightEnd = right.whole_video || right.end_seconds === null ? Infinity : right.end_seconds
    return regionsOverlap && leftStart < rightEnd && rightStart < leftEnd
  }))
}

interface SubtitleRemovalPanelProps {
  galaxyProjectId: string
  source: EditorMedia | null
  outputDir: string
  onCompleted: (result: RemovalResult) => Promise<void> | void
  onReplace: (result: RemovalResult) => Promise<void> | void
  canRestore: boolean
  onRestore: () => void
}

export function SubtitleRemovalPanel({
  galaxyProjectId,
  source,
  outputDir,
  onCompleted,
  onReplace,
  canRestore,
  onRestore,
}: SubtitleRemovalPanelProps) {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const settingsMetaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })
  const metaQuery = useQuery({ queryKey: ['removal-meta'], queryFn: fetchRemovalMeta })
  const videoRef = useRef<HTMLVideoElement>(null)
  const seeded = useRef(false)
  const dragRef = useRef<{
    type: 'move' | 'resize'
    maskId: string
    startX: number
    startY: number
    region: RemovalRegion
  } | null>(null)

  const [mode, setMode] = useState('blur')
  const [masks, setMasks] = useState<EditableRemovalMask[]>([{
    id: crypto.randomUUID(),
    name: 'Vùng 1',
    region: DEFAULT_REMOVAL_REGION,
    start_seconds: 0,
    end_seconds: null,
    whole_video: true,
  }])
  const [activeMaskId, setActiveMaskId] = useState(masks[0].id)
  const [blurStrength, setBlurStrength] = useState(18)
  const [device, setDevice] = useState('auto')
  const [licenseAccepted, setLicenseAccepted] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [beforeSnapshotUrl, setBeforeSnapshotUrl] = useState('')
  const [afterSnapshotUrl, setAfterSnapshotUrl] = useState('')
  const beforeSnapshotUrlRef = useRef('')
  const afterSnapshotUrlRef = useRef('')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<RemovalResult | null>(null)
  const sourcePath = source?.path ?? ''
  const sourceName = source?.name ?? ''
  const activeMask = masks.find((mask) => mask.id === activeMaskId) ?? masks[0]
  const region = activeMask?.region ?? DEFAULT_REMOVAL_REGION

  useEffect(() => {
    const settings = settingsQuery.data
    if (!settings || seeded.current) return
    seeded.current = true
    setMode(stringSetting(settings.subtitle_removal_mode, 'blur'))
    const configuredRegion = clampRemovalRegion({
      x: numberSetting(settings.subtitle_region_x, DEFAULT_REMOVAL_REGION.x),
      y: numberSetting(settings.subtitle_region_y, DEFAULT_REMOVAL_REGION.y),
      width: numberSetting(settings.subtitle_region_width, DEFAULT_REMOVAL_REGION.width),
      height: numberSetting(settings.subtitle_region_height, DEFAULT_REMOVAL_REGION.height),
    })
    setMasks((current) => current.map((mask, index) => index === 0
      ? { ...mask, region: configuredRegion }
      : mask))
    setBlurStrength(numberSetting(settings.subtitle_blur_strength, 18))
    setDevice(stringSetting(settings.removal_processing_device, 'auto'))
    setLicenseAccepted(settings.propainter_license_accepted === true)
  }, [settingsQuery.data])

  useEffect(() => {
    setProjectName(sourceName ? `${sourceName.replace(/\.[^.]+$/, '')}-clean` : '')
    setResult(null)
    setMessage('')
    if (beforeSnapshotUrlRef.current) URL.revokeObjectURL(beforeSnapshotUrlRef.current)
    if (afterSnapshotUrlRef.current) URL.revokeObjectURL(afterSnapshotUrlRef.current)
    beforeSnapshotUrlRef.current = ''
    afterSnapshotUrlRef.current = ''
    setBeforeSnapshotUrl('')
    setAfterSnapshotUrl('')
  }, [sourceName, sourcePath])

  useEffect(() => () => {
    if (beforeSnapshotUrlRef.current) URL.revokeObjectURL(beforeSnapshotUrlRef.current)
    if (afterSnapshotUrlRef.current) URL.revokeObjectURL(afterSnapshotUrlRef.current)
  }, [])

  const selectedMode = useMemo(
    () => metaQuery.data?.modes.find((item) => item.code === mode),
    [metaQuery.data, mode],
  )
  const usesAi = selectedMode?.uses_ai ?? false
  const usesRegion = mode !== 'strip'
  const qualityWarnings = useMemo(() => {
    if (!usesRegion) return []
    const warnings: string[] = []
    if (mode === 'blur') warnings.push('Làm mờ che chữ nhưng cũng làm mềm chi tiết nền trong vùng xóa.')
    if (mode === 'fill') warnings.push('Smart Fill có thể để lại vệt trên nền chuyển động.')
    if (usesAi) warnings.push('AI có thể tạo chi tiết giả; hãy kiểm tra khung trước và sau khi xử lý.')
    if (masks.some((mask) => mask.region.width * mask.region.height >= 3_500)) {
      warnings.push('Có vùng xóa lớn chiếm ít nhất 35% khung hình, chất lượng có thể giảm rõ rệt.')
    }
    if (hasConcurrentMaskOverlap(masks)) {
      warnings.push('Có các vùng xóa chồng nhau trong cùng thời gian; hiệu ứng xử lý có thể bị cộng dồn.')
    }
    return warnings
  }, [masks, mode, usesAi, usesRegion])

  const updateActiveMask = (update: (mask: EditableRemovalMask) => EditableRemovalMask) => {
    setMasks((current) => current.map((mask) => mask.id === activeMaskId ? update(mask) : mask))
  }

  const updateRegionField = (key: keyof RemovalRegion, value: number) => {
    updateActiveMask((mask) => ({
      ...mask,
      region: clampRemovalRegion({ ...mask.region, [key]: value }),
    }))
  }

  const beginDrag = (
    event: React.PointerEvent<HTMLDivElement>,
    type: 'move' | 'resize',
    mask: EditableRemovalMask,
  ) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    setActiveMaskId(mask.id)
    dragRef.current = {
      type,
      maskId: mask.id,
      startX: event.clientX,
      startY: event.clientY,
      region: mask.region,
    }
  }

  const moveRegion = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const bounds = event.currentTarget.closest('.editor-removal-stage')?.getBoundingClientRect()
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
    const dx = ((event.clientX - drag.startX) / bounds.width) * 100
    const dy = ((event.clientY - drag.startY) / bounds.height) * 100
    const nextRegion = clampRemovalRegion(drag.type === 'move'
      ? { ...drag.region, x: drag.region.x + dx, y: drag.region.y + dy }
      : { ...drag.region, width: drag.region.width + dx, height: drag.region.height + dy })
    setMasks((current) => current.map((mask) => mask.id === drag.maskId
      ? { ...mask, region: nextRegion }
      : mask))
  }

  const addMask = () => {
    if (masks.length >= MAX_REMOVAL_MASKS) return
    const next: EditableRemovalMask = {
      id: crypto.randomUUID(),
      name: 'Vùng ' + (masks.length + 1),
      region: DEFAULT_REMOVAL_REGION,
      start_seconds: 0,
      end_seconds: null,
      whole_video: true,
    }
    setMasks((current) => [...current, next])
    setActiveMaskId(next.id)
  }

  const removeActiveMask = () => {
    if (masks.length <= 1) return
    const index = masks.findIndex((mask) => mask.id === activeMaskId)
    const remaining = masks.filter((mask) => mask.id !== activeMaskId)
    setMasks(remaining)
    setActiveMaskId(remaining[Math.max(0, index - 1)]?.id ?? remaining[0].id)
  }

  const applyPreset = (presetCode: string) => {
    const preset = metaQuery.data?.region_presets.find((item) => item.code === presetCode)
    if (!preset) return
    updateActiveMask((mask) => ({
      ...mask,
      region: clampRemovalRegion(preset.region),
    }))
  }

  const createSnapshot = async () => {
    if (!source) return
    setMessage('Đang tạo ảnh xem trước...')
    try {
      const blob = await fetchRemovalPreview(source.path, videoRef.current?.currentTime ?? 0, region)
      const nextUrl = URL.createObjectURL(blob)
      if (beforeSnapshotUrlRef.current) URL.revokeObjectURL(beforeSnapshotUrlRef.current)
      if (afterSnapshotUrlRef.current) URL.revokeObjectURL(afterSnapshotUrlRef.current)
      beforeSnapshotUrlRef.current = nextUrl
      afterSnapshotUrlRef.current = ''
      setBeforeSnapshotUrl(nextUrl)
      setAfterSnapshotUrl('')
      setMessage('Đã tạo ảnh xem trước.')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const createComparison = async (sourceVideoPath: string, cleanPath: string) => {
    const timestamp = videoRef.current?.currentTime ?? 0
    const [beforeBlob, afterBlob] = await Promise.all([
      fetchRemovalPreview(sourceVideoPath, timestamp, region),
      fetchRemovalPreview(cleanPath, timestamp, region),
    ])
    const nextBefore = URL.createObjectURL(beforeBlob)
    const nextAfter = URL.createObjectURL(afterBlob)
    if (beforeSnapshotUrlRef.current) URL.revokeObjectURL(beforeSnapshotUrlRef.current)
    if (afterSnapshotUrlRef.current) URL.revokeObjectURL(afterSnapshotUrlRef.current)
    beforeSnapshotUrlRef.current = nextBefore
    afterSnapshotUrlRef.current = nextAfter
    setBeforeSnapshotUrl(nextBefore)
    setAfterSnapshotUrl(nextAfter)
  }

  const start = async (): Promise<string> => {
    if (!source) throw new Error('Chọn một clip video trên timeline.')
    if (!outputDir.trim()) throw new Error('Chọn thư mục xuất trong phần Xuất video.')
    if (usesAi && !licenseAccepted) throw new Error('Cần xác nhận license phi thương mại của ProPainter.')
    if (usesAi && !metaQuery.data?.propainter_ready) throw new Error('ProPainter chưa được cài đầy đủ.')
    for (const mask of masks) {
      if (!mask.name.trim()) throw new Error('Mỗi vùng xóa cần có tên.')
      if (!mask.whole_video && (mask.end_seconds === null || mask.end_seconds <= mask.start_seconds)) {
        throw new Error('Khoảng thời gian của ' + mask.name + ' không hợp lệ.')
      }
      if (!mask.whole_video && mask.end_seconds !== null && mask.end_seconds > source.duration_seconds) {
        throw new Error('Khoảng thời gian của ' + mask.name + ' vượt quá video.')
      }
    }
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
      masks: masks.map((mask) => ({
        id: mask.id,
        name: mask.name.trim(),
        region: mask.region,
        start_seconds: mask.whole_video ? 0 : mask.start_seconds,
        end_seconds: mask.whole_video ? null : mask.end_seconds,
      })),
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
      void createComparison(completed.source_video_path, completed.video_path).catch((cause) => {
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
        {usesRegion && masks.map((mask) => (
          <div
            key={mask.id}
            className={`removal-region${mask.id === activeMaskId ? ' active' : ''}`}
            style={{ left: `${mask.region.x}%`, top: `${mask.region.y}%`, width: `${mask.region.width}%`, height: `${mask.region.height}%` }}
            onPointerDown={(event) => beginDrag(event, 'move', mask)}
            onPointerMove={moveRegion}
            onPointerUp={() => { dragRef.current = null }}
            onPointerCancel={() => { dragRef.current = null }}
          >
            <span>{mask.name}</span>
            {mask.id === activeMaskId && <div
              className="region-resize"
              onPointerDown={(event) => { event.stopPropagation(); beginDrag(event, 'resize', mask) }}
              onPointerMove={moveRegion}
              onPointerUp={() => { dragRef.current = null }}
              onPointerCancel={() => { dragRef.current = null }}
            />}
          </div>
        ))}
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
        <div className="editor-removal-mask-editor">
          <div className="editor-removal-mask-list">
            {masks.map((mask) => <button
              type="button"
              key={mask.id}
              className={`btn${mask.id === activeMaskId ? ' active' : ''}`}
              onClick={() => setActiveMaskId(mask.id)}
            >{mask.name}</button>)}
            <button type="button" className="btn" disabled={masks.length >= MAX_REMOVAL_MASKS} onClick={addMask}>Thêm vùng</button>
          </div>
          {activeMask && <>
            <div className="field-grid editor-removal-mask-identity">
              <div className="field">
                <label htmlFor="editor-removal-mask-name">Tên vùng</label>
                <input id="editor-removal-mask-name" value={activeMask.name} onChange={(event) => updateActiveMask((mask) => ({ ...mask, name: event.target.value }))} />
              </div>
              <div className="field">
                <label htmlFor="editor-removal-preset">Mẫu vùng</label>
                <select id="editor-removal-preset" aria-label="Mẫu vùng" value="" onChange={(event) => applyPreset(event.target.value)}>
                  <option value="">Chọn mẫu</option>
                  {(metaQuery.data?.region_presets ?? []).map((preset) => <option key={preset.code} value={preset.code}>{preset.name}</option>)}
                </select>
              </div>
              <button type="button" className="btn danger" disabled={masks.length <= 1} onClick={removeActiveMask}>Xóa vùng</button>
            </div>
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
            <div className="field-check editor-removal-whole-video">
              <input
                id="editor-removal-whole-video"
                aria-label="Toàn bộ video"
                type="checkbox"
                checked={activeMask.whole_video}
                onChange={(event) => updateActiveMask((mask) => ({
                  ...mask,
                  whole_video: event.target.checked,
                  start_seconds: event.target.checked ? 0 : mask.start_seconds,
                  end_seconds: event.target.checked ? null : (mask.end_seconds ?? source.duration_seconds),
                }))}
              />
              <label htmlFor="editor-removal-whole-video">Toàn bộ video</label>
            </div>
            {!activeMask.whole_video && <div className="field-grid editor-removal-range-fields">
              <div className="field"><label htmlFor="editor-removal-range-start">Bắt đầu</label><input id="editor-removal-range-start" aria-label="Bắt đầu vùng" type="number" min="0" max={source.duration_seconds} step="0.1" value={activeMask.start_seconds} onChange={(event) => updateActiveMask((mask) => ({ ...mask, start_seconds: Number(event.target.value) }))} /></div>
              <div className="field"><label htmlFor="editor-removal-range-end">Kết thúc</label><input id="editor-removal-range-end" aria-label="Kết thúc vùng" type="number" min="0.1" max={source.duration_seconds} step="0.1" value={activeMask.end_seconds ?? source.duration_seconds} onChange={(event) => updateActiveMask((mask) => ({ ...mask, end_seconds: Number(event.target.value) }))} /></div>
            </div>}
          </>}
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

      {qualityWarnings.length > 0 && <div className="editor-removal-warnings">
        <strong>Cảnh báo chất lượng</strong>
        {qualityWarnings.map((warning) => <span key={warning}>{warning}</span>)}
      </div>}

      <div className="editor-removal-actions">
        <button className="btn" onClick={() => void createSnapshot()}>Xem trước vùng</button>
        <TaskButton label="Xóa phụ đề" variant="accent" onStart={start} onFinish={finish} />
        {result && <button className="btn" onClick={() => void openPath(result.project_dir)}>Mở thư mục</button>}
        {result && result.source_video_path === source.path && <button className="btn accent" onClick={() => void onReplace(result)}>Thay clip đã chọn</button>}
        {canRestore && <button className="btn" onClick={onRestore}>Khôi phục clip gốc</button>}
      </div>
      {message && <p className="action-message editor-removal-message">{message}</p>}
      {result && result.warnings.length > 0 && <div className="editor-removal-warnings result">
        {result.warnings.map((warning) => <span key={warning}>{warning}</span>)}
      </div>}
      {beforeSnapshotUrl && <div className={`editor-removal-comparison${afterSnapshotUrl ? ' complete' : ''}`}>
        <figure><figcaption>Trước xử lý</figcaption><img src={beforeSnapshotUrl} alt="Khung hình trước xử lý" /></figure>
        {afterSnapshotUrl && <figure><figcaption>Sau xử lý</figcaption><img src={afterSnapshotUrl} alt="Khung hình sau xử lý" /></figure>}
      </div>}
    </div>
  )
}

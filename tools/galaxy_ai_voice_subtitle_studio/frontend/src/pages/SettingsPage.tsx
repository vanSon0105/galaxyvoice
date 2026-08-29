import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchSettings, fetchSettingsMeta, updateSettings } from '../api/settings'
import type { AppSettings, Option, SettingsMeta } from '../api/settings'
import { ExtensionCapabilitiesPanel } from '../components/ExtensionCapabilitiesPanel'
import { useT } from '../i18n/useT'

type FieldType = 'text' | 'int' | 'number' | 'bool' | 'select'

interface FieldSchema {
  key: string
  label: string
  type: FieldType
  section: string
  options?: Option[]
  min?: number
  max?: number
  step?: number
}

const SECTIONS: { key: string; label: string }[] = [
  { key: 'general', label: 'Chung' },
  { key: 'voice', label: 'Giọng đọc' },
  { key: 'translation', label: 'Dịch & phụ đề' },
  { key: 'removal', label: 'Xóa phụ đề' },
  { key: 'audio', label: 'Tách âm thanh' },
  { key: 'editor', label: 'Dựng video' },
  { key: 'omnivoice', label: 'OmniVoice' },
]

function optionField(key: string, label: string, section: string, options: Option[]): FieldSchema {
  return { key, label, type: 'select', section, options }
}

function buildSchema(meta: SettingsMeta): FieldSchema[] {
  return [
    { key: 'output_dir', label: 'Thư mục xuất', type: 'text', section: 'general' },
    optionField('tts_engine', 'Engine giọng đọc', 'voice', meta.tts_engines),
    { key: 'voice_name', label: 'Giọng đọc', type: 'text', section: 'voice' },
    { key: 'rate', label: 'Tốc độ (-10..10)', type: 'int', section: 'voice', min: -10, max: 10 },
    { key: 'volume', label: 'Âm lượng (0..100)', type: 'int', section: 'voice', min: 0, max: 100 },
    { key: 'pause_ms', label: 'Khoảng nghỉ giữa đoạn (ms)', type: 'int', section: 'voice', min: 0, max: 1200 },
    { key: 'max_chars', label: 'Độ dài đoạn tối đa (ký tự)', type: 'int', section: 'voice', min: 60, max: 260 },
    { key: 'export_mp3', label: 'Xuất thêm MP3', type: 'bool', section: 'voice' },
    { key: 'keep_segments', label: 'Giữ các đoạn audio riêng lẻ', type: 'bool', section: 'voice' },
    optionField('video_source_language', 'Ngôn ngữ video nguồn', 'translation', meta.source_languages),
    optionField('video_target_language', 'Ngôn ngữ dịch', 'translation', meta.target_languages),
    optionField('whisper_model', 'Model Whisper', 'translation', meta.whisper_models.map((m) => ({ code: m, label: m }))),
    optionField('ai_provider', 'Nhà cung cấp AI dịch', 'translation', meta.translation_providers),
    { key: 'ai_model', label: 'Model AI dịch', type: 'text', section: 'translation' },
    { key: 'ai_base_url', label: 'Base URL (OpenAI-compatible)', type: 'text', section: 'translation' },
    optionField('voice_processing_device', 'Thiết bị xử lý giọng', 'translation', meta.processing_devices),
    optionField('subtitle_removal_mode', 'Chế độ xóa phụ đề', 'removal', meta.removal_modes),
    { key: 'subtitle_region_x', label: 'Vùng phụ đề X (%)', type: 'int', section: 'removal', min: 0, max: 99 },
    { key: 'subtitle_region_y', label: 'Vùng phụ đề Y (%)', type: 'int', section: 'removal', min: 0, max: 99 },
    { key: 'subtitle_region_width', label: 'Vùng phụ đề rộng (%)', type: 'int', section: 'removal', min: 1, max: 100 },
    { key: 'subtitle_region_height', label: 'Vùng phụ đề cao (%)', type: 'int', section: 'removal', min: 1, max: 100 },
    { key: 'subtitle_blur_strength', label: 'Độ mờ', type: 'int', section: 'removal', min: 1, max: 100 },
    optionField('removal_processing_device', 'Thiết bị xử lý', 'removal', meta.processing_devices),
    { key: 'propainter_license_accepted', label: 'Đã chấp nhận license ProPainter', type: 'bool', section: 'removal' },
    { key: 'audio_output_dir', label: 'Thư mục xuất', type: 'text', section: 'audio' },
    optionField('audio_process_method', 'Phương pháp tách', 'audio', meta.audio_methods),
    { key: 'audio_model_name', label: 'Model', type: 'text', section: 'audio' },
    optionField('audio_output_format', 'Định dạng xuất', 'audio', meta.audio_formats.map((f) => ({ code: f, label: f }))),
    { key: 'audio_segment_size', label: 'Kích thước đoạn', type: 'text', section: 'audio' },
    { key: 'audio_overlap', label: 'Overlap', type: 'text', section: 'audio' },
    optionField('audio_processing_device', 'Thiết bị xử lý', 'audio', meta.audio_devices),
    { key: 'audio_gpu_conversion', label: 'Chuyển đổi bằng GPU', type: 'bool', section: 'audio' },
    { key: 'audio_vocals_only', label: 'Chỉ giọng hát', type: 'bool', section: 'audio' },
    { key: 'audio_instrumental_only', label: 'Chỉ nhạc nền', type: 'bool', section: 'audio' },
    { key: 'audio_sample_mode', label: 'Chế độ mẫu', type: 'bool', section: 'audio' },
    { key: 'editor_output_dir', label: 'Thư mục xuất', type: 'text', section: 'editor' },
    optionField('editor_resolution', 'Độ phân giải', 'editor', meta.editor_resolutions),
    optionField('editor_fps', 'FPS', 'editor', meta.editor_fps),
    optionField('editor_encoder', 'Encoder', 'editor', meta.editor_encoders),
    optionField('editor_audio_mode', 'Chế độ âm thanh', 'editor', meta.editor_audio_modes),
    { key: 'editor_source_volume', label: 'Âm lượng gốc (0..200)', type: 'int', section: 'editor', min: 0, max: 200 },
    { key: 'editor_external_volume', label: 'Âm lượng lồng tiếng (0..200)', type: 'int', section: 'editor', min: 0, max: 200 },
    { key: 'editor_subtitle_font_size', label: 'Cỡ chữ phụ đề', type: 'int', section: 'editor', min: 10, max: 72 },
    { key: 'editor_subtitle_margin', label: 'Lề phụ đề', type: 'int', section: 'editor', min: 0, max: 300 },
    { key: 'editor_timeline_zoom', label: 'Zoom timeline', type: 'number', section: 'editor', min: 0.1, max: 300 },
    { key: 'omnivoice_output_dir', label: 'Thư mục xuất', type: 'text', section: 'omnivoice' },
    { key: 'omnivoice_model_id', label: 'Model ID', type: 'text', section: 'omnivoice' },
    optionField('omnivoice_device', 'Thiết bị', 'omnivoice', meta.omnivoice_devices),
    { key: 'omnivoice_language', label: 'Ngôn ngữ', type: 'text', section: 'omnivoice' },
    { key: 'omnivoice_num_step', label: 'Số bước (4..64)', type: 'int', section: 'omnivoice', min: 4, max: 64 },
    { key: 'omnivoice_guidance_scale', label: 'Guidance scale (0..4)', type: 'number', section: 'omnivoice', min: 0, max: 4, step: 0.1 },
    { key: 'omnivoice_t_shift', label: 'T-shift (0.01..1)', type: 'number', section: 'omnivoice', min: 0.01, max: 1, step: 0.01 },
    { key: 'omnivoice_speed', label: 'Tốc độ (0.5..1.5)', type: 'number', section: 'omnivoice', min: 0.5, max: 1.5, step: 0.1 },
    { key: 'omnivoice_export_mp3', label: 'Xuất thêm MP3', type: 'bool', section: 'omnivoice' },
    { key: 'omnivoice_enable_flashinfer', label: 'Bật FlashInfer', type: 'bool', section: 'omnivoice' },
  ]
}

function coerceValue(field: FieldSchema, raw: string | boolean): string | number | boolean | null {
  if (field.type === 'bool') return raw === true
  if (field.type === 'int') {
    const value = Number.parseInt(String(raw), 10)
    return Number.isFinite(value) ? value : null
  }
  if (field.type === 'number') {
    const value = Number.parseFloat(String(raw))
    return Number.isFinite(value) ? value : null
  }
  return String(raw)
}

export function SettingsPage() {
  const t = useT()
  const queryClient = useQueryClient()
  const [saveNote, setSaveNote] = useState('')
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const timerRef = useRef<number | undefined>(undefined)
  const pendingPatchRef = useRef<Record<string, unknown>>({})

  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const metaQuery = useQuery({ queryKey: ['settings-meta'], queryFn: fetchSettingsMeta })

  const saveMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: (saved) => {
      queryClient.setQueryData(['settings'], saved)
      setSaveNote(t('settings.saved'))
    },
    onError: (_error, attemptedPatch) => {
      pendingPatchRef.current = { ...attemptedPatch, ...pendingPatchRef.current }
      setSaveNote(t('settings.saveError'))
    },
  })

  const schema = useMemo(
    () => (metaQuery.data ? buildSchema(metaQuery.data) : []),
    [metaQuery.data],
  )

  useEffect(() => {
    return () => {
      window.clearTimeout(timerRef.current)
      const patch = pendingPatchRef.current
      pendingPatchRef.current = {}
      if (Object.keys(patch).length > 0) {
        void updateSettings(patch).then((saved) => {
          queryClient.setQueryData(['settings'], saved)
        }).catch(() => undefined)
      }
    }
  }, [queryClient])

  useEffect(() => {
    if (settingsQuery.data && draft === null) {
      setDraft(settingsQuery.data)
    }
  }, [draft, settingsQuery.data])

  const settingsPending = settingsQuery.isPending || metaQuery.isPending
  const settingsUnavailable = !settingsQuery.data || !metaQuery.data || draft === null
  const settings = draft ?? {}

  const handleChange = (field: FieldSchema, raw: string | boolean) => {
    setDraft((current) => ({ ...(current ?? {}), [field.key]: raw }))
    const value = coerceValue(field, raw)
    if (value === null) return
    pendingPatchRef.current = { ...pendingPatchRef.current, [field.key]: value }
    window.clearTimeout(timerRef.current)
    setSaveNote('')
    timerRef.current = window.setTimeout(() => {
      const patch = pendingPatchRef.current
      pendingPatchRef.current = {}
      saveMutation.mutate(patch)
    }, 400)
  }

  const renderField = (field: FieldSchema) => {
    const current = settings[field.key]
    if (field.type === 'bool') {
      return (
        <div className="field-check" key={field.key}>
          <input
            type="checkbox"
            id={`setting-${field.key}`}
            checked={Boolean(current)}
            onChange={(event) => handleChange(field, event.target.checked)}
          />
          <label htmlFor={`setting-${field.key}`}>{field.label}</label>
        </div>
      )
    }
    const inputType = field.type === 'int' ? 'number' : field.type === 'number' ? 'number' : 'text'
    if (field.type === 'select') {
      return (
        <div className="field" key={field.key}>
          <label htmlFor={`setting-${field.key}`}>{field.label}</label>
          <select
            id={`setting-${field.key}`}
            value={String(current ?? '')}
            onChange={(event) => handleChange(field, event.target.value)}
          >
            {(field.options ?? []).map((option) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      )
    }
    return (
      <div className="field" key={field.key}>
        <label htmlFor={`setting-${field.key}`}>{field.label}</label>
        <input
          id={`setting-${field.key}`}
          type={inputType}
          min={field.min}
          max={field.max}
          step={field.step}
          value={String(current ?? '')}
          onChange={(event) => handleChange(field, event.target.value)}
        />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <h1 className="section-title" style={{ margin: 0 }}>
          {t('settings.title')}
        </h1>
        <span style={{ color: 'var(--color-fg-subtle)', fontSize: 12 }}>{saveNote}</span>
      </div>
      {settingsPending ? (
        <div className="placeholder-page">{t('ws.connecting')}</div>
      ) : settingsUnavailable ? (
        <div className="placeholder-page">{t('settings.loadError')}</div>
      ) : (
        SECTIONS.map((section) => (
          <section className="section-card" key={section.key}>
            <h2 className="section-title">{section.label}</h2>
            <div className="field-grid">
              {schema.filter((field) => field.section === section.key).map(renderField)}
            </div>
          </section>
        ))
      )}
      <ExtensionCapabilitiesPanel />
    </div>
  )
}

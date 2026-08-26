import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import {
  createDesignedVoice,
  deleteLibraryVoice,
  exportLibraryVoice,
  fetchLibraryVoices,
  importLibraryAudio,
  importLibraryBundle,
  pinLibraryVoice,
  setStableSample,
  updateLibraryVoice,
  type LibraryVoice,
} from '../../api/voiceLibrary'
import { WorkspaceLoading, WorkspaceState } from '../../components/WorkspaceState'
import { pickAudioFile, pickFolder, pickVoiceBundleFile } from '../../lib/dialogs'
import { useVoiceProject } from './VoiceProjectContext'

const SOURCE_LABELS = {
  system: 'Hệ thống', imported: 'Đã nhập', cloned: 'Giọng nhái', designed: 'Thiết kế',
} as const

type Composer = 'none' | 'import' | 'design'

export function VoiceLibraryPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { projectId } = useVoiceProject()
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [language, setLanguage] = useState('')
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const [composer, setComposer] = useState<Composer>('none')
  const [message, setMessage] = useState('')

  const voicesQuery = useQuery({
    queryKey: ['voice-library', query, source, language, favoriteOnly],
    queryFn: () => fetchLibraryVoices({ query, source, language, favorite_only: favoriteOnly }),
  })
  const voices = voicesQuery.data ?? []
  const selected = voices.find((voice) => voice.voice_id === selectedId) ?? voices[0] ?? null
  const languages = useMemo(
    () => [...new Set((voicesQuery.data ?? []).map((voice) => voice.language).filter(Boolean))].sort(),
    [voicesQuery.data],
  )

  useEffect(() => {
    if (selected && selected.voice_id !== selectedId) setSelectedId(selected.voice_id)
  }, [selected, selectedId])

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['voice-library'] })
    await queryClient.invalidateQueries({ queryKey: ['omnivoice-profiles'] })
  }

  const favoriteMutation = useMutation({
    mutationFn: (voice: LibraryVoice) => updateLibraryVoice(voice.voice_id, { favorite: !voice.favorite }),
    onSuccess: refresh,
  })

  const handleBundleImport = async () => {
    const path = await pickVoiceBundleFile()
    if (!path) return
    try {
      const voice = await importLibraryBundle(path)
      await refresh()
      setSelectedId(voice.voice_id)
      setMessage(`Đã nhập ${voice.name}.`)
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="library-page">
      <section className="library-toolbar">
        <div className="library-search">
          <label htmlFor="library-search">Tìm giọng</label>
          <input id="library-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tên, tag hoặc ghi chú" />
        </div>
        <div className="field"><label>Nguồn</label><select value={source} onChange={(event) => setSource(event.target.value)}><option value="">Tất cả</option>{Object.entries(SOURCE_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div>
        <div className="field"><label>Ngôn ngữ</label><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="">Tất cả</option>{languages.map((item) => <option key={item}>{item}</option>)}</select></div>
        <label className="library-favorite-filter"><input type="checkbox" checked={favoriteOnly} onChange={(event) => setFavoriteOnly(event.target.checked)} /> Chỉ yêu thích</label>
        <div className="library-toolbar-actions">
          <button className="btn" type="button" onClick={() => setComposer(composer === 'import' ? 'none' : 'import')}>Nhập audio</button>
          <button className="btn" type="button" onClick={() => setComposer(composer === 'design' ? 'none' : 'design')}>Thiết kế giọng</button>
          <button className="btn quiet" type="button" onClick={() => void handleBundleImport()}>Nhập bundle</button>
          <button className="btn quiet" type="button" onClick={() => navigate('/voice/library/gallery')}>Mẫu thiết kế</button>
        </div>
      </section>

      {composer === 'import' && <ImportVoicePanel onClose={() => setComposer('none')} onCreated={async (voice) => { await refresh(); setSelectedId(voice.voice_id); setComposer('none') }} />}
      {composer === 'design' && <DesignVoicePanel onClose={() => setComposer('none')} onCreated={async (voice) => { await refresh(); setSelectedId(voice.voice_id); setComposer('none') }} />}
      {message && <div className="library-message" role="status">{message}<button type="button" onClick={() => setMessage('')}>Đóng</button></div>}

      <div className="library-layout">
        <section className="library-list-panel">
          <div className="section-header compact"><h2 className="section-title">Giọng cục bộ</h2><span className="studio-counter">{voices.length}</span></div>
          {voicesQuery.isPending ? <WorkspaceLoading label="Đang đọc thư viện giọng..." /> : voicesQuery.isError ? <WorkspaceState title="Không đọc được thư viện" tone="error" action={<button className="btn" onClick={() => void voicesQuery.refetch()}>Thử lại</button>} /> : voices.length === 0 ? <WorkspaceState title="Chưa có giọng phù hợp" description="Nhập audio, thiết kế một giọng mới hoặc đổi bộ lọc." /> : (
            <div className="library-voice-list">
              {voices.map((voice) => (
                <div role="button" tabIndex={0} key={voice.voice_id} className={`library-voice-row${selected?.voice_id === voice.voice_id ? ' active' : ''}`} onClick={() => setSelectedId(voice.voice_id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setSelectedId(voice.voice_id) }}>
                  <span className={`library-source-mark ${voice.source}`}>{SOURCE_LABELS[voice.source].slice(0, 1)}</span>
                  <span className="library-voice-copy"><strong>{voice.name}</strong><small>{SOURCE_LABELS[voice.source]} · {voice.language} · {voice.engine_id}</small><span>{voice.tags.length ? voice.tags.join(' · ') : voice.notes || 'Chưa có tag'}</span></span>
                  <button type="button" className={`library-favorite${voice.favorite ? ' active' : ''}`} aria-label={`${voice.favorite ? 'Bỏ yêu thích' : 'Yêu thích'} ${voice.name}`} onClick={(event) => { event.stopPropagation(); favoriteMutation.mutate(voice) }}>{voice.favorite ? '★' : '☆'}</button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="library-detail-panel">
          {selected ? <VoiceDetail voice={selected} projectId={projectId} onRefresh={refresh} onMessage={setMessage} /> : <WorkspaceState title="Chọn một giọng" description="Metadata, preview và nơi sử dụng sẽ hiện ở đây." />}
        </section>
      </div>
    </div>
  )
}

function ImportVoicePanel({ onClose, onCreated }: { onClose: () => void; onCreated: (voice: LibraryVoice) => void }) {
  const [name, setName] = useState('')
  const [audioPath, setAudioPath] = useState('')
  const [language, setLanguage] = useState('vi')
  const [source, setSource] = useState<'imported' | 'cloned'>('cloned')
  const [referenceText, setReferenceText] = useState('')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const mutation = useMutation({ mutationFn: () => importLibraryAudio({ name, source, language, audio_path: audioPath, reference_text: referenceText, consent: { confirmed: consent, basis: 'owner', statement: 'Đã xác nhận trong Galaxy Studio', provenance: audioPath } }), onSuccess: onCreated, onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })
  return <section className="section-card library-composer"><div className="section-header compact"><div><span className="workspace-kicker">Thêm vào thư viện</span><h2 className="section-title">Nhập audio tham chiếu</h2></div><button className="btn quiet" type="button" onClick={onClose}>Đóng</button></div><div className="field-grid"><div className="field"><label>Tên giọng</label><input value={name} onChange={(event) => setName(event.target.value)} /></div><div className="field"><label>Loại</label><select value={source} onChange={(event) => setSource(event.target.value as 'imported' | 'cloned')}><option value="cloned">Giọng nhái</option><option value="imported">Giọng nhập</option></select></div><div className="field"><label>Ngôn ngữ</label><input value={language} onChange={(event) => setLanguage(event.target.value)} /></div><div className="field field-wide"><label>Audio mẫu</label><div className="input-action"><input value={audioPath} onChange={(event) => setAudioPath(event.target.value)} /><button className="btn" type="button" onClick={() => void pickAudioFile().then((path) => path && setAudioPath(path))}>Chọn</button></div></div><div className="field field-wide"><label>Transcript audio mẫu</label><textarea rows={2} value={referenceText} onChange={(event) => setReferenceText(event.target.value)} /></div></div>{source === 'cloned' && <label className="field-check consent-check"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> Tôi có quyền sử dụng giọng nói này</label>}{error && <div className="studio-error">{error}</div>}<button className="btn accent" type="button" disabled={mutation.isPending || !audioPath || !name} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Đang nhập...' : 'Lưu giọng'}</button></section>
}

function DesignVoicePanel({ onClose, onCreated }: { onClose: () => void; onCreated: (voice: LibraryVoice) => void }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('vi')
  const [instruction, setInstruction] = useState('')
  const [error, setError] = useState('')
  const mutation = useMutation({ mutationFn: () => createDesignedVoice({ name, language, instruction }), onSuccess: onCreated, onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })
  return <section className="section-card library-composer"><div className="section-header compact"><div><span className="workspace-kicker">Giọng tổng hợp</span><h2 className="section-title">Thiết kế giọng mới</h2></div><button className="btn quiet" type="button" onClick={onClose}>Đóng</button></div><div className="field-grid"><div className="field"><label>Tên giọng</label><input value={name} onChange={(event) => setName(event.target.value)} /></div><div className="field"><label>Ngôn ngữ</label><input value={language} onChange={(event) => setLanguage(event.target.value)} /></div><div className="field field-wide"><label>Mô tả giọng</label><textarea rows={3} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Ví dụ: nữ trẻ, ấm áp, giọng kể chậm, phát âm tiếng Việt rõ..." /></div></div>{error && <div className="studio-error">{error}</div>}<button className="btn accent" type="button" disabled={mutation.isPending || !name || !instruction} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Đang lưu...' : 'Lưu thiết kế'}</button></section>
}

function VoiceDetail({ voice, projectId, onRefresh, onMessage }: { voice: LibraryVoice; projectId: string; onRefresh: () => Promise<void>; onMessage: (value: string) => void }) {
  const [name, setName] = useState(voice.name)
  const [language, setLanguage] = useState(voice.language)
  const [tags, setTags] = useState(voice.tags.join(', '))
  const [notes, setNotes] = useState(voice.notes)
  useEffect(() => { setName(voice.name); setLanguage(voice.language); setTags(voice.tags.join(', ')); setNotes(voice.notes) }, [voice])
  const save = async () => { await updateLibraryVoice(voice.voice_id, { name, language, tags: tags.split(',').map((item) => item.trim()).filter(Boolean), notes }); await onRefresh(); onMessage('Đã lưu thông tin giọng.') }
  const exportVoice = async () => { const folder = await pickFolder(); if (!folder) return; const result = await exportLibraryVoice(voice.voice_id, `${folder}/${voice.name}.galaxyvoice`); onMessage(`Đã xuất: ${result.path}`) }
  const remove = async () => { if (!window.confirm(`Xóa giọng "${voice.name}"?`)) return; try { await deleteLibraryVoice(voice.voice_id); await onRefresh() } catch { if (window.confirm('Giọng đang được sử dụng. Vẫn xóa khỏi thư viện?')) { await deleteLibraryVoice(voice.voice_id, true); await onRefresh() } } }
  const stable = async () => { const path = await pickAudioFile(); if (!path) return; await setStableSample(voice.voice_id, path, voice.selection.reference_text); await onRefresh(); onMessage('Đã khóa audio này làm mẫu ổn định.') }
  return <div className="library-detail"><div className="library-detail-heading"><span className={`library-source-mark ${voice.source}`}>{SOURCE_LABELS[voice.source].slice(0, 1)}</span><div><span className="workspace-kicker">{SOURCE_LABELS[voice.source]} · phiên bản {voice.revision}</span><h2>{voice.name}</h2><p>{voice.capabilities.join(' · ') || 'Chỉ dùng với engine tương thích'}</p></div></div>{voice.preview_available ? <audio controls preload="none" src={voice.preview_url} /> : <div className="library-no-preview">Chưa có audio xem trước</div>}<div className="library-compatibility">{Object.entries(voice.compatibility).map(([key, supported]) => <span className={supported ? 'supported' : ''} key={key}>{key}: {supported ? 'Dùng được' : 'Không tương thích'}</span>)}</div><div className="field-grid"><div className="field"><label>Tên</label><input disabled={!voice.identity_editable} value={name} onChange={(event) => setName(event.target.value)} /></div><div className="field"><label>Ngôn ngữ</label><input disabled={!voice.identity_editable} value={language} onChange={(event) => setLanguage(event.target.value)} /></div><div className="field field-wide"><label>Tags, ngăn bằng dấu phẩy</label><input value={tags} onChange={(event) => setTags(event.target.value)} /></div><div className="field field-wide"><label>Ghi chú</label><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></div></div>{voice.source === 'cloned' && <div className={`library-consent ${voice.consent.confirmed ? 'confirmed' : ''}`}><strong>{voice.consent.confirmed ? 'Đã xác nhận quyền sử dụng' : 'Chưa có xác nhận quyền sử dụng'}</strong><span>{voice.consent.statement || 'Cập nhật consent trước khi dùng giọng ngoài phạm vi cá nhân.'}</span></div>}<div className="library-detail-actions"><button className="btn accent" type="button" onClick={() => void save()}>Lưu thay đổi</button>{voice.source !== 'system' && <button className="btn" type="button" onClick={() => void exportVoice()}>Xuất bundle</button>}{projectId && <button className="btn" type="button" onClick={() => void pinLibraryVoice(voice.voice_id, projectId).then(() => onMessage('Đã ghim snapshot giọng vào dự án.'))}>Ghim vào dự án</button>}{(voice.source === 'cloned' || voice.source === 'imported') && <button className="btn" type="button" onClick={() => void stable()}>Đổi mẫu ổn định</button>}{voice.deletable && <button className="btn danger" type="button" onClick={() => void remove()}>Xóa</button>}</div><small className="library-usage">Đang được tham chiếu tại {voice.usage_count} nơi.</small></div>
}

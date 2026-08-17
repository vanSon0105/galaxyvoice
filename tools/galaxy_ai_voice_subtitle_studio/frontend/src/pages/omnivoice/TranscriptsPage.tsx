import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addTranscript,
  clearTranscripts,
  deleteTranscript,
  fetchTranscripts,
} from '../../api/workspaces'

/** Local transcript history: search, add, delete, clear. */
export function TranscriptsPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [text, setText] = useState('')
  const [language, setLanguage] = useState('vi')
  const [error, setError] = useState('')

  const transcriptsQuery = useQuery({
    queryKey: ['transcripts', query],
    queryFn: () => fetchTranscripts(query),
  })

  const handleAdd = async () => {
    setError('')
    try {
      await addTranscript({ text, language })
      setText('')
      void queryClient.invalidateQueries({ queryKey: ['transcripts'] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const handleClear = async () => {
    if (!window.confirm('Xóa toàn bộ lịch sử transcripts?')) return
    await clearTranscripts()
    void queryClient.invalidateQueries({ queryKey: ['transcripts'] })
  }

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Thêm transcript</h2>
        <div className="field-grid">
          <div className="field">
            <label>Nội dung</label>
            <textarea
              className="srt-editor"
              rows={3}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <div className="field">
            <label>Ngôn ngữ</label>
            <input type="text" value={language} onChange={(event) => setLanguage(event.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <button className="btn accent" onClick={() => void handleAdd()}>
            Lưu transcript
          </button>
          {error && <span style={{ color: 'var(--color-danger)', fontSize: 12 }}>{error}</span>}
        </div>
      </section>

      <section className="section-card">
        <h2 className="section-title">Lịch sử</h2>
        <div className="field" style={{ maxWidth: 360 }}>
          <label>Tìm kiếm</label>
          <input type="text" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <div style={{ marginTop: 10 }}>
          {(transcriptsQuery.data ?? []).map((entry) => (
            <div className="transcript-row" key={entry.entry_id}>
              <div className="transcript-text" title={entry.text}>
                {entry.text}
              </div>
              <span className="archetype-tag">{entry.language}</span>
              <span style={{ color: 'var(--color-fg-subtle)', fontSize: 11 }}>
                {entry.created_at.slice(0, 16).replace('T', ' ')}
              </span>
              <button
                className="btn danger"
                onClick={() =>
                  void deleteTranscript(entry.entry_id).then(() =>
                    queryClient.invalidateQueries({ queryKey: ['transcripts'] }),
                  )
                }
              >
                Xóa
              </button>
            </div>
          ))}
          {(transcriptsQuery.data ?? []).length === 0 && (
            <div style={{ color: 'var(--color-fg-subtle)' }}>Chưa có transcript nào.</div>
          )}
        </div>
        {(transcriptsQuery.data ?? []).length > 0 && (
          <button className="btn danger" style={{ marginTop: 10 }} onClick={() => void handleClear()}>
            Xóa lịch sử
          </button>
        )}
      </section>
    </div>
  )
}

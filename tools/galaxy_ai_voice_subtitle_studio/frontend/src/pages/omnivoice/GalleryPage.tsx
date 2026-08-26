import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { fetchGallery, fetchGalleryCategories } from '../../api/workspaces'
import type { Archetype } from '../../api/workspaces'

/** Voice archetype gallery: search, category filter, paginated cards. */
export function GalleryPage() {
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [useCase, setUseCase] = useState('')
  const [language, setLanguage] = useState('')
  const [gender, setGender] = useState('')
  const [age, setAge] = useState('')
  const [pitch, setPitch] = useState('')
  const [style, setStyle] = useState('')
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  const categoriesQuery = useQuery({
    queryKey: ['gallery-categories'],
    queryFn: fetchGalleryCategories,
  })
  const galleryQuery = useQuery({
    queryKey: ['gallery', appliedQuery, useCase, language, gender, age, pitch, style, page],
    queryFn: () =>
      fetchGallery({
        query: appliedQuery,
        use_case: useCase,
        language,
        gender,
        age,
        pitch,
        style,
        page,
      }),
    placeholderData: keepPreviousData,
  })

  const total = galleryQuery.data?.total ?? 0
  const pageSize = galleryQuery.data?.page_size ?? 120
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const handleFilterChange = () => setPage(1)

  const handleArchetypeSelect = (item: Archetype) => {
    // Navigate to Studio with design mode and pre-fill from archetype
    const params = new URLSearchParams()
    params.set('mode', 'design')
    if (item.gender) params.set('gender', item.gender)
    if (item.age) params.set('age', item.age)
    if (item.pitch) params.set('pitch', item.pitch)
    if (item.accent) params.set('accent', item.accent)
    if (item.style) params.set('style', item.style)
    if (item.language) params.set('language', item.language)
    if (item.instruct) params.set('instruct', item.instruct)
    if (item.sample_text) params.set('sample', item.sample_text)
    navigate(`/voice?${params.toString()}`)
  }

  // Extract unique filter options from current results
  const items = galleryQuery.data?.items ?? []
  const languages = [...new Set(items.map((i) => i.language).filter(Boolean))].sort()
  const genders = [...new Set(items.map((i) => i.gender).filter(Boolean))].sort()
  const ages = [...new Set(items.map((i) => i.age).filter(Boolean))].sort()
  const pitches = [...new Set(items.map((i) => i.pitch).filter(Boolean))].sort()
  const styles = [...new Set(items.map((i) => i.style).filter(Boolean))].sort()

  return (
    <div>
      <section className="section-card">
        <h2 className="section-title">Thư viện giọng thiết kế</h2>
        <div className="field-grid">
          <div className="field">
            <label>Tìm kiếm</label>
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  setAppliedQuery(query.trim())
                  setPage(1)
                }
              }}
              placeholder="Tìm tên, đặc điểm, mục đích… (Enter để tìm)"
            />
          </div>
          <div className="field">
            <label>Mục đích sử dụng</label>
            <select
              value={useCase}
              onChange={(event) => {
                setUseCase(event.target.value)
                setPage(1)
              }}
            >
              <option value="">Tất cả</option>
              {(categoriesQuery.data ?? []).map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Ngôn ngữ</label>
            <select value={language} onChange={(event) => { setLanguage(event.target.value); handleFilterChange(); }}>
              <option value="">Tất cả</option>
              {languages.map((lang) => (
                <option key={lang} value={lang}>{lang}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Giới tính</label>
            <select value={gender} onChange={(event) => { setGender(event.target.value); handleFilterChange(); }}>
              <option value="">Tất cả</option>
              {genders.map((g) => (
                <option key={g} value={g}>{g === 'male' ? 'Nam' : g === 'female' ? 'Nữ' : g}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Độ tuổi</label>
            <select value={age} onChange={(event) => { setAge(event.target.value); handleFilterChange(); }}>
              <option value="">Tất cả</option>
              {ages.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Cao độ</label>
            <select value={pitch} onChange={(event) => { setPitch(event.target.value); handleFilterChange(); }}>
              <option value="">Tất cả</option>
              {pitches.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Phong cách</label>
            <select value={style} onChange={(event) => { setStyle(event.target.value); handleFilterChange(); }}>
              <option value="">Tất cả</option>
              {styles.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ color: 'var(--color-fg-subtle)', fontSize: 12, marginTop: 8 }}>
          {total} giọng — trang {page}/{pages}
        </div>
      </section>

      <div className="archetype-grid">
        {(galleryQuery.data?.items ?? []).map((item) => (
          <div
            className="archetype-card"
            key={item.archetype_id}
            onClick={() => handleArchetypeSelect(item)}
            style={{ cursor: 'pointer' }}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                handleArchetypeSelect(item)
              }
            }}
          >
            <div className="archetype-name">{item.name}</div>
            <div className="archetype-meta">
              {[item.gender, item.age, item.pitch, item.accent, item.style]
                .filter(Boolean)
                .join(' · ') || item.use_case}
            </div>
            <div className="archetype-instruct" title={item.instruct}>
              {item.instruct}
            </div>
            <div className="archetype-sample">{item.sample_text}</div>
            <div className="archetype-footer">
              <span className="archetype-tag">{item.use_case}</span>
              <span className="archetype-tag">{item.language}</span>
            </div>
            <div className="archetype-hint">Click để dùng trong Studio</div>
          </div>
        ))}
      </div>

      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'center' }}>
          <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Trước
          </button>
          <button className="btn" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Sau
          </button>
        </div>
      )}
    </div>
  )
}

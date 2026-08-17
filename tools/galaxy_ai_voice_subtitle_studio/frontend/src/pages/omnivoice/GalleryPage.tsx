import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { fetchGallery, fetchGalleryCategories } from '../../api/workspaces'

/** Voice archetype gallery: search, category filter, paginated cards. */
export function GalleryPage() {
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [useCase, setUseCase] = useState('')
  const [page, setPage] = useState(1)

  const categoriesQuery = useQuery({
    queryKey: ['gallery-categories'],
    queryFn: fetchGalleryCategories,
  })
  const galleryQuery = useQuery({
    queryKey: ['gallery', appliedQuery, useCase, page],
    queryFn: () => fetchGallery({ query: appliedQuery, use_case: useCase, page }),
    placeholderData: keepPreviousData,
  })

  const total = galleryQuery.data?.total ?? 0
  const pageSize = galleryQuery.data?.page_size ?? 120
  const pages = Math.max(1, Math.ceil(total / pageSize))

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
        </div>
        <div style={{ color: 'var(--color-fg-subtle)', fontSize: 12, marginTop: 8 }}>
          {total} giọng — trang {page}/{pages}
        </div>
      </section>

      <div className="archetype-grid">
        {(galleryQuery.data?.items ?? []).map((item) => (
          <div className="archetype-card" key={item.archetype_id}>
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

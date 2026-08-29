import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchExtensionCapabilities,
  type ExtensionCapability,
  type ExtensionCapabilityDisposition,
} from '../api/extensions'

const DISPOSITION_LABELS: Record<ExtensionCapabilityDisposition, string> = {
  extension: 'Tiện ích mở rộng',
  deferred: 'Tạm hoãn',
  optional_adapter: 'Bộ điều hợp tùy chọn',
  non_goal: 'Không phải mục tiêu',
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <dt>{title}</dt>
      <dd>
        <ul>
          {items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </dd>
    </div>
  )
}

function CapabilityRow({ capability }: { capability: ExtensionCapability }) {
  const [open, setOpen] = useState(false)

  return (
    <details
      className="extension-capability"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            setOpen((current) => !current)
          }
        }}
      >
        <span className="extension-capability-copy">
          <strong>{capability.label}</strong>
          <span>{capability.summary}</span>
        </span>
        <span className={`extension-disposition ${capability.disposition}`}>
          {DISPOSITION_LABELS[capability.disposition]}
        </span>
      </summary>
      <dl className="extension-capability-details">
        <div>
          <dt>Ranh giới</dt>
          <dd>{capability.boundary}</dd>
        </div>
        <DetailList title="Ràng buộc" items={capability.constraints} />
        <DetailList title="Xem xét lại khi" items={capability.revisit_triggers} />
      </dl>
    </details>
  )
}

export function ExtensionCapabilitiesPanel() {
  const capabilitiesQuery = useQuery({
    queryKey: ['extension-capabilities'],
    queryFn: fetchExtensionCapabilities,
  })

  return (
    <section className="section-card extension-capabilities" aria-labelledby="extension-capabilities-title">
      <h2 className="section-title" id="extension-capabilities-title">Tính năng mở rộng</h2>
      {capabilitiesQuery.isPending && (
        <p className="extension-capabilities-state" role="status">
          Đang tải danh mục tính năng mở rộng...
        </p>
      )}
      {capabilitiesQuery.isError && (
        <p className="extension-capabilities-state error" role="alert">
          Không thể tải danh mục tính năng mở rộng.
        </p>
      )}
      {capabilitiesQuery.data && (
        capabilitiesQuery.data.capabilities.length > 0 ? (
          <div className="extension-capability-list">
            {capabilitiesQuery.data.capabilities.map((capability) => (
              <CapabilityRow key={capability.capability_id} capability={capability} />
            ))}
          </div>
        ) : (
          <p className="extension-capabilities-state">Chưa có tính năng mở rộng.</p>
        )
      )}
    </section>
  )
}

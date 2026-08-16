import { useT } from '../i18n/useT'

interface PlaceholderPageProps {
  title: string
  phase: string
}

export function PlaceholderPage({ title, phase }: PlaceholderPageProps) {
  const t = useT()
  return (
    <div className="placeholder-page">
      <div className="placeholder-title">
        {title} — {phase}
      </div>
      <div>{t('placeholder.detail')}</div>
    </div>
  )
}

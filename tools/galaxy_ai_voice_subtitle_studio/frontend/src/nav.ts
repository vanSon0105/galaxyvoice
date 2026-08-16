/** Navigation single source of truth: one entry per workspace. */
export interface NavItem {
  id: string
  label: string
  route: string
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dubbing', label: 'Video Dubbing', route: '/dubbing' },
  { id: 'omnivoice', label: 'OmniVoice', route: '/omnivoice' },
  { id: 'voicestudio', label: 'VoiceStudio', route: '/voicestudio' },
  { id: 'editor', label: 'Dựng video', route: '/editor' },
  { id: 'separation', label: 'Tách âm thanh', route: '/separation' },
  { id: 'removal', label: 'Xóa phụ đề', route: '/removal' },
  { id: 'settings', label: 'Cài đặt', route: '/settings' },
]

export const DEFAULT_ROUTE = NAV_ITEMS[0].route

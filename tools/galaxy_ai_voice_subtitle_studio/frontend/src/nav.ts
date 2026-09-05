/** Navigation single source of truth: one entry per workspace. */
export interface NavItem {
  id: string
  label: string
  route: string
}

export interface VoiceNavItem extends NavItem {
  description: string
}

export const VOICE_NAV_ITEMS: VoiceNavItem[] = [
  { id: 'studio', label: 'Studio', route: '/voice', description: 'Tạo, thử và quản lý các bản đọc' },
  { id: 'batch', label: 'Batch', route: '/voice/batch', description: 'Xử lý nhiều nội dung theo hàng đợi' },
  { id: 'library', label: 'Thư viện giọng', route: '/voice/library', description: 'Giọng đã lưu và mẫu thiết kế' },
]

export const NAV_ITEMS: NavItem[] = [
  { id: 'voice', label: 'Voice', route: '/voice' },
  { id: 'video-subtitles', label: 'Phụ đề video', route: '/dubbing' },
  { id: 'editor', label: 'Dựng video', route: '/editor' },
  { id: 'separation', label: 'Tách âm thanh', route: '/separation' },
  { id: 'settings', label: 'Cài đặt', route: '/settings' },
]

export const DEFAULT_ROUTE = NAV_ITEMS[0].route

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
  { id: 'transcripts', label: 'Transcripts', route: '/voice/transcripts', description: 'Bản ghi có thể tìm kiếm và chỉnh sửa' },
  { id: 'longform', label: 'Truyện & Sách nói', route: '/voice/longform', description: 'Nội dung dài, nhiều chương và nhiều giọng' },
  { id: 'dubbing', label: 'Dubbing', route: '/voice/dubbing', description: 'Lồng tiếng theo phân đoạn và thời gian' },
]

export const NAV_ITEMS: NavItem[] = [
  { id: 'voice', label: 'Voice', route: '/voice' },
  { id: 'video-subtitles', label: 'Phụ đề video', route: '/dubbing' },
  { id: 'editor', label: 'Dựng video', route: '/editor' },
  { id: 'separation', label: 'Tách âm thanh', route: '/separation' },
  { id: 'removal', label: 'Xóa phụ đề', route: '/removal' },
  { id: 'settings', label: 'Cài đặt', route: '/settings' },
]

export const DEFAULT_ROUTE = NAV_ITEMS[0].route

import { useQuery, useQueryClient } from '@tanstack/react-query'

import { deleteProfile, fetchProfiles } from '../../api/omnivoice'
import { WorkspaceLoading, WorkspaceState } from '../../components/WorkspaceState'

/** Saved voice-profile library with delete. */
export function ProfilesPage() {
  const queryClient = useQueryClient()
  const profilesQuery = useQuery({ queryKey: ['omnivoice-profiles'], queryFn: fetchProfiles })

  if (profilesQuery.isPending) return <WorkspaceLoading label="Đang tải thư viện giọng..." />
  if (profilesQuery.isError || !profilesQuery.data) {
    return (
      <WorkspaceState
        title="Không tải được thư viện giọng"
        description="Kiểm tra runtime local rồi thử làm mới dữ liệu."
        tone="error"
        action={<button className="btn" onClick={() => void profilesQuery.refetch()}>Thử lại</button>}
      />
    )
  }

  const handleDelete = async (profileId: string, name: string) => {
    if (!window.confirm(`Xóa profile giọng "${name}"?`)) return
    try {
      await deleteProfile(profileId)
      void queryClient.invalidateQueries({ queryKey: ['omnivoice-profiles'] })
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <section className="section-card">
      <h2 className="section-title">Thư viện giọng</h2>
      {profilesQuery.data.length === 0 ? (
        <WorkspaceState
          title="Chưa có giọng đã lưu"
          description={'Tạo một giọng trong Studio, rồi chọn "Lưu thành profile mới" để dùng lại ở mọi workflow.'}
        />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Tên</th>
              <th>Ngôn ngữ</th>
              <th>Tạo lúc</th>
              <th>Nội dung mẫu</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {profilesQuery.data.map((profile) => (
              <tr key={profile.profile_id}>
                <td>{profile.display_name}</td>
                <td>{profile.language}</td>
                <td>{profile.created_at.slice(0, 19).replace('T', ' ')}</td>
                <td className="truncate-cell">{profile.reference_text}</td>
                <td>
                  <button
                    className="btn danger"
                    onClick={() => void handleDelete(profile.profile_id, profile.display_name)}
                  >
                    Xóa
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

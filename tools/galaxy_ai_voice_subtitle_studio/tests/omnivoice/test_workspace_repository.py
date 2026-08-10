from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.omnivoice.workspaces.common.repository import WorkspaceRepository


class WorkspaceRepositoryTests(unittest.TestCase):
    def test_projects_round_trip_per_workspace_and_keep_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = WorkspaceRepository(Path(temp_dir) / "workspace.json")

            project = repository.save_project(
                workspace="stories",
                name="Chuyến đi",
                payload={"script": "Lan: Xin chào", "cast": {"Lan": "lan-vi"}},
            )
            updated = repository.save_project(
                workspace="stories",
                name="Chuyến đi mới",
                payload={"script": "Lan: Đi thôi", "cast": {"Lan": "lan-vi"}},
                project_id=project.project_id,
            )
            repository.save_project(
                workspace="audiobook",
                name="Sách khác",
                payload={"script": "# Chương 1"},
            )

            self.assertEqual(updated.project_id, project.project_id)
            self.assertEqual(len(repository.list_projects("stories")), 1)
            self.assertEqual(repository.get_project(project.project_id), updated)
            self.assertEqual(updated.payload["script"], "Lan: Đi thôi")

    def test_history_can_be_searched_starred_deleted_and_limited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = WorkspaceRepository(Path(temp_dir) / "workspace.json", history_limit=2)
            first = repository.add_history(
                workspace="voice-clone",
                title="Giọng Lan",
                summary="Xin chào Việt Nam",
                artifact_path="lan.wav",
                metadata={"profile_id": "lan"},
            )
            repository.add_history(
                workspace="stories",
                title="Truyện ngắn",
                summary="Ngày xửa ngày xưa",
                artifact_path="story.wav",
            )

            starred = repository.set_history_starred(first.history_id, True)
            self.assertTrue(starred.starred)
            self.assertEqual(repository.search_history("Việt Nam")[0].history_id, first.history_id)

            repository.add_history(
                workspace="audiobook",
                title="Sách nói",
                summary="Chương cuối",
                artifact_path="book.m4b",
            )
            self.assertEqual(len(repository.list_history()), 2)
            self.assertIn(first.history_id, {item.history_id for item in repository.list_history()})
            repository.delete_history(first.history_id)
            self.assertNotIn(first.history_id, {item.history_id for item in repository.list_history()})

    def test_repository_never_serializes_secret_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workspace.json"
            repository = WorkspaceRepository(path)

            project = repository.save_project(
                workspace="dubbing",
                name="An toàn",
                payload={
                    "source": "video.mp4",
                    "api_key": "must-not-be-saved",
                    "nested": {"openai_api_key": "also-secret", "language": "vi"},
                },
            )

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("must-not-be-saved", raw)
            self.assertNotIn("also-secret", raw)
            self.assertNotIn("api_key", project.payload)
            self.assertEqual(project.payload["nested"], {"language": "vi"})


if __name__ == "__main__":
    unittest.main()

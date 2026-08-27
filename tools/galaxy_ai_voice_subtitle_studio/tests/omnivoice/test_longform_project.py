from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.omnivoice.workspaces.longform_project import (
    LongformProject,
    LongformProjectRepository,
    LongformRevisionConflict,
)


class LongformProjectTests(unittest.TestCase):
    def test_repository_persists_one_revisioned_model_for_story_and_audiobook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = LongformProjectRepository(Path(directory) / "longform_projects.json")
            project = LongformProject.create(
                name="Truyện thử",
                kind="stories",
                source="Lan: Xin chào",
                document={"chapters": ["Mở đầu"], "items": [{"item_id": "one"}]},
                options={"api_key": "secret", "device": "auto"},
            )
            saved = repository.save(project, expected_revision=0)

            self.assertEqual(saved.revision, 1)
            self.assertEqual(repository.list("stories")[0].item_count, 1)
            self.assertNotIn("api_key", repository.get(saved.project_id).options)

            updated = repository.save(
                saved.evolved(kind="audiobook", stage="cast"),
                expected_revision=1,
            )
            self.assertEqual(updated.revision, 2)
            self.assertEqual(repository.list("audiobook")[0].chapter_count, 1)
            with self.assertRaises(LongformRevisionConflict):
                repository.save(saved.evolved(name="stale"), expected_revision=1)


if __name__ == "__main__":
    unittest.main()

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
                galaxy_project_id="active-project-1",
                name="Truyện thử",
                kind="stories",
                source="Lan: Xin chào",
                document={"chapters": ["Mở đầu"], "items": [{"item_id": "one"}]},
                options={"api_key": "secret", "device": "auto"},
            )
            saved = repository.save(project, expected_revision=0)

            self.assertEqual(saved.revision, 1)
            self.assertEqual(saved.galaxy_project_id, "active-project-1")
            self.assertEqual(
                repository.list("stories", galaxy_project_id="active-project-1")[0].project_id,
                saved.project_id,
            )
            self.assertEqual(repository.list(galaxy_project_id="other-project"), ())
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

    def test_resume_advances_checkpoint_without_discarding_completed_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = LongformProjectRepository(Path(directory) / "longform_projects.json")
            project = LongformProject.create(
                name="Resume test",
                kind="stories",
                source="One. Two.",
                document={"items": [{"item_id": "one"}, {"item_id": "two"}]},
            )
            saved = repository.save(project, expected_revision=0)
            checkpointed = repository.save(
                saved.evolved(
                    stage="render",
                    last_result={"completed_item_ids": ["one"]},
                ),
                expected_revision=saved.revision,
            )

            resumed = repository.resume(
                saved.project_id,
                completed_item_ids=("one", "two"),
                expected_revision=checkpointed.revision,
            )

            self.assertEqual(resumed.last_result["completed_item_ids"], ["one", "two"])
            with self.assertRaisesRegex(ValueError, "discard"):
                repository.resume(
                    saved.project_id,
                    completed_item_ids=("two", "three"),
                    expected_revision=resumed.revision,
                )


if __name__ == "__main__":
    unittest.main()

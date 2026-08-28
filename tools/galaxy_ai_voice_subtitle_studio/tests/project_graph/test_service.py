from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.project_graph.models import AssetReference, HandoffRequest, NodeRequest
from app.project_graph.service import ProjectGraphService


class ProjectGraphServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_project_graph_")
        self.root = Path(self._tmp.name)
        self.service = ProjectGraphService(self.root / "project_graph.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_handoff_keeps_references_and_reversible_provenance(self) -> None:
        source = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="transcripts",
                owner_id="transcript-1",
                label="Phỏng vấn gốc",
                revision=4,
                assets=(
                    AssetReference(
                        asset_id="asset-srt",
                        role="source_subtitle",
                        path_hint="D:/media/source.srt",
                        ownership="linked",
                        fingerprint="sha256:abc",
                    ),
                ),
            )
        )

        handoff = self.service.create_handoff(
            HandoffRequest(
                project_id="project-1",
                source_node_id=source.node_id,
                target_workspace="dubbing",
                input_asset_ids=("asset-srt",),
                payload={"api_key": "must-not-leak", "transcript_id": "transcript-1"},
            )
        )

        self.assertEqual(handoff.status, "pending")
        self.assertEqual(handoff.source_route, "/voice/transcripts")
        self.assertEqual(handoff.target_route, "/voice/dubbing")
        self.assertEqual(handoff.source_revision, 4)
        self.assertEqual(handoff.input_asset_ids, ("asset-srt",))
        self.assertNotIn("api_key", handoff.payload)

        opened = self.service.open_handoff(handoff.handoff_id)
        returned = self.service.return_handoff(
            handoff.handoff_id,
            target_node=NodeRequest(
                project_id="project-1",
                workspace="dubbing",
                owner_id="dub-1",
                label="Bản lồng tiếng",
                revision=2,
                assets=(
                    AssetReference(
                        asset_id="asset-dub",
                        role="dubbed_audio",
                        path_hint="generated/dub.wav",
                        ownership="generated",
                        derived_from=("asset-srt",),
                    ),
                ),
            ),
            output_asset_ids=("asset-dub",),
        )

        self.assertEqual(opened.status, "opened")
        self.assertEqual(returned.status, "returned")
        self.assertEqual(returned.output_asset_ids, ("asset-dub",))
        self.assertEqual(returned.target_node_id, "dubbing:dub-1")
        self.assertEqual(len(self.service.get_graph("project-1").nodes), 2)

    def test_rejects_cross_project_and_unsupported_handoffs(self) -> None:
        source = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="studio",
                owner_id="take-1",
                label="Take 1",
            )
        )
        with self.assertRaisesRegex(ValueError, "không được hỗ trợ"):
            self.service.create_handoff(
                HandoffRequest(
                    project_id="project-1",
                    source_node_id=source.node_id,
                    target_workspace="subtitle_removal",
                )
            )
        with self.assertRaisesRegex(ValueError, "không thuộc"):
            self.service.create_handoff(
                HandoffRequest(
                    project_id="project-2",
                    source_node_id=source.node_id,
                    target_workspace="editor",
                )
            )

    def test_reopening_returned_handoff_does_not_erase_return_record(self) -> None:
        source = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="editor",
                owner_id="edit-1",
                label="Bản dựng",
            )
        )
        handoff = self.service.create_handoff(
            HandoffRequest(
                project_id="project-1",
                source_node_id=source.node_id,
                target_workspace="separation",
            )
        )
        self.service.open_handoff(handoff.handoff_id)
        self.service.return_handoff(handoff.handoff_id)

        with self.assertRaisesRegex(ValueError, "đã hoàn tất"):
            self.service.open_handoff(handoff.handoff_id)

    def test_return_rejects_output_asset_from_another_project(self) -> None:
        source = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="editor",
                owner_id="edit-1",
                label="Editor output",
            )
        )
        handoff = self.service.create_handoff(
            HandoffRequest(
                project_id="project-1",
                source_node_id=source.node_id,
                target_workspace="separation",
            )
        )
        self.service.upsert_node(
            NodeRequest(
                project_id="project-2",
                workspace="separation",
                owner_id="separation-2",
                label="Foreign stems",
                assets=(
                    AssetReference(
                        asset_id="foreign-output",
                        role="audio_stem",
                        ownership="generated",
                    ),
                ),
            )
        )

        with self.assertRaisesRegex(ValueError, "graph"):
            self.service.return_handoff(
                handoff.handoff_id,
                output_asset_ids=("foreign-output",),
            )

    def test_return_links_an_existing_target_node_and_its_outputs(self) -> None:
        source = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="transcripts",
                owner_id="transcript-1",
                label="Transcript",
            )
        )
        handoff = self.service.create_handoff(
            HandoffRequest(
                project_id="project-1",
                source_node_id=source.node_id,
                target_workspace="dubbing",
            )
        )
        target = self.service.upsert_node(
            NodeRequest(
                project_id="project-1",
                workspace="dubbing",
                owner_id="dubbing-1",
                label="Dub",
                assets=(
                    AssetReference(
                        asset_id="dub-output",
                        role="dubbed_audio",
                        ownership="generated",
                    ),
                ),
            )
        )

        returned = self.service.return_handoff(
            handoff.handoff_id,
            target_node_id=target.node_id,
            output_asset_ids=("dub-output",),
        )

        self.assertEqual(returned.target_node_id, target.node_id)
        self.assertEqual(returned.output_asset_ids, ("dub-output",))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.server.main import create_app


class ProjectGraphApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_project_graph_api_")
        self.root = Path(self._tmp.name)
        self.client = TestClient(create_app(config_path=self.root / "config.json"))

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def test_node_handoff_open_return_lifecycle(self) -> None:
        node = self.client.post(
            "/api/project-graph/nodes",
            json={
                "project_id": "project-1",
                "workspace": "studio",
                "owner_id": "take-1",
                "label": "Take 1",
                "revision": 1,
                "assets": [
                    {
                        "asset_id": "audio-1",
                        "role": "voice_audio",
                        "path_hint": "D:/output/take.wav",
                        "ownership": "generated",
                    }
                ],
            },
        )
        self.assertEqual(node.status_code, 200, node.text)

        created = self.client.post(
            "/api/project-graph/handoffs",
            json={
                "project_id": "project-1",
                "source_node_id": node.json()["node_id"],
                "target_workspace": "editor",
                "input_asset_ids": ["audio-1"],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        handoff_id = created.json()["handoff_id"]

        opened = self.client.post(f"/api/project-graph/handoffs/{handoff_id}/open", json={})
        self.assertEqual(opened.json()["status"], "opened")
        target = self.client.post(
            "/api/project-graph/nodes",
            json={
                "project_id": "project-1",
                "workspace": "editor",
                "owner_id": "edit-1",
                "label": "Edit 1",
                "assets": [
                    {
                        "asset_id": "video-1",
                        "role": "edited_video",
                        "ownership": "generated",
                    }
                ],
            },
        )
        self.assertEqual(target.status_code, 200, target.text)
        returned = self.client.post(
            f"/api/project-graph/handoffs/{handoff_id}/return",
            json={
                "target_node_id": target.json()["node_id"],
                "output_asset_ids": ["video-1"],
            },
        )
        self.assertEqual(returned.json()["status"], "returned")
        self.assertEqual(returned.json()["target_node_id"], "editor:edit-1")
        self.assertEqual(returned.json()["output_asset_ids"], ["video-1"])

        graph = self.client.get("/api/project-graph/projects/project-1")
        self.assertEqual(graph.status_code, 200)
        self.assertEqual(len(graph.json()["nodes"]), 2)
        self.assertEqual(len(graph.json()["handoffs"]), 1)

    def test_workspace_catalog_exposes_routes_and_targets(self) -> None:
        response = self.client.get("/api/project-graph/workspaces")
        self.assertEqual(response.status_code, 200)
        catalog = {item["id"]: item for item in response.json()}
        self.assertEqual(catalog["studio"]["route"], "/voice")
        self.assertIn("editor", catalog["studio"]["targets"])
        self.assertIn("subtitle_removal", catalog["editor"]["targets"])


if __name__ == "__main__":
    unittest.main()

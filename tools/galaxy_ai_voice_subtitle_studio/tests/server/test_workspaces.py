"""Shared Voice project, history, and gallery router tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.server.main import create_app


class WorkspacesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_workspaces_")
        self.tmp = Path(self._tmp.name)
        self.client = TestClient(create_app(config_path=self.tmp / "config.json"))

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def test_project_save_list_get_delete(self) -> None:
        saved = self.client.post(
            "/api/workspaces/projects",
            json={"workspace": "stories", "name": "Truyện thử", "payload": {"api_key": "sk-secret"}},
        )
        self.assertEqual(saved.status_code, 200)
        body = saved.json()
        self.assertEqual(body["workspace"], "stories")
        self.assertNotIn("api_key", body["payload"])

        listed = self.client.get("/api/workspaces/projects", params={"workspace": "stories"})
        self.assertEqual(len(listed.json()), 1)

        fetched = self.client.get(f"/api/workspaces/projects/{body['project_id']}")
        self.assertEqual(fetched.json()["name"], "Truyện thử")

        updated = self.client.post(
            "/api/workspaces/projects",
            json={
                "workspace": "stories",
                "name": "Truyện sửa",
                "project_id": body["project_id"],
                "payload": {},
            },
        )
        self.assertEqual(updated.json()["name"], "Truyện sửa")
        self.assertEqual(len(self.client.get("/api/workspaces/projects").json()), 1)

        self.assertEqual(
            self.client.delete(f"/api/workspaces/projects/{body['project_id']}").status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/workspaces/projects").json(), [])

    def test_history_add_star_search_clear(self) -> None:
        added = self.client.post(
            "/api/workspaces/history",
            json={"workspace": "audiobook", "title": "Chương 1", "summary": "bắt đầu", "artifact_path": ""},
        )
        self.assertEqual(added.status_code, 200)
        history_id = added.json()["history_id"]

        starred = self.client.patch(
            f"/api/workspaces/history/{history_id}/starred",
            json={"starred": True},
        )
        self.assertTrue(starred.json()["starred"])

        search = self.client.get(
            "/api/workspaces/history",
            params={"query": "bắt đầu", "starred_only": True},
        )
        self.assertEqual(len(search.json()), 1)

        self.client.delete("/api/workspaces/history", params={"workspace": "audiobook"})
        self.assertEqual(self.client.get("/api/workspaces/history").json(), [])

    def test_gallery_returns_paginated_archetypes(self) -> None:
        response = self.client.get("/api/workspaces/gallery", params={"page": 1})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body["total"], 0)
        self.assertEqual(len(body["items"]), min(body["total"], 120))
        self.assertIn("instruct", body["items"][0])
        categories = self.client.get("/api/workspaces/gallery/categories").json()
        self.assertIsInstance(categories, list)

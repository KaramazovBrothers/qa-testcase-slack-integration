"""Screenshots attached to cases: one per set, overridable per case.

The picture shows the tester what the method looks like on the frontend, so it
must reach Slack right after the case body: after the body message, before the
extra instructions and before the WebView APK.
"""

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import case_images, main, storage
from app.current_user import get_current_user_id

# A real 120x90 PNG (Pillow rejects a hand-assembled one when decoding), so
# the thumbnail path is exercised rather than its fallback.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAA30lEQVR4nO3QMQ0AIADAMMASnlCLKFSwqzWwZHOfO/hvBQ2M7hgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0aPxgMjHwIZJO8apQAAAABJRU5ErkJggg=="
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


class CaseImageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)

    def saved_set(self, title="Case"):
        response = self.client.post("/api/tasks/save", json={
            "client_key": "draft-1",
            "title": "Task",
            "settings": {"fields": {"region": "TR"}},
            "generation_key": "gen-1",
            "cases": [{"client_key": "case-1", "title": title, "text": "Body",
                       "status": "Not tested"}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task"]["id"]
        set_id = response.json()["set"]["id"]
        case_id = response.json()["set"]["cases"][0]["id"]
        return task_id, set_id, case_id

    def upload(self, url, content=PNG, name="shot.png", media="image/png"):
        return self.client.post(url, files={"file": (name, io.BytesIO(content), media)})

    def test_set_picture_applies_to_every_case(self):
        task_id, set_id, case_id = self.saved_set()
        uploaded = self.upload(f"/api/case-images/sets/{set_id}/default")
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        payload = self.client.get(f"/api/tasks/{task_id}/sets/{set_id}").json()
        self.assertEqual(payload["default_image"]["filename"], "shot.png")
        case = payload["cases"][0]
        self.assertEqual(case["image"]["id"], uploaded.json()["id"])
        self.assertEqual(case["image_source"], "set")

    def test_reupload_replaces_the_set_picture_in_place(self):
        _, set_id, _ = self.saved_set()
        first = self.upload(f"/api/case-images/sets/{set_id}/default").json()
        second = self.upload(f"/api/case-images/sets/{set_id}/default",
                             content=JPEG, name="new.jpeg", media="image/jpeg").json()
        self.assertEqual(first["id"], second["id"])
        # The extension follows the real content, not the browser-supplied name.
        self.assertEqual(second["filename"], "new.jpg")
        self.assertEqual(second["media_type"], "image/jpeg")

    def test_case_override_wins_and_can_be_reset(self):
        task_id, set_id, case_id = self.saved_set()
        self.upload(f"/api/case-images/sets/{set_id}/default")
        own = self.upload(f"/api/case-images/cases/{case_id}", name="own.png")
        self.assertEqual(own.status_code, 201, own.text)

        case = self.client.get(f"/api/tasks/{task_id}/sets/{set_id}").json()["cases"][0]
        self.assertEqual(case["image"]["filename"], "own.png")
        self.assertEqual(case["image_source"], "case")

        self.assertEqual(self.client.delete(f"/api/case-images/cases/{case_id}").status_code, 204)
        case = self.client.get(f"/api/tasks/{task_id}/sets/{set_id}").json()["cases"][0]
        self.assertEqual(case["image"]["filename"], "shot.png")
        self.assertEqual(case["image_source"], "set")

    def test_reuploading_the_set_keeps_case_overrides(self):
        task_id, set_id, case_id = self.saved_set()
        self.upload(f"/api/case-images/sets/{set_id}/default")
        self.upload(f"/api/case-images/cases/{case_id}", name="own.png")
        self.upload(f"/api/case-images/sets/{set_id}/default", name="v2.png")
        case = self.client.get(f"/api/tasks/{task_id}/sets/{set_id}").json()["cases"][0]
        self.assertEqual(case["image_source"], "case")
        self.assertEqual(case["image"]["filename"], "own.png")

    def test_image_is_served_with_safe_headers(self):
        _, set_id, _ = self.saved_set()
        image_id = self.upload(f"/api/case-images/sets/{set_id}/default").json()["id"]
        response = self.client.get(f"/api/case-images/{image_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, PNG)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_non_image_or_empty_upload_is_refused(self):
        _, set_id, _ = self.saved_set()
        not_image = self.upload(f"/api/case-images/sets/{set_id}/default",
                                content=b"<html>not an image</html>", name="x.png")
        self.assertEqual(not_image.status_code, 422)
        empty = self.upload(f"/api/case-images/sets/{set_id}/default", content=b"")
        self.assertEqual(empty.status_code, 422)

    def test_unknown_set_and_case_are_not_found(self):
        self.saved_set()
        self.assertEqual(self.upload("/api/case-images/sets/999/default").status_code, 404)
        self.assertEqual(self.upload("/api/case-images/cases/999").status_code, 404)

    def test_sniffing_rejects_disguised_files(self):
        self.assertIsNone(case_images._sniff(b"%PDF-1.4"))
        self.assertEqual(case_images._sniff(PNG), "image/png")
        self.assertEqual(case_images._sniff(JPEG), "image/jpeg")

    def test_filename_is_reduced_to_a_safe_name(self):
        name = case_images.safe_filename("../../etc/pass wd.png", "image/png")
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".png"))


class SendOrderTests(unittest.TestCase):
    """The picture must arrive right after the case body message."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)
        storage.save_slack_token(storage.LOCAL_USER_ID, "xoxp-test")

    def test_picture_is_uploaded_after_the_body_and_before_comments(self):
        saved = self.client.post("/api/tasks/save", json={
            "client_key": "draft-1", "title": "T",
            "settings": {"fields": {"region": "TR"}},
            "generation_key": "gen-1",
            "cases": [{"client_key": "c1", "title": "Case", "text": "Body",
                       "status": "Not tested"}],
        }).json()
        set_id = saved["set"]["id"]
        case_id = saved["set"]["cases"][0]["id"]
        image = self.client.post(
            f"/api/case-images/sets/{set_id}/default",
            files={"file": ("shot.png", io.BytesIO(PNG), "image/png")},
        ).json()

        calls = []

        async def fake_post(token, channel, text, thread_ts=None):
            calls.append(("post", text))
            return {"ok": True, "ts": f"1700000000.00000{len(calls)}", "channel": channel}

        uploaded_bytes = {}

        async def fake_upload(token, channel, filename, content, *, thread_ts=None,
                              initial_comment=""):
            calls.append(("upload", filename))
            uploaded_bytes["content"] = content
            return {"ok": True, "files": [{"id": "F1"}]}

        with patch.object(main, "post_message", side_effect=fake_post), \
                patch.object(main, "upload_file", side_effect=fake_upload), \
                patch.object(main.slack_history, "resolve_permalink",
                             side_effect=lambda *a, **k: {"send_id": 1}):
            response = self.client.post("/slack/send-cases", json={
                "region": "TR", "operation": "deposit", "mention_users": [],
                "cases": [{"case_ids": [case_id], "title": "Case", "text": "Body",
                           "comment": "Extra", "image_id": image["id"]}],
            })
        self.assertEqual(response.status_code, 200, response.text)
        kinds = [kind for kind, _ in calls]
        self.assertEqual(kinds, ["post", "post", "upload", "post"])
        # Slack gets the small copy, so a screenshot cannot fill the thread.
        self.assertEqual(calls[2][1], f"method-{image['id']}.png")
        from PIL import Image
        with Image.open(io.BytesIO(uploaded_bytes["content"])) as sent:
            self.assertLessEqual(max(sent.size), 50)

    def test_unknown_image_is_rejected_before_sending(self):
        with patch.object(main, "post_message") as send:
            response = self.client.post("/slack/send-cases", json={
                "region": "TR", "operation": "deposit", "mention_users": [],
                "cases": [{"case_ids": [], "title": "Case", "text": "Body",
                           "image_id": 999}],
            })
        self.assertEqual(response.status_code, 404)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()

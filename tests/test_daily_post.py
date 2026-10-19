import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "daily_post.py"
SPEC = importlib.util.spec_from_file_location("daily_post", MODULE_PATH)
daily_post = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_post)


class DailyPostTests(unittest.TestCase):
    def test_prepared_photo_gets_openai_caption_without_replacing_image(self):
        day = date(2026, 10, 21)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            posts = root / "posts"
            posts.mkdir()
            image = posts / "2026-10-21.jpg"
            image.write_bytes(b"prepared photo")
            manifest_path = posts / "2026-10-21.json"
            manifest_path.write_text(json.dumps({
                "date": "2026-10-21", "due_at_utc": "2026-10-21T03:00:00.000Z",
                "scene": "flower market", "caption": None,
                "image": "posts/2026-10-21.jpg", "buffer_post_id": None,
            }), encoding="utf-8")
            fake_openai = SimpleNamespace(OpenAI=lambda api_key: object())
            with patch.object(daily_post, "ROOT", root), patch.object(daily_post, "POSTS_DIR", posts), \
                 patch.dict(sys.modules, {"openai": fake_openai}), \
                 patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
                 patch.object(daily_post, "generate_caption", return_value="今日行花市。\n\n#AI創作"):
                daily_post.generate(day)
            self.assertEqual(image.read_bytes(), b"prepared photo")
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["caption"], "今日行花市。\n\n#AI創作")

    def test_prepared_photo_cannot_schedule_without_caption(self):
        day = date(2026, 10, 21)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            posts = root / "posts"
            posts.mkdir()
            (posts / "2026-10-21.jpg").write_bytes(b"prepared photo")
            (posts / "2026-10-21.json").write_text(json.dumps({
                "date": "2026-10-21", "due_at_utc": "2026-10-21T03:00:00.000Z",
                "scene": "flower market", "caption": None,
                "image": "posts/2026-10-21.jpg", "buffer_post_id": None,
            }), encoding="utf-8")
            with patch.object(daily_post, "ROOT", root), patch.object(daily_post, "POSTS_DIR", posts):
                with self.assertRaisesRegex(RuntimeError, "caption is missing"):
                    daily_post.schedule(day)

    def test_caption_falls_back_only_for_model_access(self):
        class AccessError(Exception):
            status_code = 403
            code = "model_not_found"

        class Response:
            output_text = "今朝嘆杯咖啡，慢慢開始新一日。"

        class Client:
            class responses:
                @staticmethod
                def create(**kwargs):
                    if kwargs["model"] == "gpt-4o-mini":
                        raise AccessError("No model access")
                    return Response()

        with patch.dict("os.environ", {"OPENAI_TEXT_MODEL": "gpt-4o-mini,gpt-4.1-mini"}):
            self.assertEqual(
                daily_post.generate_caption(Client(), "a cafe"),
                "今朝嘆杯咖啡，慢慢開始新一日。\n\n#AI創作",
            )

    def test_hong_kong_11_is_utc_03(self):
        self.assertEqual(
            daily_post.iso_utc(daily_post.publication_time(date(2026, 10, 20))),
            "2026-10-20T03:00:00.000Z",
        )

    def test_only_exact_instagram_handle_matches(self):
        responses = [
            {"account": {"organizations": [{"id": "org-1", "name": "A"}]}},
            {"channels": [
                {"id": "wrong", "name": "ai_andy_lee", "service": "instagram"},
                {"id": "near", "name": "kellykellyhk3extra", "service": "instagram"},
                {"id": "right", "name": "kellykellyhk3", "service": "instagram"},
            ]},
        ]
        with patch.object(daily_post, "graphql", side_effect=responses):
            org, channel = daily_post.find_target_channel("key")
        self.assertEqual((org, channel["id"]), ("org-1", "right"))

    def test_wrong_buffer_account_fails_closed(self):
        responses = [
            {"account": {"organizations": [{"id": "org-1", "name": "A"}]}},
            {"channels": [{"id": "wrong", "name": "ai_andy_lee", "service": "instagram"}]},
        ]
        with patch.object(daily_post, "graphql", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "found 0"):
                daily_post.find_target_channel("key")

    def test_disconnected_channel_fails_closed(self):
        responses = [
            {"account": {"organizations": [{"id": "org-1", "name": "A"}]}},
            {"channels": [{
                "id": "right", "name": "kellykellyhk3", "service": "instagram", "isDisconnected": True
            }]},
        ]
        with patch.object(daily_post, "graphql", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "disconnected"):
                daily_post.find_target_channel("key")

    def test_existing_post_blocks_different_caption(self):
        data = {"posts": {"edges": [{"node": {
            "id": "post-1", "text": "Other caption", "dueAt": "2026-10-20T03:00:00.000Z"
        }}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        with patch.object(daily_post, "graphql", return_value=data):
            with self.assertRaisesRegex(RuntimeError, "occupies this 11:00 slot"):
                daily_post.existing_post("key", "org", "channel", "2026-10-20T03:00:00.000Z", "Our caption")

    def test_existing_post_reuses_matching_caption(self):
        data = {"posts": {"edges": [{"node": {
            "id": "post-1", "text": "Our caption", "dueAt": "2026-10-20T03:00:00.000Z"
        }}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        with patch.object(daily_post, "graphql", return_value=data):
            self.assertEqual(
                daily_post.existing_post("key", "org", "channel", "2026-10-20T03:00:00.000Z", "Our caption"),
                "post-1",
            )

    def test_failed_buffer_post_requires_review(self):
        data = {"posts": {"edges": [{"node": {
            "id": "post-1", "text": "Our caption", "dueAt": "2026-10-20T03:00:00.000Z", "status": "error"
        }}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        with patch.object(daily_post, "graphql", return_value=data):
            with self.assertRaisesRegex(RuntimeError, "has an error"):
                daily_post.existing_post("key", "org", "channel", "2026-10-20T03:00:00.000Z", "Our caption")

    def test_create_post_has_ai_disclosure_and_exact_schedule(self):
        data = {"createPost": {"post": {
            "id": "post-1", "channelId": "channel", "dueAt": "2026-10-20T03:00:00.000Z"
        }}}
        with patch.object(daily_post, "graphql", return_value=data) as api:
            self.assertEqual(
                daily_post.create_post("key", "channel", "Hi", "2026-10-20T03:00:00.000Z", "https://example.com/a.jpg"),
                "post-1",
            )
        query = api.call_args.args[1]
        self.assertIn("mode: customScheduled", query)
        self.assertIn("isAiGenerated: true", query)
        self.assertIn("shouldShareToFeed: true", query)


if __name__ == "__main__":
    unittest.main()

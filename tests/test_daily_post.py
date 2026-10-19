import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "daily_post.py"
SPEC = importlib.util.spec_from_file_location("daily_post", MODULE_PATH)
daily_post = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_post)


class DailyPostTests(unittest.TestCase):
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

import unittest
from unittest.mock import patch

from forum_feed_poster.main import (
    Settings,
    build_discord_payload,
    extract_items,
    format_forum_post,
)


class FeedPosterTests(unittest.TestCase):
    def test_extracts_and_formats_items(self) -> None:
        items = extract_items(
            {
                "items": [
                    {
                        "title": "Trade completed",
                        "summary": "Team A sent Player X to Team B.",
                        "url": "https://example.com/event/123",
                    }
                ]
            }
        )

        content = format_forum_post("league-123", "Ironbound Feed", items, max_items=10)

        self.assertIn("## Ironbound Feed", content)
        self.assertIn("**Trade completed**", content)
        self.assertIn("[details](https://example.com/event/123)", content)

    @patch.dict(
        "os.environ",
        {
            "LEAGUE_ID": "league-123",
            "LEAGUE_FEED_URL": "https://example.com/{league_id}",
            "DRY_RUN": "true",
        },
        clear=True,
    )
    def test_dry_run_does_not_require_webhook(self) -> None:
        settings = Settings.from_environment()

        self.assertTrue(settings.dry_run)
        self.assertIsNone(settings.discord_webhook_url)

    @patch.dict(
        "os.environ",
        {
            "LEAGUE_ID": "league-123",
            "LEAGUE_FEED_URL": "https://example.com/{league_id}",
            "FORUM_POST_TITLE": "Ironbound Feed",
            "DRY_RUN": "true",
        },
        clear=True,
    )
    def test_payload_creates_a_forum_thread(self) -> None:
        settings = Settings.from_environment()
        payload = build_discord_payload(settings, "Feed content")

        self.assertEqual(payload["thread_name"], "Ironbound Feed")
        self.assertEqual(payload["content"], "Feed content")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})


if __name__ == "__main__":
    unittest.main()

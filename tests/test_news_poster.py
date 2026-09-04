import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from forum_feed_poster.classify import classify_story, tag_ids_for_names
from forum_feed_poster.config import Settings
from forum_feed_poster.dedupe import ActiveThread, DedupeStore, canonicalize_url
from forum_feed_poster.discord import (
    SUPPRESS_EMBEDS,
    ImageAttachment,
    build_payload,
    generate_story_card,
    team_emoji_markup,
)
from forum_feed_poster.list_tags import _team_emoji_ids
from forum_feed_poster.models import NewsSource, NewsStory
from forum_feed_poster.presentation import PlayerDirectory, present_story
from forum_feed_poster.sources import parse_feed
from forum_feed_poster.teams import TEAMS_BY_ABBREVIATION


def story(**overrides):
    values = {
        "source": "Test Source",
        "title": "Bears rule D'Andre Swift out with an ankle injury",
        "summary": "Swift did not practice and will miss Sunday's game.",
        "url": "https://example.com/swift-injury",
        "published_at": datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc),
        "image_url": "https://example.com/swift.jpg",
        "categories": (),
    }
    values.update(overrides)
    return NewsStory(**values)


class SourceTests(unittest.TestCase):
    def test_parses_rss_story_and_relative_image(self) -> None:
        rss = """<?xml version="1.0"?>
        <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
          <channel><title>Player News</title><item>
            <title>Player signs extension</title>
            <link>https://news.example.com/story/1</link>
            <description>Fantasy impact summary.</description>
            <pubDate>Thu, 03 Sep 2026 15:00:00 +0000</pubDate>
            <content:encoded><![CDATA[<img src="/images/player.jpg" />]]></content:encoded>
          </item></channel>
        </rss>"""

        stories = parse_feed(NewsSource("Example", "https://news.example.com/rss"), rss)

        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0].summary, "Fantasy impact summary.")
        self.assertEqual(stories[0].image_url, "https://news.example.com/images/player.jpg")


class ClassificationTests(unittest.TestCase):
    def test_applies_breaking_and_injury_tags(self) -> None:
        tags = classify_story(
            story(
                title="Breaking: Bears rule D'Andre Swift out with injury",
                summary="Swift will miss Sunday's game with an ankle injury.",
            )
        )

        self.assertEqual(tags, ["Breaking", "Injury"])

    def test_maps_tag_names_to_discord_ids(self) -> None:
        ids = tag_ids_for_names(
            ["Breaking", "Injury"],
            {"🚨 Breaking": "111", "📰 Injury": "222"},
        )

        self.assertEqual(ids, ["111", "222"])

    def test_practice_report_and_injury_can_both_apply(self) -> None:
        tags = classify_story(
            story(title="Zay Flowers returns to practice Thursday after injury")
        )

        self.assertEqual(tags, ["Practice Report", "Injury"])

    def test_backfield_analysis_can_also_use_depth_chart_tag(self) -> None:
        tags = classify_story(
            story(
                title="Beat Writer Confirms That You Shouldn't Bother Drafting RJ Harvey",
                summary=(
                    "The Broncos' backfield outlook has Harvey occupying the same role "
                    "even if Dobbins goes down again. This is fantasy commentary."
                ),
            )
        )

        self.assertEqual(tags, ["Depth Chart", "Fantasy Analysis"])

    def test_contract_signing_uses_contract_tag(self) -> None:
        tags = classify_story(
            story(
                title="Michael Wilson signs three-year extension",
                summary="Wilson agreed to a new contract with Arizona.",
            )
        )

        self.assertEqual(tags, ["Breaking", "Contract"])

    def test_suspension_uses_legal_trouble_tag(self) -> None:
        tags = classify_story(
            story(
                title="League suspends player for four games",
                summary="The suspension followed a disciplinary review.",
            )
        )

        self.assertEqual(tags, ["Breaking", "Legal Trouble"])

    def test_expanded_tags_can_overlap(self) -> None:
        tags = classify_story(
            story(
                title="Dynasty start/sit: Rookie remains questionable in new scheme",
                summary="The rookie is a game-time decision with long-term value.",
            )
        )

        self.assertEqual(
            tags,
            [
                "Game Status",
                "Coaching / Scheme",
                "Rookie / Prospect",
                "Fantasy Analysis",
                "Start/Sit",
            ],
        )


class DedupeTests(unittest.TestCase):
    def test_removes_tracking_parameters_from_urls(self) -> None:
        canonical = canonicalize_url(
            "https://Example.com/story/?utm_source=x&player=swift#section"
        )

        self.assertEqual(canonical, "https://example.com/story?player=swift")

    def test_detects_same_story_from_different_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            store = DedupeStore(Path(temp_directory) / "seen.json", 168, 0.62)
            store.remember(
                story(
                    source="Source A",
                    title="D'Andre Swift ruled out by Bears with ankle injury",
                    summary="Chicago ruled out running back D'Andre Swift due to his ankle injury.",
                )
            )
            duplicate = story(
                source="Source B",
                title="Bears rule D'Andre Swift out for Sunday",
                summary="Running back D'Andre Swift will miss the game because of an ankle injury.",
                url="https://another.example.com/news/987",
            )

            self.assertTrue(store.is_duplicate(duplicate))

    def test_detects_current_extension_story_across_feed_wording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            store = DedupeStore(Path(temp_directory) / "seen.json", 168, 0.62)
            store.remember(
                story(
                    source="Draft Sharks",
                    title="Michael Wilson's Extension Another Reason To Believe In His 2026 Role",
                    summary="The Cardinals and Michael Wilson agreed to a three-year, $75 million extension.",
                )
            )
            duplicate = story(
                source="RotoWire",
                title="Michael Wilson: Lands three-year extension",
                summary="Wilson agreed to a three-year, $75 million contract with the Cardinals.",
                url="https://another.example.com/michael-wilson-extension",
            )

            self.assertTrue(store.is_duplicate(duplicate))

    def test_finds_same_player_thread_only_inside_merge_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            now = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
            store = DedupeStore(Path(temp_directory) / "seen.json", 168, 0.62)
            store.remember_thread(
                ActiveThread(
                    player_key="00-0040730",
                    player_name="RJ Harvey",
                    thread_id="123",
                    headline="[DEN] RJ Harvey update",
                    opened_at=(now - timedelta(minutes=59)).isoformat(),
                    updated_at=now.isoformat(),
                    tag_names=["Depth Chart"],
                    source_urls=["https://example.com/one"],
                )
            )

            self.assertIsNotNone(
                store.find_active_thread("00-0040730", 60, now=now)
            )
            self.assertIsNone(
                store.find_active_thread(
                    "00-0040730", 60, now=now + timedelta(minutes=2)
                )
            )

    def test_saves_thread_state_without_breaking_old_story_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "seen.json"
            path.write_text(
                json.dumps({"version": 1, "stories": []}), encoding="utf-8"
            )
            store = DedupeStore(path, 168, 0.62)
            store.remember_thread(
                ActiveThread(
                    player_key="player",
                    player_name="Player",
                    thread_id="thread",
                    headline="Headline",
                    opened_at=datetime.now(timezone.utc).isoformat(),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    tag_names=["General News"],
                    source_urls=[],
                )
            )
            store.save()

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["active_threads"][0]["thread_id"], "thread")


class DiscordTests(unittest.TestCase):
    def test_builds_image_backed_forum_payload_with_tags(self) -> None:
        attachment = ImageAttachment("swift.jpg", "image/jpeg", b"image")

        payload = build_payload(story(), ["111", "222"], attachment)

        self.assertEqual(payload["applied_tags"], ["111", "222"])
        self.assertEqual(payload["attachments"][0]["filename"], "swift.jpg")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["flags"], SUPPRESS_EMBEDS)
        self.assertIn("Read the full story", payload["content"])

    def test_generates_png_fallback_for_gallery_mode(self) -> None:
        attachment = generate_story_card(story(image_url=None))

        self.assertEqual(attachment.content_type, "image/png")
        self.assertTrue(attachment.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(attachment.data), 1_000)

    def test_formats_existing_team_emoji_for_message_body(self) -> None:
        emoji = team_emoji_markup(
            TEAMS_BY_ABBREVIATION["DEN"], {"DEN": "1540346172743618610"}
        )

        self.assertEqual(emoji, "<:broncos:1540346172743618610>")


class PresentationTests(unittest.TestCase):
    def test_creates_requested_player_first_rj_harvey_headline(self) -> None:
        players_csv = """gsis_id,display_name,common_first_name,first_name,last_name,football_name,headshot,last_season,latest_team
00-0040730,RJ Harvey,RJ,Robert,Harvey,RJ,https://images.example/rj.png,2026,DEN
00-0038120,J.K. Dobbins,J.K.,J'Kaylin,Dobbins,J.K.,https://images.example/jk.png,2026,DEN
00-0099999,Drew Stevens,Drew,Drew,Stevens,Drew,https://images.example/drew.png,2026,NE
"""
        directory = PlayerDirectory.from_csv(players_csv, current_year=2026)
        presentation = present_story(
            story(
                title="Beat Writer Confirms That You Shouldn't Bother Drafting RJ Harvey",
                summary=(
                    "Zac Stevens broke down the Broncos' backfield outlook and said "
                    "Harvey has the same role even if Dobbins goes down again."
                ),
            ),
            directory,
        )

        self.assertEqual(
            presentation.thread_title,
            "[DEN] RJ Harvey Unlikely to Become Workhorse if Dobbins Misses Time",
        )
        self.assertEqual(presentation.player.display_name, "RJ Harvey")


class SettingsTests(unittest.TestCase):
    @patch.dict("os.environ", {"DRY_RUN": "true"}, clear=True)
    def test_defaults_to_public_player_news_feeds(self) -> None:
        settings = Settings.from_environment()

        self.assertTrue(settings.dry_run)
        self.assertGreaterEqual(len(settings.news_sources), 2)
        self.assertIsNone(settings.discord_webhook_url)

    @patch.dict(
        "os.environ",
        {"DRY_RUN": "false", "DISCORD_WEBHOOK_URL": "https://example.com/webhook"},
        clear=True,
    )
    def test_live_mode_requires_forum_tag_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "DISCORD_TAG_IDS_JSON"):
            Settings.from_environment()


class DiscordMetadataTests(unittest.TestCase):
    def test_maps_existing_team_emoji_names_to_abbreviations(self) -> None:
        mapping = _team_emoji_ids(
            [
                {"id": "111", "name": "broncos", "available": True},
                {"id": "222", "name": "49rs", "available": True},
                {"id": "333", "name": "forge", "available": True},
                {"id": "444", "name": "bears", "available": False},
            ]
        )

        self.assertEqual(mapping, {"DEN": "111", "SF": "222"})


if __name__ == "__main__":
    unittest.main()

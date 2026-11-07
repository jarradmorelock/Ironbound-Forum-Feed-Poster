"""Regression coverage for player-specific news headline attribution."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from forum_feed_poster.models import NewsStory
from forum_feed_poster.presentation import PlayerDirectory, PlayerProfile, present_story


def profile(key: str, first: str, last: str) -> PlayerProfile:
    name = f"{first} {last}"
    return PlayerProfile(
        key=key,
        display_name=name,
        first_name=first,
        last_name=last,
        team="HOU",
        headshot_url=None,
        aliases=(name.lower(),),
    )


class HeadlineAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = PlayerDirectory(
            (
                profile("marks", "Woody", "Marks"),
                profile("montgomery", "David", "Montgomery"),
            )
        )

    def story(self, title: str, summary: str) -> NewsStory:
        return NewsStory(
            source="RotoWire",
            title=title,
            summary=summary,
            url="https://example.com/story",
            published_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        )

    def test_marks_workload_not_mistaken_for_montgomery_absence(self) -> None:
        story = self.story(
            "Woody Marks: Set for RB1 work",
            "With David Montgomery (groin) again ruled out for Week 9, "
            "Marks is expected to remain the Texans' clear RB1 for Sunday's "
            "game against the Chargers.",
        )
        presentation = present_story(story, self.players)
        self.assertEqual(presentation.player.display_name, "Woody Marks")
        self.assertEqual(
            presentation.headline,
            "Woody Marks Set for Lead Role With Montgomery Out",
        )
        self.assertNotIn("Marks Ruled Out", presentation.thread_title)

    def test_real_out_report_still_generates_out_headline(self) -> None:
        story = self.story(
            "David Montgomery: Ruled out",
            "David Montgomery (groin) has been ruled out for Week 9. "
            "Woody Marks will start in his place.",
        )
        self.assertEqual(
            present_story(story, self.players).headline,
            "David Montgomery Ruled Out for Week 9",
        )

    def test_player_named_after_other_players_out_status_is_not_out(self) -> None:
        story = self.story(
            "Woody Marks: Backfield leader",
            "David Montgomery is ruled out for Week 9, and Woody Marks "
            "should get the lion's share of the carries.",
        )
        headline = present_story(story, self.players).headline
        self.assertNotIn("Marks Ruled Out", headline)

    def test_player_questionable_headline_is_attributed_correctly(self) -> None:
        story = self.story(
            "Woody Marks: Questionable for Week 9",
            "Woody Marks is questionable for Week 9. "
            "David Montgomery was ruled out.",
        )
        self.assertEqual(
            present_story(story, self.players).headline,
            "Woody Marks Questionable for Week 9",
        )

    def test_not_ruled_out_is_not_rewritten_as_confirmed_out(self) -> None:
        story = self.story(
            "Woody Marks: Not ruled out",
            "Woody Marks has not been ruled out for Week 9.",
        )
        headline = present_story(story, self.players).headline
        self.assertNotEqual(headline, "Woody Marks Ruled Out for Week 9")

    def test_could_be_ruled_out_remains_conditional(self) -> None:
        story = self.story(
            "Woody Marks: Could be ruled out",
            "Woody Marks could be ruled out for Week 9.",
        )
        headline = present_story(story, self.players).headline
        self.assertNotEqual(headline, "Woody Marks Ruled Out for Week 9")

    def test_expected_to_play_not_confused_with_teammate_out(self) -> None:
        story = self.story(
            "Woody Marks: Expected to play",
            "With David Montgomery ruled out for Week 9, "
            "Woody Marks is expected to play Sunday.",
        )
        self.assertEqual(
            present_story(story, self.players).headline,
            "Woody Marks Expected to Play Week 9",
        )


if __name__ == "__main__":
    unittest.main()

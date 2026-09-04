# Ironbound Forum Feed Poster

An image-first NFL player-news collector for the Ironbound Fantasy Football Discord Forum. It reads public fantasy-football news feeds, maps each story to Forum tags, avoids likely duplicates, and creates one image-backed Forum thread per story so Discord Gallery view has a thumbnail.

This repository is separate from the transaction-ledger project and does not collect league transactions or roster activity.

## Initial news sources

The default configuration uses two public player-news RSS feeds:

- [Draft Sharks Shark Bites](https://www.draftsharks.com/rss/shark-bites)
- [RotoWire NFL player news](https://www.rotowire.com/rss/news.php?sport=NFL)

Draft Sharks includes player-specific fantasy context and an image in its feed. RotoWire provides a second player-news source, allowing the duplicate detector to suppress two outlets reporting the same underlying event.

Direct X/Twitter collection is not enabled. X API access requires a developer account, credentials, and paid usage credits. It can be added later as an optional source. In practice, the fantasy RSS feeds frequently attribute breaking reports to reporters such as Adam Schefter while adding fantasy context.

## How a run works

1. Fetch every configured RSS/Atom feed.
2. Normalize and combine recent stories.
3. Reject stories already seen by canonical URL, normalized title, or fuzzy title/summary similarity.
4. Classify each story into the Forum's existing tag taxonomy.
5. Use the feed image or the article's Open Graph image; generate an Ironbound headline card when neither is available.
6. Upload the image as a real Discord attachment and create one Forum thread per story.
7. Save successfully posted story fingerprints in the GitHub Actions cache for seven days by default.

Only the newest three eligible stories are posted per run by default. Every post receives either its source image or a generated PNG headline card, preserving the intended Gallery layout.

## Current tag mapping

The built-in classifier targets the tags already present in the Forum:

- `Breaking`
- `Injury`
- `Practice Report`
- `NFL Moves`
- `Depth Chart`
- `Waiver Watch`
- `Fantasy Analysis`
- `General News`
- `Contract`
- `Legal Trouble`

A story can receive every relevant category, up to Discord's five-tag-per-post limit. For
example, a player-role article can receive both `Depth Chart` and `Fantasy Analysis`, while
an availability update can receive both `Practice Report` and `Injury`. Discord requires
tag IDs—not tag names—when a webhook creates the post.

### Obtain the Forum tag IDs

The existing bot can read the IDs without changing the channel. Enable Discord Developer Mode, copy the Forum channel ID, and run:

```bash
export DISCORD_BOT_TOKEN='your bot token'
export DISCORD_FORUM_CHANNEL_ID='your Forum channel ID'
python -m forum_feed_poster.list_tags
```

Do not paste the bot token into GitHub issues, Discord, or this repository. The helper prints JSON shaped like:

```json
{
  "Breaking": "123456789012345678",
  "Injury": "234567890123456789",
  "Practice Report": "345678901234567890"
}
```

The helper prints two mappings. Copy the first into the GitHub Actions repository variable
`DISCORD_TAG_IDS_JSON`. Copy the second into `DISCORD_TEAM_EMOJI_IDS_JSON`; it maps the
server's existing NFL team emojis to standard team abbreviations, without including unrelated
server emojis. Emoji are optional in the Forum-tag JSON keys; the matcher ignores them.

`Contract` covers new signings, extensions, restructures, franchise tags, and holdouts. `Legal Trouble` covers suspensions, discipline, arrests, charges, investigations, and similar off-field events. `NFL Moves` remains focused on trades, releases, waivers, activations, and other roster movement.

## Configuration

Add `DISCORD_WEBHOOK_URL` as a GitHub Actions **secret**. Everything else below is non-sensitive and can be stored as an Actions **variable**. Live mode requires the tag-ID mapping so the automation cannot accidentally create untagged posts.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DISCORD_TAG_IDS_JSON` | `{}` | Maps Forum tag names to Discord tag IDs |
| `DISCORD_TEAM_EMOJI_IDS_JSON` | `{}` | Maps NFL team abbreviations to existing server emoji IDs |
| `NEWS_FEEDS_JSON` | Built-in sources | Optional JSON list of `{ "name", "url" }` feeds |
| `MAX_POSTS_PER_RUN` | `3` | Live-post safety cap, from 1–10 |
| `MAX_STORY_AGE_HOURS` | `36` | Ignores old feed entries |
| `DEDUPE_WINDOW_HOURS` | `168` | Keeps seven days of story history |
| `DEDUPE_SIMILARITY` | `0.62` | Fuzzy duplicate threshold |
| `DRY_RUN` | `true` | Prints candidate payloads without posting or saving history |

Example custom source configuration:

```json
[
  {"name": "Draft Sharks", "url": "https://www.draftsharks.com/rss/shark-bites"},
  {"name": "RotoWire", "url": "https://www.rotowire.com/rss/news.php?sport=NFL"},
  {"name": "ESPN NFL", "url": "https://www.espn.com/espn/rss/nfl/news"}
]
```

## Local dry run

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
python -m forum_feed_poster
```

The dry-run output includes the suggested tags, source image URL, downloaded image size, and exact Discord payload. It never calls the webhook or changes duplicate history.

## GitHub Actions rollout

1. Add the webhook secret and tag-ID variable under **Settings → Secrets and variables → Actions**.
2. Open **Actions → Post Discord Forum feed → Run workflow**.
3. Leave **Dry run** enabled and review the candidate stories.
4. Run again with dry run disabled to create the first Gallery posts.
5. After verifying the posts, uncomment the 30-minute `schedule` trigger in the workflow.

The workflow carries `.state/seen.json` between runs using the GitHub Actions cache. This is intentionally lightweight: it substantially reduces repeats, including near-identical reports from different outlets, but cannot guarantee perfect semantic deduplication.

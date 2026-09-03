# Ironbound Forum Feed Poster

A small Python automation that fetches a league feed, turns it into a Discord-friendly digest, and creates a post in an existing Discord Forum channel through a webhook.

This repository is intentionally separate from the transaction-ledger project. The first version is provider-neutral and expects a simple JSON feed, so a Sleeper- or league-specific adapter can be added once the exact source payload is settled.

## What it does

1. Fetches JSON from `LEAGUE_FEED_URL`.
2. Formats the newest feed items as Discord Markdown.
3. Creates one Forum post by sending `content` and `thread_name` to the existing webhook.
4. Skips posting when the feed contains no items.

The GitHub Actions workflow is manual by default and starts in dry-run mode. This prevents accidental or duplicate Forum posts while the feed source and posting schedule are being tested.

## Repository layout

```text
.
├── .github/workflows/post-forum-feed.yml
├── forum_feed_poster/
│   ├── __init__.py
│   ├── __main__.py
│   └── main.py
├── tests/test_main.py
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Feed format

The feed endpoint may return a JSON list directly or an object containing an `items`, `events`, or `feed` list.

```json
{
  "items": [
    {
      "title": "Trade completed",
      "summary": "Team A sent Player X to Team B.",
      "url": "https://example.com/league/event/123",
      "timestamp": "2026-09-03T14:30:00Z"
    }
  ]
}
```

The formatter also accepts common alternatives such as `name`, `type`, `description`, `message`, `details`, and `link`. Unknown fields are ignored.

## Configuration

The application reads configuration from environment variables. Nothing sensitive is committed.

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | Live posts only | Existing Discord Forum webhook URL |
| `LEAGUE_ID` | Yes | League identifier used in the post and feed URL |
| `LEAGUE_FEED_URL` | Yes | JSON endpoint; may contain a `{league_id}` placeholder |
| `FEED_API_TOKEN` | No | Bearer token for a protected feed endpoint |
| `FORUM_POST_TITLE` | No | Thread title; defaults to `League Feed — YYYY-MM-DD` |
| `MAX_FEED_ITEMS` | No | Maximum items per post; defaults to `10` |
| `DRY_RUN` | No | Prints the Discord payload instead of sending it |

For GitHub Actions, create these repository secrets:

- `DISCORD_WEBHOOK_URL`
- `LEAGUE_ID`
- `LEAGUE_FEED_URL`
- `FEED_API_TOKEN` only if the source requires it

Optional non-sensitive repository variables are `FORUM_POST_TITLE` and `MAX_FEED_ITEMS`.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
python -m forum_feed_poster
```

Keep `DRY_RUN=true` until the fetched data and formatted payload look correct.

## Run with GitHub Actions

Open **Actions → Post Discord Forum feed → Run workflow**. Leave **Dry run** enabled for the first run. When the output looks right, run it again with dry run disabled.

After the desired cadence is known, add a `schedule` trigger to `.github/workflows/post-forum-feed.yml`. The workflow is deliberately unscheduled at this stage because each live run creates a new Forum thread.

## Current scope

- One feed request per run
- One Forum thread per non-empty run
- Basic Discord Markdown formatting
- No database, state store, or duplicate detection yet

Those pieces can be added when the exact feed provider and posting behavior are confirmed.

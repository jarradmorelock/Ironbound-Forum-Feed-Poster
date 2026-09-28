# Ironbound News Ledger

This branch stores the durable accepted-story ledger for the Discord player-news system.

- `ledger/events.jsonl` is append-only logical history. Each line is one accepted Discord story/update.
- Records contain normalized RSS/feed evidence and Discord/editorial metadata, not full article text.
- The main application owns source collection, player resolution, classification, and deduplication.
- Editorial Desk is a read-only consumer of this branch.

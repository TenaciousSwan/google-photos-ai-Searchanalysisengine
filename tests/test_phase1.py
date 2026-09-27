import pytest
from pathlib import Path
from unittest.mock import patch

from backend.app.pipeline.sanitizer import sanitizer
from backend.app.pipeline.ingestion import (
    PlayStoreScraperAdapter,
    AppStoreScraperAdapter,
    RedditAdapter,
    GoogleHelpForumAdapter,
    IngestionPipelineManager
)
from backend.app.core.database import DatabaseManager

def test_sanitizer_pii_removal():
    """Verify regex scrubbing of sensitive personal identifiers."""
    raw = "My name is John Doe, SSN 123-45-6789, email john.doe@example.com, phone 555-123-4567. Can't find my photo!"
    scrubbed, author, is_valid, reason = sanitizer.sanitize(raw, "John Doe")

    assert is_valid is True
    assert "[REDACTED_SSN]" in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "john.doe@example.com" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed
    assert author.startswith("usr_")

def test_sanitizer_quality_filtering():
    """Verify rejection of spam, empty reviews, and excessive emoji strings."""
    # Too short
    _, _, valid_short, reason_short = sanitizer.sanitize("Too short")
    assert valid_short is False
    assert "Too short" in reason_short

    # Pure emojis
    _, _, valid_emoji, reason_emoji = sanitizer.sanitize("😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡😡")
    assert valid_emoji is False
    assert "emoji" in reason_emoji.lower()

    # Valid review
    _, _, valid_ok, _ = sanitizer.sanitize("I spent two hours looking for that cafe picture from Paris last year.")
    assert valid_ok is True

def test_scraper_adapters_fixtures():
    """Verify all 4 adapters parse and return standardized dictionaries from fixtures."""
    play = PlayStoreScraperAdapter().scrape(limit=10, use_fixtures=True)
    assert len(play) > 0
    assert play[0]["source"] == "play_store"
    assert "user_text" in play[0]

    app = AppStoreScraperAdapter().scrape(limit=10, use_fixtures=True)
    assert len(app) > 0
    assert app[0]["source"] == "app_store"

    reddit = RedditAdapter().scrape(limit=10, use_fixtures=True)
    assert len(reddit) > 0
    assert reddit[0]["source"] == "reddit"

    help_f = GoogleHelpForumAdapter().scrape(limit=10, use_fixtures=True)
    assert len(help_f) > 0
    assert help_f[0]["source"] == "help_forum"

def test_ingestion_pipeline_and_deduplication(tmp_path):
    """
    Test end-to-end ingestion:
      1. Ingests records into temporary test database.
      2. Verifies records exist in raw_conversations table.
      3. Verifies ingestion checkpoints updated.
      4. Second ingestion run skips duplicates cleanly.
    """
    test_db = tmp_path / "test_ingest.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with patch("backend.app.pipeline.ingestion.db_manager", db):
        manager = IngestionPipelineManager()
        # First Run
        result1 = manager.run_ingestion(limit_per_source=5, use_fixtures=True)
        assert result1["total_inserted"] > 0
        assert result1["duplicates_skipped"] == 0

        # Check DB count
        with db.session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]
            assert count == result1["total_inserted"]

            # Check Checkpoint
            checkpoints = conn.execute("SELECT COUNT(*) FROM ingestion_checkpoints").fetchone()[0]
            assert checkpoints >= 1

        # Second Run (Exact same data -> 100% duplicate skip)
        result2 = manager.run_ingestion(limit_per_source=5, use_fixtures=True)
        assert result2["total_inserted"] == 0
        assert result2["duplicates_skipped"] == result1["total_inserted"]

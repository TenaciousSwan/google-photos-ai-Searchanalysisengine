import json
import logging
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests

from backend.app.core.config import settings, RAW_FIXTURES_DIR
from backend.app.models.schemas import RawConversation
from backend.app.pipeline.sanitizer import sanitizer
from backend.app.services.orchestrator import orchestrator
from backend.app.core.database import db_manager

logger = logging.getLogger(__name__)

class BaseScraperAdapter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    def scrape(self, limit: int = 20, use_fixtures: bool = False) -> List[Dict[str, Any]]:
        pass

    def load_fixture_records(self, source_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        fixture_file = RAW_FIXTURES_DIR / "sample_reviews.json"
        if not fixture_file.exists():
            return []
        try:
            with open(fixture_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if source_filter:
                    return [r for r in data if r.get("source") == source_filter]
                return data
        except Exception as e:
            logger.error(f"Error loading fixture: {e}")
            return []

class PlayStoreScraperAdapter(BaseScraperAdapter):
    @property
    def source_name(self) -> str:
        return "play_store"

    def scrape(self, limit: int = 20, use_fixtures: bool = False) -> List[Dict[str, Any]]:
        if use_fixtures:
            return self.load_fixture_records("play_store")[:limit]

        try:
            from google_play_scraper import reviews, Sort
            # Fetch up to `limit` reviews using newest sort
            fetch_count = limit if limit > 20 else 50
            result, _ = reviews(
                'com.google.android.apps.photos',
                lang='en',
                country='us',
                sort=Sort.NEWEST,
                count=fetch_count,
                filter_score_with=None
            )
            parsed = []
            for r in result:
                text = r.get("content", "")
                if not text or len(text.strip()) < 15:
                    continue
                parsed.append({
                    "id": f"play_{r.get('reviewId')}",
                    "source": "play_store",
                    "source_url": f"https://play.google.com/store/apps/details?id=com.google.android.apps.photos&reviewId={r.get('reviewId')}",
                    "post_date": r.get("at", datetime.utcnow()).isoformat() if hasattr(r.get("at"), "isoformat") else str(r.get("at")),
                    "platform": "android",
                    "author": r.get("userName"),
                    "rating": r.get("score"),
                    "user_text": text,
                    "engagement": r.get("thumbsUpCount", 0)
                })
                if len(parsed) >= limit:
                    break
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Play Store live scraping encountered error: {e}. Falling back to fixture.")

        return self.load_fixture_records("play_store")[:limit]

class AppStoreScraperAdapter(BaseScraperAdapter):
    @property
    def source_name(self) -> str:
        return "app_store"

    def scrape(self, limit: int = 20, use_fixtures: bool = False) -> List[Dict[str, Any]]:
        if use_fixtures:
            return self.load_fixture_records("app_store")[:limit]

        try:
            # Apple iTunes Customer Reviews RSS Feed for Google Photos (App ID: 962194608)
            parsed = []
            max_pages = min(10, (limit // 50) + 1)
            for page in range(1, max_pages + 1):
                url = f"https://itunes.apple.com/us/rss/customerreviews/page={page}/id=962194608/sortBy=mostRecent/json"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                res = requests.get(url, headers=headers, timeout=5.0)
                if res.status_code != 200:
                    break
                data = res.json()
                entries = data.get("feed", {}).get("entry", [])
                for entry in entries:
                    content = entry.get("content", {}).get("label", "")
                    title = entry.get("title", {}).get("label", "")
                    full_text = f"{title}. {content}".strip()
                    if len(full_text) < 15:
                        continue
                    review_id = entry.get("id", {}).get("label", str(time.time()))
                    parsed.append({
                        "id": f"app_{review_id}",
                        "source": "app_store",
                        "source_url": f"https://apps.apple.com/app/google-photos/id962194608?review={review_id}",
                        "post_date": datetime.utcnow().isoformat(),
                        "platform": "ios",
                        "author": entry.get("author", {}).get("name", {}).get("label", "Apple User"),
                        "rating": int(entry.get("im:rating", {}).get("label", 3)),
                        "user_text": full_text,
                        "engagement": 0
                    })
                    if len(parsed) >= limit:
                        break
                if len(parsed) >= limit:
                    break
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"App Store live scraping encountered error: {e}. Falling back to fixture.")

        return self.load_fixture_records("app_store")[:limit]

class RedditAdapter(BaseScraperAdapter):
    @property
    def source_name(self) -> str:
        return "reddit"

    def scrape(self, limit: int = 20, use_fixtures: bool = False) -> List[Dict[str, Any]]:
        if use_fixtures:
            return self.load_fixture_records("reddit")[:limit]

        try:
            import xml.etree.ElementTree as ET
            import re
            parsed = []
            queries = ["search", "find+photo", "lost+photo", "faces+album", "retrieval"]
            for q in queries:
                url = f"https://www.reddit.com/r/googlephotos/search.rss?q={q}&restrict_sr=1&sort=new"
                headers = {"User-Agent": "script:googlephotos.discovery:v1.0 (by /u/researcher)"}
                res = requests.get(url, headers=headers, timeout=5.0)
                if res.status_code == 200:
                    try:
                        root = ET.fromstring(res.text)
                        entries = root.findall('{http://www.w3.org/2005/Atom}entry')
                        for entry in entries:
                            title_el = entry.find('{http://www.w3.org/2005/Atom}title')
                            content_el = entry.find('{http://www.w3.org/2005/Atom}content')
                            id_el = entry.find('{http://www.w3.org/2005/Atom}id')
                            updated_el = entry.find('{http://www.w3.org/2005/Atom}updated')
                            link_el = entry.find('{http://www.w3.org/2005/Atom}link')

                            title = title_el.text if title_el is not None and title_el.text else ""
                            content_html = content_el.text if content_el is not None and content_el.text else ""
                            clean_content = re.sub(r'<[^>]+>', ' ', content_html).strip()
                            full_text = f"{title}. {clean_content}".strip()
                            if len(full_text) < 20:
                                continue
                            post_id = id_el.text if id_el is not None else str(time.time())
                            parsed.append({
                                "id": f"reddit_{post_id.split('/')[-1]}",
                                "source": "reddit",
                                "source_url": link_el.attrib.get('href') if link_el is not None else "https://reddit.com/r/googlephotos",
                                "post_date": updated_el.text if updated_el is not None else datetime.utcnow().isoformat(),
                                "platform": "web",
                                "author": "Reddit User",
                                "rating": None,
                                "user_text": full_text[:1500],
                                "engagement": 1
                            })
                            if len(parsed) >= limit:
                                break
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse Reddit XML: {parse_err}")
                if len(parsed) >= limit:
                    break
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Reddit live scraping encountered error: {e}. Falling back to fixture.")

        return self.load_fixture_records("reddit")[:limit]

class GoogleHelpForumAdapter(BaseScraperAdapter):
    @property
    def source_name(self) -> str:
        return "help_forum"

    def scrape(self, limit: int = 20, use_fixtures: bool = False) -> List[Dict[str, Any]]:
        # Google Help Community forums require session JS execution; we use curated fixtures
        return self.load_fixture_records("help_forum")[:limit]

class IngestionPipelineManager:
    """
    Coordinates multi-platform scraping, PII scrubbing,
    local Ollama text normalization, MD5 deduplication, and persistence.
    """
    def __init__(self):
        self.adapters = {
            "play_store": PlayStoreScraperAdapter(),
            "app_store": AppStoreScraperAdapter(),
            "reddit": RedditAdapter(),
            "help_forum": GoogleHelpForumAdapter()
        }

    def run_ingestion(
        self,
        sources: Optional[List[str]] = None,
        limit_per_source: int = 20,
        use_fixtures: bool = False
    ) -> Dict[str, Any]:
        target_sources = sources or list(self.adapters.keys())
        total_scraped = 0
        total_sanitized = 0
        total_normalized = 0
        total_inserted = 0
        duplicates_skipped = 0

        with db_manager.session() as conn:
            for source in target_sources:
                adapter = self.adapters.get(source)
                if not adapter:
                    continue

                logger.info(f"Scraping from source: {source} (use_fixtures={use_fixtures})...")
                records = adapter.scrape(limit=limit_per_source, use_fixtures=use_fixtures)
                total_scraped += len(records)

                prepared_batch = []
                for r in records:
                    raw_text = r.get("user_text", "")
                    raw_author = r.get("author", "")

                    # 1. Sanitize (Scrub PII, length & emoji validation)
                    scrubbed_text, author_pseudo, is_valid, reason = sanitizer.sanitize(raw_text, raw_author)
                    if not is_valid or not scrubbed_text:
                        continue
                    total_sanitized += 1

                    # 2. Normalize Text: Fast unicode & whitespace normalization
                    import unicodedata
                    clean_norm = unicodedata.normalize('NFKD', scrubbed_text).encode('ascii', 'ignore').decode('utf-8')
                    normalized_text = " ".join((clean_norm or scrubbed_text).split())
                    total_normalized += 1

                    prepared_batch.append((
                        r.get("id"),
                        r.get("source"),
                        r.get("source_url"),
                        r.get("post_date"),
                        r.get("platform", "android"),
                        author_pseudo,
                        scrubbed_text,
                        normalized_text,
                        r.get("rating"),
                        r.get("engagement", 0)
                    ))

                # 3. Batch insert into raw_conversations
                for row_data in prepared_batch:
                    try:
                        cursor = conn.execute(
                            """
                            INSERT OR IGNORE INTO raw_conversations 
                            (id, source, source_url, post_date, platform, author_pseudonym, raw_text, normalized_text, star_rating, engagement_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            row_data
                        )
                        if cursor.rowcount > 0:
                            total_inserted += 1
                        else:
                            duplicates_skipped += 1
                    except Exception as e:
                        logger.error(f"Failed to insert record {row_data[0]}: {e}")

                # Update checkpoint
                conn.execute(
                    "INSERT OR REPLACE INTO ingestion_checkpoints (source, last_page, last_processed_id) VALUES (?, ?, ?)",
                    (source, 1, records[-1]["id"] if records else None)
                )

        return {
            "sources_scraped": target_sources,
            "total_scraped": total_scraped,
            "total_sanitized": total_sanitized,
            "total_normalized": total_normalized,
            "total_inserted": total_inserted,
            "duplicates_skipped": duplicates_skipped
        }

ingestion_manager = IngestionPipelineManager()

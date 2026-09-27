import logging
import time
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests
from google_play_scraper import reviews, Sort

from backend.app.core.database import db_manager
from backend.app.pipeline.sanitizer import sanitizer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Global target markets
PLAY_STORE_COUNTRIES = [
    ('in', 'en'),  # India (English)
    ('gb', 'en'),  # United Kingdom
    ('ca', 'en'),  # Canada
    ('au', 'en'),  # Australia
    ('ph', 'en'),  # Philippines
    ('de', 'en'),  # Germany (English reviews)
    ('br', 'en'),  # Brazil (English reviews)
    ('mx', 'en'),  # Mexico (English reviews)
    ('us', 'en'),  # United States (additional queries)
]

APP_STORE_COUNTRIES = ['in', 'gb', 'ca', 'au', 'de', 'fr', 'ph']

SUBREDDITS = [
    ("googlephotos", ["search", "find photo", "lost photo", "face tagging", "retrieve"]),
    ("GooglePixel", ["google photos search", "can't find photo", "photos backup search", "face recognition"]),
    ("Android", ["google photos search", "google photos find", "google photos album"]),
    ("photography", ["google photos search", "google photos archive search"]),
]

class GlobalIngestionEngine:
    """
    Fetches real global user feedback across multi-region Play Store,
    multi-region App Store, and Reddit without consuming ANY LLM tokens.
    """

    def __init__(self):
        self.total_fetched = 0
        self.total_inserted = 0

    def fetch_play_store_global(self, count_per_region: int = 100) -> int:
        """Fetch 1-3 star retrieval feedback from multiple global Play Store regions."""
        new_inserted = 0
        logger.info(f"Starting Multi-Region Play Store Ingestion across {len(PLAY_STORE_COUNTRIES)} markets...")

        with db_manager.session() as conn:
            for country, lang in PLAY_STORE_COUNTRIES:
                for score in [1, 2, 3]:
                    try:
                        result, _ = reviews(
                            'com.google.android.apps.photos',
                            lang=lang,
                            country=country,
                            sort=Sort.NEWEST,
                            count=count_per_region // 3,
                            filter_score_with=score
                        )
                        for r in result:
                            text = r.get("content", "")
                            author = r.get("userName", "")
                            scrubbed, pseudo, is_valid, _ = sanitizer.sanitize(text, author)
                            if not is_valid or not scrubbed or len(scrubbed) < 15:
                                continue

                            clean_norm = unicodedata.normalize('NFKD', scrubbed).encode('ascii', 'ignore').decode('utf-8')
                            norm = " ".join((clean_norm or scrubbed).split())

                            review_id = f"play_{country}_{r.get('reviewId')}"
                            source_url = f"https://play.google.com/store/apps/details?id=com.google.android.apps.photos&reviewId={r.get('reviewId')}&gl={country}"
                            post_date = r.get("at", datetime.utcnow()).isoformat() if hasattr(r.get("at"), "isoformat") else str(r.get("at"))

                            cur = conn.execute(
                                """
                                INSERT OR IGNORE INTO raw_conversations 
                                (id, source, source_url, post_date, platform, author_pseudonym, raw_text, normalized_text, star_rating, engagement_count)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    review_id,
                                    "play_store",
                                    source_url,
                                    post_date,
                                    "android",
                                    f"{pseudo} ({country.upper()})",
                                    scrubbed,
                                    norm,
                                    r.get("score"),
                                    r.get("thumbsUpCount", 0)
                                )
                            )
                            if cur.rowcount > 0:
                                new_inserted += 1
                        time.sleep(0.3)  # Gentle spacing between regional requests
                    except Exception as e:
                        logger.warning(f"Failed Play Store fetch for country={country}, score={score}: {e}")

        logger.info(f"Play Store multi-region ingestion complete. Newly inserted: {new_inserted}")
        return new_inserted

    def fetch_app_store_global(self, pages_per_country: int = 5) -> int:
        """Fetch real iOS reviews across multiple regional iTunes storefronts."""
        new_inserted = 0
        logger.info(f"Starting Multi-Region App Store Ingestion across {len(APP_STORE_COUNTRIES)} storefronts...")

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with db_manager.session() as conn:
            for country in APP_STORE_COUNTRIES:
                for page in range(1, pages_per_country + 1):
                    url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id=962194608/sortBy=mostRecent/json"
                    try:
                        res = requests.get(url, headers=headers, timeout=6.0)
                        if res.status_code != 200:
                            break
                        data = res.json()
                        entries = data.get("feed", {}).get("entry", [])
                        for entry in entries:
                            title = entry.get("title", {}).get("label", "")
                            content = entry.get("content", {}).get("label", "")
                            full_text = f"{title}. {content}".strip()
                            if len(full_text) < 15:
                                continue

                            author_name = entry.get("author", {}).get("name", {}).get("label", "Apple User")
                            scrubbed, pseudo, is_valid, _ = sanitizer.sanitize(full_text, author_name)
                            if not is_valid or not scrubbed:
                                continue

                            clean_norm = unicodedata.normalize('NFKD', scrubbed).encode('ascii', 'ignore').decode('utf-8')
                            norm = " ".join((clean_norm or scrubbed).split())

                            review_id = entry.get("id", {}).get("label", str(time.time()))
                            rec_id = f"app_{country}_{review_id}"
                            source_url = f"https://apps.apple.com/{country}/app/google-photos/id962194608?review={review_id}"

                            rating = 3
                            try:
                                rating = int(entry.get("im:rating", {}).get("label", 3))
                            except Exception:
                                pass

                            cur = conn.execute(
                                """
                                INSERT OR IGNORE INTO raw_conversations 
                                (id, source, source_url, post_date, platform, author_pseudonym, raw_text, normalized_text, star_rating, engagement_count)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    rec_id,
                                    "app_store",
                                    source_url,
                                    datetime.utcnow().isoformat(),
                                    "ios",
                                    f"{pseudo} ({country.upper()})",
                                    scrubbed,
                                    norm,
                                    rating,
                                    0
                                )
                            )
                            if cur.rowcount > 0:
                                new_inserted += 1
                        time.sleep(0.3)
                    except Exception as e:
                        logger.warning(f"Failed App Store fetch for country={country}, page={page}: {e}")

        logger.info(f"App Store multi-region ingestion complete. Newly inserted: {new_inserted}")
        return new_inserted

    def fetch_reddit_discussions(self) -> int:
        """Fetch targeted discussions from key subreddits via public RSS feeds."""
        new_inserted = 0
        logger.info("Starting Multi-Subreddit Ingestion...")
        headers = {"User-Agent": "script:googlephotos.global.discovery:v2.0 (research)"}

        with db_manager.session() as conn:
            for sub, queries in SUBREDDITS:
                for q in queries:
                    url = f"https://www.reddit.com/r/{sub}/search.rss?q={q.replace(' ', '+')}&restrict_sr=1&sort=new&limit=25"
                    try:
                        res = requests.get(url, headers=headers, timeout=6.0)
                        if res.status_code == 200:
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
                                if len(full_text) < 25:
                                    continue

                                scrubbed, pseudo, is_valid, _ = sanitizer.sanitize(full_text, f"r/{sub} User")
                                if not is_valid or not scrubbed:
                                    continue

                                clean_norm = unicodedata.normalize('NFKD', scrubbed).encode('ascii', 'ignore').decode('utf-8')
                                norm = " ".join((clean_norm or scrubbed).split())

                                post_id = id_el.text if id_el is not None else str(time.time())
                                clean_id = post_id.split('/')[-1]
                                rec_id = f"reddit_{sub}_{clean_id}"
                                source_url = link_el.attrib.get('href') if link_el is not None else f"https://reddit.com/r/{sub}"

                                cur = conn.execute(
                                    """
                                    INSERT OR IGNORE INTO raw_conversations 
                                    (id, source, source_url, post_date, platform, author_pseudonym, raw_text, normalized_text, star_rating, engagement_count)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        rec_id,
                                        "reddit",
                                        source_url,
                                        updated_el.text if updated_el is not None else datetime.utcnow().isoformat(),
                                        "web",
                                        f"u/{pseudo} (r/{sub})",
                                        scrubbed[:2000],
                                        norm[:2000],
                                        None,
                                        1
                                    )
                                )
                                if cur.rowcount > 0:
                                    new_inserted += 1
                        time.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"Reddit query '{q}' in r/{sub} encountered error: {e}")

        logger.info(f"Reddit multi-subreddit ingestion complete. Newly inserted: {new_inserted}")
        return new_inserted

def run_global_ingestion():
    engine = GlobalIngestionEngine()
    t0 = time.time()
    ps_count = engine.fetch_play_store_global(count_per_region=120)
    as_count = engine.fetch_app_store_global(pages_per_country=6)
    rd_count = engine.fetch_reddit_discussions()
    elapsed = time.time() - t0

    with db_manager.session() as conn:
        total_now = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]

    print(f"\n================ GLOBAL INGESTION SUMMARY ================")
    print(f"Play Store (Multi-Region) newly inserted : {ps_count}")
    print(f"App Store (Multi-Region) newly inserted  : {as_count}")
    print(f"Reddit (Multi-Subreddit) newly inserted  : {rd_count}")
    print(f"Total newly added conversations          : {ps_count + as_count + rd_count}")
    print(f"Total raw conversations in SQLite DB     : {total_now}")
    print(f"Execution time                           : {elapsed:.2f}s")
    print(f"Zero LLM API tokens used (100% network/local compute)")
    print(f"=========================================================\n")

if __name__ == "__main__":
    run_global_ingestion()

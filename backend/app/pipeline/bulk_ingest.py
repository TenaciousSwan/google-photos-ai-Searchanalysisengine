import unicodedata
from google_play_scraper import reviews, Sort
from backend.app.core.database import db_manager
from backend.app.pipeline.sanitizer import sanitizer

def ingest_low_ratings():
    print("Fetching 1-star, 2-star, and 3-star reviews for Google Photos...")
    r1, _ = reviews('com.google.android.apps.photos', lang='en', country='us', sort=Sort.NEWEST, count=250, filter_score_with=1)
    r2, _ = reviews('com.google.android.apps.photos', lang='en', country='us', sort=Sort.NEWEST, count=250, filter_score_with=2)
    r3, _ = reviews('com.google.android.apps.photos', lang='en', country='us', sort=Sort.NEWEST, count=150, filter_score_with=3)
    
    combined = r1 + r2 + r3
    print(f"Total fetched: {len(combined)}")
    
    inserted = 0
    with db_manager.session() as conn:
        for r in combined:
            text = r.get("content", "")
            author = r.get("userName", "")
            scrubbed, pseudo, is_valid, _ = sanitizer.sanitize(text, author)
            if not is_valid or not scrubbed:
                continue
            clean_norm = unicodedata.normalize('NFKD', scrubbed).encode('ascii', 'ignore').decode('utf-8')
            norm = " ".join((clean_norm or scrubbed).split())
            
            c = conn.execute(
                """
                INSERT OR IGNORE INTO raw_conversations 
                (id, source, source_url, post_date, platform, author_pseudonym, raw_text, normalized_text, star_rating, engagement_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"play_{r.get('reviewId')}",
                    "play_store",
                    f"https://play.google.com/store/apps/details?id=com.google.android.apps.photos&reviewId={r.get('reviewId')}",
                    str(r.get('at', '')),
                    "android",
                    pseudo,
                    scrubbed,
                    norm,
                    r.get("score"),
                    r.get("thumbsUpCount", 0)
                )
            )
            if c.rowcount > 0:
                inserted += 1
                
    print(f"Newly inserted: {inserted}")
    with db_manager.session() as conn:
        total = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]
        print(f"Total raw_conversations in DB: {total}")

if __name__ == "__main__":
    ingest_low_ratings()

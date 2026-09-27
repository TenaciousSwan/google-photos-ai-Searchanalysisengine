import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/discovery.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT r.id, r.source, r.platform, r.raw_text, q.filter_reason
    FROM raw_conversations r
    JOIN conversation_qualifications q ON r.id = q.conversation_id
    WHERE q.is_retrieval_friction = 1
""").fetchall()

print(f"Total qualified reviews: {len(rows)}")
for i, r in enumerate(rows, 1):
    print(f"\n[{i}] ID: {r['id']} | {r['source']} ({r['platform']})")
    print(f"    Text: {r['raw_text']}")

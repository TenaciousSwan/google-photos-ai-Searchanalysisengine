import sqlite3
conn = sqlite3.connect("data/discovery.db")
c = conn.cursor()
recent_count = c.execute("SELECT COUNT(id) FROM raw_conversations WHERE post_date >= '2026-03-01'").fetchone()[0]
total_count = c.execute("SELECT COUNT(id) FROM raw_conversations").fetchone()[0]
oldest = c.execute("SELECT MIN(post_date) FROM raw_conversations").fetchone()[0]
newest = c.execute("SELECT MAX(post_date) FROM raw_conversations").fetchone()[0]
print(f"Total: {total_count}, Past 6 months (>= 2026-03-01): {recent_count}")
print(f"Oldest: {oldest}, Newest: {newest}")

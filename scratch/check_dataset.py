import sqlite3

conn = sqlite3.connect('data/discovery.db')
conn.row_factory = sqlite3.Row

print("=== CHECKING SCRAPED REVIEWS ===")
rows = conn.execute("SELECT id, source, platform, raw_text FROM raw_conversations LIMIT 10 OFFSET 20").fetchall()
for r in rows:
    print(f"[{r['id']}] ({r['source']}/{r['platform']}): {repr(r['raw_text'][:110])}")

print("\n=== TOTAL QUALIFICATIONS ===")
print("Qualified (is_retrieval_friction = 1):", conn.execute("SELECT count(*) FROM conversation_qualifications WHERE is_retrieval_friction = 1").fetchone()[0])
print("Rejected (is_retrieval_friction = 0):", conn.execute("SELECT count(*) FROM conversation_qualifications WHERE is_retrieval_friction = 0").fetchone()[0])

print("\n=== ALL 27 EXTRACTED SIGNALS ===")
signals = conn.execute("""
    SELECT s.id, s.conversation_id, s.primary_failure_mode, s.terminal_outcome, s.frustration_severity,
           s.spatial_cues, s.temporal_cues, s.visual_cues, s.text_cues, s.entities_remembered, s.actions_taken,
           r.raw_text
    FROM extracted_signals s
    JOIN raw_conversations r ON s.conversation_id = r.id
""").fetchall()

for s in signals:
    print(f"\n[{s['id']}] conv={s['conversation_id']} | theme={s['primary_failure_mode']} | outcome={s['terminal_outcome']} | sev={s['frustration_severity']}")
    print(f"  Cues: ent={s['entities_remembered']} | spat={s['spatial_cues']} | temp={s['temporal_cues']} | vis={s['visual_cues']} | txt={s['text_cues']}")
    print(f"  Actions: {s['actions_taken']}")
    print(f"  Review: {s['raw_text'][:120]}")

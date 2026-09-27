import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/discovery.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT s.id, s.conversation_id, s.primary_failure_mode, s.terminal_outcome, s.frustration_severity,
           s.spatial_cues, s.temporal_cues, s.visual_cues, s.text_cues, s.entities_remembered, s.actions_taken,
           r.raw_text, r.source, r.platform
    FROM extracted_signals s
    JOIN raw_conversations r ON s.conversation_id = r.id
""").fetchall()

print(f"Total extracted signals in DB: {len(rows)}")
for i, r in enumerate(rows, 1):
    print(f"\n--- [{i}] ID: {r['id']} (conv={r['conversation_id']}, {r['source']}/{r['platform']}) ---")
    print(f"Theme: {r['primary_failure_mode']}")
    print(f"Outcome: {r['terminal_outcome']}")
    print(f"Severity: {r['frustration_severity']}")
    print(f"Entities: {r['entities_remembered']}")
    print(f"Spatial: {r['spatial_cues']}")
    print(f"Temporal: {r['temporal_cues']}")
    print(f"Visual: {r['visual_cues']}")
    print(f"Text cues: {r['text_cues']}")
    print(f"Actions: {r['actions_taken']}")
    print(f"Raw text: {r['raw_text']}")

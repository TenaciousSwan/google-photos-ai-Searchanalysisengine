import sqlite3, json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/discovery.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT s.id, s.conversation_id, r.raw_text, r.source, r.platform, s.frustration_severity, s.terminal_outcome
    FROM extracted_signals s
    JOIN raw_conversations r ON s.conversation_id = r.id
""").fetchall()

# Let's map each review to the best fitting existing theme, cue type, query strategy, outcome, and severity
mapped = []
for r in rows:
    text = r['raw_text']
    lower = text.lower()
    conv_id = r['conversation_id']
    
    # 1. Theme classification
    if any(k in lower for k in ['prescription', 'wi-fi', 'wifi', 'password', 'receipt', 'screenshot', 'invoice', 'document', 'ticket']):
        theme = "Utility / Document Retrieval Gap"
    elif any(k in lower for k in ['multiple people', 'two people', 'bob and sue', 'sarah and kevin', 'together at', 'both people']):
        theme = "Event-Based Multi-Entity Retrieval"
    elif any(k in lower for k in ['exif', 'whatsapp', 'stripped', 'rearrange', 'rearranging', 'order', 'timestamp']):
        theme = "Metadata Dependency Trap (Stripped EXIF)"
    elif any(k in lower for k in ['gemini search', 'worst downgrade', 'ai slop', 'random white cars', '5,000 random', 'too broad', '4,200 photos']):
        theme = "Visual-Concept Search Gap"
    elif any(k in lower for k in ['synonyms', 'linguistically', 'wrong word', 'right word', 'search is useless', 'can\'t find any photos of looking for', 'doesn\'t come up with anything on first attempt']):
        theme = "Weak Search Vocabulary"
    elif any(k in lower for k in ['years ago', 'over the years', 'between 2021', 'late 2022', 'last summer', '2024 will be forgot', 'expired subscription']):
        theme = "Unknown Time (Temporal Vagueness)"
    else:
        theme = "Incomplete Memory"
        
    # 2. Cue type
    if any(k in lower for k in ['prescription', 'wi-fi', 'wifi', 'password', 'receipt', 'screenshot', 'flight confirmation', 'code']):
        cue_type = "Embedded Text / Document"
    elif any(k in lower for k in ['two people', 'multiple people', 'bob and sue', 'sarah', 'sister', 'mom and dad', 'friendships']):
        cue_type = "People / Multi-Entity"
    elif any(k in lower for k in ['red brick', 'blue neon sign', 'white cars', 'yellow house', 'white screen', 'red birthday hat']):
        cue_type = "Visual / Aesthetic"
    elif any(k in lower for k in ['cliffside', 'goa beach', 'paris', 'stands', 'in front of']):
        cue_type = "Spatial / Setting"
    elif any(k in lower for k in ['last summer', 'winter', '2024', 'years ago', '2022', '2023', 'black friday', 'months ago']):
        cue_type = "Temporal / Relative Date"
    elif any(k in lower for k in ['farewell dinner', 'wedding', 'graduation', 'trip']):
        cue_type = "Event / Occasion"
    else:
        cue_type = "Subject / Object"

    # 3. Query strategy
    if any(k in lower for k in ['scrolling', 'swipe back', 'scroll through']):
        query_strategy = "manual_scroll"
    elif any(k in lower for k in ['searched', 'searching', 'search for', 'tried searching']):
        query_strategy = "text_query"
    elif 'star' in lower or 'favorite' in lower or 'album' in lower:
        query_strategy = "album_filter"
    else:
        query_strategy = "text_query"

    # 4. Outcome
    if any(k in lower for k in ['zero results', 'nothing showed up', 'no results', 'showed nothing']):
        outcome = "FAILED_ZERO_RESULTS"
    elif any(k in lower for k in ['400 results', '4,200 photos', '5,000 random', '2000 pictures', 'travel photos, not']):
        outcome = "FAILED_IRRELEVANT"
    elif any(k in lower for k in ['scrolling through 4 months', 'had to swipe back', 'spent 3 hours scrolling']):
        outcome = "SUCCESS_EVENTUAL"
    elif any(k in lower for k in ['gave up', 'never use this again', 'not a fan', 'total ai slop', 'horrible']):
        outcome = "ABANDONED"
    else:
        outcome = r['terminal_outcome'] or "ABANDONED"

    sev = r['frustration_severity'] or 4

    mapped.append({
        "id": r['id'],
        "conv_id": conv_id,
        "theme": theme,
        "cue_type": cue_type,
        "query_strategy": query_strategy,
        "outcome": outcome,
        "severity": sev,
        "platform": r['platform'],
        "source": r['source'],
        "raw_text": text
    })

print(f"Total mapped: {len(mapped)}")
from collections import Counter
theme_counts = Counter(m['theme'] for m in mapped)
print("\n=== THEME COUNTS ===")
for t, c in theme_counts.most_common():
    avg_sev = sum(m['severity'] for m in mapped if m['theme'] == t) / c
    print(f"  {t}: count={c}, avg_sev={avg_sev:.2f}")

print("\n=== CUE TYPE COUNTS ===")
for ct, c in Counter(m['cue_type'] for m in mapped).most_common():
    print(f"  {ct}: {c}")

print("\n=== QUERY STRATEGY COUNTS ===")
for qs, c in Counter(m['query_strategy'] for m in mapped).most_common():
    print(f"  {qs}: {c}")

print("\n=== OUTCOME COUNTS ===")
for oc, c in Counter(m['outcome'] for m in mapped).most_common():
    print(f"  {oc}: {c}")

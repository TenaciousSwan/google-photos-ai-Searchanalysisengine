import sqlite3, json

c = sqlite3.connect('data/discovery.db')
c.row_factory = sqlite3.Row

# All 4 problem clusters
print("=== ALL PROBLEM CLUSTERS ===")
for r in c.execute("SELECT * FROM problem_clusters").fetchall():
    d = dict(r)
    print(f"\n  ID: {d['id']}")
    print(f"  Name: {d['cluster_name']}")
    print(f"  Archetype: {d['archetype']}")
    print(f"  Evidence Count: {d['evidence_count']}")
    print(f"  Failure Rate: {d['failure_rate']}")
    print(f"  Avg Severity: {d['average_severity']}")
    print(f"  Opportunity Score: {d['opportunity_score']}")
    print(f"  Tier: {d['opportunity_tier']}")
    print(f"  Root Cause: {d['root_cause'][:100]}")

# All product insights
print("\n\n=== ALL PRODUCT INSIGHTS ===")
for r in c.execute("SELECT * FROM product_insights").fetchall():
    d = dict(r)
    print(f"\n  Cluster ID: {d['cluster_id']}")
    print(f"  Memory Pattern: {d['user_memory_pattern'][:100]}")
    print(f"  Retrieval Pattern: {d['retrieval_pattern'][:100]}")
    print(f"  Failure Pattern: {d['failure_pattern'][:100]}")
    print(f"  Opportunity: {d['opportunity_statement'][:100]}")
    print(f"  Feature: {d['recommended_feature_direction'][:100]}")

# Extracted signals breakdown
print("\n\n=== EXTRACTED SIGNALS DISTRIBUTION ===")
for r in c.execute("SELECT primary_failure_mode, count(*) as cnt, avg(frustration_severity) as avg_sev FROM extracted_signals GROUP BY primary_failure_mode").fetchall():
    print(f"  {r['primary_failure_mode']}: {r['cnt']} signals, avg severity {r['avg_sev']:.1f}")

# How many qualified?
qual = c.execute("SELECT is_retrieval_friction, count(*) FROM conversation_qualifications GROUP BY is_retrieval_friction").fetchall()
print(f"\n=== QUALIFICATION ===")
for r in qual:
    print(f"  is_retrieval_friction={r[0]}: {r[1]}")

# Cluster mapping
print(f"\n=== CLUSTER MAPPING ===")
for r in c.execute("""
    SELECT pc.id, pc.cluster_name, pc.archetype, count(scm.signal_id) as mapped_signals
    FROM problem_clusters pc
    LEFT JOIN signal_cluster_mapping scm ON pc.id = scm.cluster_id
    GROUP BY pc.id
""").fetchall():
    print(f"  {r['id']} ({r['archetype']}): {r['mapped_signals']} signals mapped")

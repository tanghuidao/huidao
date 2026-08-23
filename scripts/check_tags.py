"""Fix classifier to use word-boundary matching instead of substring matching.

The core issue: keywords like 'did ', 'orb', 'dex', 'ssi' match as substrings
in unrelated contexts (e.g., 'The regulator did something' matches 'did ').

Fix: Use regex word boundaries for short/ambiguous keywords.
"""
import sys
sys.path.insert(0, '/app')

import re
from app.database import SessionLocal
from app.models import Article, Classification

db = SessionLocal()

# Check examples of bad tagging
print("=== 检查标签质量问题 ===\n")

# Sample recent articles and their tags
recent = db.query(Article).join(Classification).filter(
    Classification.article_id == Article.id
).order_by(Article.fetched_at.desc()).limit(20).all()

for a in recent:
    c = a.classification
    if c:
        tags = c.tags or []
        # Check for suspicious tag combinations
        suspicious = []
        if "Worldcoin" in tags and "worldcoin" not in (a.title + " " + (a.raw_content or "")).lower():
            suspicious.append("Worldcoin")
        if "Identity" in tags:
            content_lower = (a.title + " " + (a.raw_content or "")).lower()
            if not any(kw in content_lower for kw in ["decentralized identity", "self-sovereign", "verifiable credential", "worldcoin", "world id", "world_id"]):
                suspicious.append("Identity")
        if "DeFi" in tags:
            content_lower = (a.title + " " + (a.raw_content or "")).lower()
            if not any(kw in content_lower for kw in ["defi", "decentralized finance", "amm", "lending protocol", "liquidity pool"]):
                suspicious.append("DeFi")

        if suspicious:
            print(f"  [{a.id}] {a.title[:60]}")
            print(f"    Tags: {tags}")
            print(f"    SUSPICIOUS: {suspicious}")
            print()

# Count tag frequency to find over-tagged ones
from collections import Counter
tag_counts = Counter()
all_classifications = db.query(Classification).all()
for c in all_classifications:
    if c.tags:
        for tag in c.tags:
            tag_counts[tag] += 1

print("\n=== 标签频率分布 ===")
for tag, count in tag_counts.most_common(20):
    pct = count * 100 / max(len(all_classifications), 1)
    print(f"  {tag}: {count} ({pct:.1f}%)")

# Count total articles per tag to check over-tagging
total_articles = db.query(Article).count()
print(f"\n总文章数: {total_articles}")
print(f"有分类的文章: {len(all_classifications)}")

db.close()

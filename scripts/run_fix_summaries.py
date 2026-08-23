"""Run fix_bad_summaries on existing data"""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.services.summarizer import fix_bad_summaries

db = SessionLocal()
result = fix_bad_summaries(db, limit=500)
print(f"Found: {result['found']} articles with bad summaries")
print(f"Fixed: {result['fixed']}")
print(f"Skipped: {result['skipped']}")

# Also check overall stats
from app.models import Article
from sqlalchemy import func

total = db.query(Article).count()
with_summary = db.query(Article).filter(Article.one_line_summary.isnot(None), Article.one_line_summary != '').count()
empty_summary = db.query(Article).filter(
    (Article.one_line_summary.is_(None)) | (Article.one_line_summary == '')
).count()
short_summary = db.query(Article).filter(
    Article.one_line_summary.isnot(None),
    func.length(Article.one_line_summary) < 5
).count()

print(f"\nOverall stats:")
print(f"  Total articles: {total}")
print(f"  With summary: {with_summary} ({with_summary*100//max(total,1)}%)")
print(f"  Empty summary: {empty_summary}")
print(f"  Very short summary (<5 chars): {short_summary}")

db.close()

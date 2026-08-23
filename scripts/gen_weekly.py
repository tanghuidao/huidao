"""Generate a weekly briefing."""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.services.briefing import generate_briefing

db = SessionLocal()
print("Generating weekly briefing...")
briefing = generate_briefing(db, period_type="weekly")
print(f"Done! Briefing ID: {briefing.id}")
print(f"Title: {briefing.title}")
print(f"Period: {briefing.start_date} ~ {briefing.end_date}")
print(f"Content length: {len(briefing.content)} chars")
print(f"\nPreview (first 300 chars):")
print(briefing.content[:300])
db.close()

"""Fix entity classification for Near and check other entities."""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.services.tracker import get_entity_leaderboard

db = SessionLocal()

print("=== 实体排行榜 (14天) ===")
result = get_entity_leaderboard(db, entity_type=None, days=14, top_n=20)
for r in result:
    name = r.get('name', '?')
    count = r.get('count', 0)
    cat = r.get('category', '?')
    print(f"  {name:<20} count={count:<5} type={cat}")

# Check the KNOWN_ENTITIES dict in classifier
print("\n=== 检查Near在KNOWN_ENTITIES中的分类 ===")
from app.services.classifier import KNOWN_ENTITIES
for name, etype in KNOWN_ENTITIES.items():
    if 'near' in name.lower() or 'Near' in name:
        print(f"  {name}: {etype}")

# Check what the tracker uses for entity categories
print("\n=== 检查tracker中的实体分类逻辑 ===")
import inspect
from app.services import tracker
src = inspect.getsource(tracker.get_entity_leaderboard)
# Find where 'category' comes from
for line in src.split('\n'):
    if 'category' in line or 'type' in line.lower() or 'entity' in line.lower():
        print(f"  {line.strip()}")

db.close()

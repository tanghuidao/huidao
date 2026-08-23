"""Analyze article volume by source and date to find flood sources."""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models import Article, Source
from sqlalchemy import func
from collections import Counter, defaultdict
import datetime

db = SessionLocal()

# 1. Articles per day (last 30 days)
print("=== 每日文章数量 ===")
since = datetime.datetime.utcnow() - datetime.timedelta(days=30)
daily = db.query(
    func.date(Article.fetched_at).label('day'),
    func.count(Article.id).label('cnt')
).filter(
    Article.fetched_at >= since
).group_by(
    func.date(Article.fetched_at)
).order_by('day').all()

for d in daily:
    bar = '#' * (d.cnt // 50)
    print(f"  {d.day}: {d.cnt:>5} {bar}")

# 2. Articles per source (last 30 days)
print("\n=== 每源文章数量 (30天) ===")
source_counts = db.query(
    Source.name,
    func.count(Article.id).label('cnt')
).join(Article, Article.source_id == Source.id).filter(
    Article.fetched_at >= since
).group_by(Source.name).order_by(func.count(Article.id).desc()).all()

total_30d = sum(s.cnt for s in source_counts)
print(f"  30天总计: {total_30d}")
for s in source_counts[:20]:
    pct = s.cnt * 100 / max(total_30d, 1)
    print(f"  {s.name:<30} {s.cnt:>5} ({pct:.1f}%)")

# 3. Check for very short/empty articles (low quality)
print("\n=== 低质量文章检测 ===")
total_all = db.query(Article).count()
short_content = db.query(Article).filter(func.length(Article.raw_content) < 100).count()
empty_content = db.query(Article).filter(
    (Article.raw_content.is_(None)) | (Article.raw_content == '')
).count()
short_title = db.query(Article).filter(func.length(Article.title) < 10).count()
dup_titles = db.query(Article.title, func.count(Article.id).label('cnt')).group_by(Article.title).having(func.count(Article.id) > 5).limit(10).all()

print(f"  总文章: {total_all}")
print(f"  内容<100字: {short_content} ({short_content*100//max(total_all,1)}%)")
print(f"  内容为空: {empty_content} ({empty_content*100//max(total_all,1)}%)")
print(f"  标题<10字: {short_title} ({short_title*100//max(total_all,1)}%)")
print(f"  重复标题(>5次):")
for d in dup_titles:
    print(f"    [{d.cnt}次] {d[0][:60]}")

# 4. Check content length distribution by source
print("\n=== 各源平均内容长度 ===")
avg_lengths = db.query(
    Source.name,
    func.avg(func.length(Article.raw_content)).label('avg_len'),
    func.count(Article.id).label('cnt')
).join(Article, Article.source_id == Source.id).filter(
    Article.fetched_at >= since
).group_by(Source.name).order_by(func.count(Article.id).desc()).limit(15).all()

for s in avg_lengths:
    avg = s.avg_len or 0
    print(f"  {s.name:<30} 文章:{s.cnt:>5}  平均长度:{avg:>8.0f}")

db.close()

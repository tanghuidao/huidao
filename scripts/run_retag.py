from app.database import SessionLocal
from app.services.classifier import retag_recent_articles
from app.services.language import batch_detect_languages
db = SessionLocal()
count = retag_recent_articles(db, days=7, limit=10000)
print(f'retagged: {count}')
lang_count = batch_detect_languages(db, limit=500)
print(f'lang_fixed: {lang_count}')
db.close()

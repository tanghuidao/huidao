"""Check broken sources - test URL connectivity"""
import urllib.request
import ssl
import json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

from app.database import SessionLocal
from app.models import Source

db = SessionLocal()
sources = db.query(Source).filter(Source.health_status != 'healthy').all()

for s in sources:
    print(f"--- {s.name} [{s.source_type}] status={s.health_status}")
    print(f"    url={s.url}")
    if s.url:
        try:
            req = urllib.request.Request(s.url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            data = resp.read()
            ct = resp.headers.get("content-type", "?")
            print(f"    -> HTTP {resp.status}, content-type: {ct}, size: {len(data)} bytes")
        except Exception as e:
            print(f"    -> ERROR: {e}")
    print()

db.close()

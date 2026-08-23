"""Comprehensive fix for broken sources"""
from app.database import SessionLocal
from app.models import Source
import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

db = SessionLocal()

print("=" * 60)
print("信息源修复脚本")
print("=" * 60)

# --- Step 1: Delete duplicate Coinbase Blog ---
print("\n[1. 删除重复Coinbase Blog条目]")
dup = db.query(Source).filter(Source.id == 53).first()
if dup:
    db.delete(dup)
    db.commit()
    print("  已删除 id=53 (Coinbase Blog #disabled 重复条目)")
else:
    print("  条目不存在，跳过")

# --- Step 2: Disable permanently blocked sources ---
print("\n[2. 标记永久性403封锁源为disabled]")
blocked_ids = [16, 58, 4, 54, 2]  # Coinbase, Bitcoin Mag, CryptoSlate, Chainlink, The Block
for sid in blocked_ids:
    s = db.query(Source).filter(Source.id == sid).first()
    if s:
        s.enabled = False
        s.health_status = "disabled"
        print(f"  已禁用: id={s.id} {s.name} (403 Cloudflare封锁)")
db.commit()

# --- Step 3: Fix Messari (404) ---
print("\n[3. 修复Messari (URL已失效)]")
messari = db.query(Source).filter(Source.id == 13).first()
if messari:
    # Try alternative: Messari uses Cloudflare, try direct research feed
    alt_url = "https://messari.io/rss.xml"
    try:
        req = urllib.request.Request(alt_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        if resp.status == 200:
            messari.url = alt_url
            messari.health_status = "healthy"
            messari.enabled = True
            print(f"  已更新Messari URL -> {alt_url}")
    except Exception as e:
        messari.enabled = False
        messari.health_status = "disabled"
        print(f"  Messari无法修复 ({e}), 已禁用")
db.commit()

# --- Step 4: Fix Nikkei Asia (404) ---
print("\n[4. 修复Nikkei Asia (URL已失效)]")
nikkei = db.query(Source).filter(Source.id == 74).first()
if nikkei:
    # Try nikkei.com main RSS
    alt_urls = [
        "https://www.nikkei.com/rss/index.html",
        "https://asia.nikkei.com/rss.xml",
        "https://www.nikkei.co.jp/nikkeiinfo/en/rss/",
    ]
    found = False
    for alt_url in alt_urls:
        try:
            req = urllib.request.Request(alt_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            data = resp.read(200)
            ct = resp.headers.get("content-type", "")
            if resp.status == 200 and ("xml" in ct or "rss" in data.decode("utf-8", errors="ignore")[:200].lower()):
                nikkei.url = alt_url
                nikkei.health_status = "healthy"
                nikkei.enabled = True
                print(f"  已更新Nikkei Asia URL -> {alt_url}")
                found = True
                break
        except Exception:
            continue
    if not found:
        nikkei.enabled = False
        nikkei.health_status = "disabled"
        print("  Nikkei Asia无法修复, 所有替代URL均不可用, 已禁用")
db.commit()

# --- Step 5: Fix MAS Singapore ---
print("\n[5. 修复MAS Singapore (RSS格式问题)]")
mas = db.query(Source).filter(Source.id == 83).first()
if mas:
    # MAS changed their RSS structure, try different paths
    alt_urls = [
        "https://www.mas.gov.sg/news/rss",
        "https://www.mas.gov.sg/-/media/MAS-Media-Library/news/rss/mas-news-rss.xml",
        "https://www.mas.gov.sg/news/media-releases/rss",
    ]
    found = False
    for alt_url in alt_urls:
        try:
            req = urllib.request.Request(alt_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            data = resp.read(500)
            ct = resp.headers.get("content-type", "")
            text = data.decode("utf-8", errors="ignore")
            if resp.status == 200 and ("xml" in ct or "<rss" in text[:300] or "<feed" in text[:300]):
                mas.url = alt_url
                mas.health_status = "healthy"
                mas.enabled = True
                print(f"  已更新MAS URL -> {alt_url}")
                found = True
                break
        except Exception:
            continue
    if not found:
        mas.enabled = False
        mas.health_status = "disabled"
        print("  MAS Singapore无法修复, 已禁用")
db.commit()

# --- Step 6: Fix BlockBeats ---
print("\n[6. 修复BlockBeats律动 (JSON格式)]")
bb = db.query(Source).filter(Source.id == 26).first()
if bb:
    # BlockBeats API changed, try RSS endpoint
    alt_urls = [
        "https://www.theblockbeats.info/rss",
        "https://www.theblockbeats.news/rss",
    ]
    found = False
    for alt_url in alt_urls:
        try:
            req = urllib.request.Request(alt_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            data = resp.read(500)
            text = data.decode("utf-8", errors="ignore")
            if resp.status == 200 and ("<rss" in text[:300] or "<feed" in text[:300] or "<xml" in text[:300]):
                bb.url = alt_url
                bb.health_status = "healthy"
                bb.enabled = True
                print(f"  已更新BlockBeats URL -> {alt_url}")
                found = True
                break
        except Exception:
            continue
    if not found:
        bb.enabled = False
        bb.health_status = "disabled"
        print("  BlockBeats无法修复, 已禁用")
db.commit()

# --- Step 7: Handle degraded web sources ---
print("\n[7. 处理degraded web源]")
odaily = db.query(Source).filter(Source.id == 92).first()
if odaily:
    # odaily.news is a web scraper - might just be slow/unreliable
    # Keep enabled but set health_status to degraded explicitly
    odaily.health_status = "degraded"
    print(f"  odaily.news: 保持degraded状态 (web scraping不稳定)")

wechat = db.query(Source).filter(Source.id == 93).first()
if wechat:
    # WeChat articles require authentication, not scrapable
    wechat.enabled = False
    wechat.health_status = "disabled"
    print("  mp.weixin.qq.com: 已禁用 (需要登录, 无法自动采集)")
db.commit()

# --- Step 8: Add replacement sources ---
print("\n[8. 添加替代信息源]")

replacements = [
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "source_type": "rss",
        "region": "US",
        "credibility_score": 0.90,
        "description": "Leading cryptocurrency news and analysis",
    },
    {
        "name": "Decrypt",
        "url": "https://decrypt.co/feed",
        "source_type": "rss",
        "region": "US",
        "credibility_score": 0.85,
        "description": "Crypto and Web3 news, culture, and investing",
    },
    {
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
        "source_type": "rss",
        "region": "global",
        "credibility_score": 0.80,
        "description": "Blockchain, crypto, and DeFi news",
    },
]

for r in replacements:
    existing = db.query(Source).filter(Source.name == r["name"]).first()
    if existing:
        print(f"  {r['name']}: 已存在, 跳过")
        continue
    # Test URL first
    try:
        req = urllib.request.Request(r["url"], headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        data = resp.read(300)
        if resp.status == 200 and len(data) > 50:
            new_source = Source(
                name=r["name"],
                url=r["url"],
                source_type=r["source_type"],
                region=r["region"],
                credibility_score=r["credibility_score"],
                description=r["description"],
                health_status="healthy",
                enabled=True,
            )
            db.add(new_source)
            print(f"  已添加: {r['name']} ({r['url']})")
        else:
            print(f"  {r['name']}: URL不可用, 跳过")
    except Exception as e:
        print(f"  {r['name']}: URL测试失败 ({e}), 跳过")
db.commit()

# --- Summary ---
print("\n" + "=" * 60)
print("修复完成 - 最终状态统计")
print("=" * 60)
total = db.query(Source).count()
healthy = db.query(Source).filter(Source.health_status == "healthy").count()
disabled = db.query(Source).filter(Source.health_status == "disabled").count()
degraded = db.query(Source).filter(Source.health_status == "degraded").count()
error = db.query(Source).filter(Source.health_status == "error").count()
other = total - healthy - disabled - degraded - error
print(f"  总计: {total} 个源")
print(f"  健康: {healthy}")
print(f"  降级: {degraded}")
print(f"  错误: {error}")
print(f"  已禁用: {disabled}")
if other > 0:
    print(f"  其他: {other}")

db.close()

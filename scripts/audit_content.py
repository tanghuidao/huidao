"""Content capability audit script for huidao.cc - uses urllib (built-in)"""
import urllib.request
import urllib.error
import json
import ssl
from collections import Counter

BASE = "http://localhost:8000"

# Allow self-signed / no cert check for internal calls
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(path):
    url = f"{BASE}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:200]
        except:
            pass
        return {"error": e.code, "text": body}
    except Exception as e:
        return {"error": str(e)}

print("=" * 60)
print("huidao.cc 内容能力审计报告")
print("=" * 60)

# 1. Dashboard overview
print("\n[1. 仪表盘总览]")
dash = fetch("/api/dashboard")
if "error" not in dash:
    stats = dash.get("stats", {})
    print(f"  信息源: {stats.get('total_sources', 0)} (健康: {stats.get('healthy_sources', 0)})")
    print(f"  文章总数: {stats.get('total_articles', 0)}")
    print(f"  今日新增: {stats.get('articles_today', 0)}")
    print(f"  本周新增: {stats.get('articles_this_week', 0)}")
    print(f"  简报: {stats.get('total_briefings', 0)}")
    print(f"  近期热门文章: {len(dash.get('hot_topics', []))} 个")
    print(f"  高风险文章: {len(dash.get('high_risk_articles', []))} 篇")
    print(f"  疑似炒作: {len(dash.get('suspected_hype', []))} 篇")
    print(f"  近期文章: {len(dash.get('recent_articles', []))} 篇")
else:
    print(f"  ERROR: {dash}")

# 2. Sources health
print("\n[2. 信息源健康状态]")
sources = fetch("/api/sources")
if isinstance(sources, list):
    health_counts = Counter(s.get("health_status", "unknown") for s in sources)
    type_counts = Counter(s.get("source_type", "unknown") for s in sources)
    region_counts = Counter(s.get("region", "unknown") for s in sources)
    print(f"  总数: {len(sources)}")
    print(f"  健康分布: {dict(health_counts)}")
    print(f"  类型分布: {dict(type_counts)}")
    print(f"  地区分布: {dict(region_counts)}")
    unhealthy = [s for s in sources if s.get("health_status") != "healthy"]
    if unhealthy:
        print(f"\n  非健康源 ({len(unhealthy)} 个):")
        for s in unhealthy:
            name = s.get("name", "?")
            stype = s.get("source_type", "?")
            status = s.get("health_status", "?")
            score = s.get("credibility_score", 0)
            last = s.get("last_checked_at", "never")
            print(f"    - {name} [{stype}] status={status} score={score:.0%} last={str(last)[:19]}")
else:
    print(f"  ERROR: {sources}")

# 3. Articles analysis
print("\n[3. 文章采集质量]")
articles = fetch("/api/articles?page=1&days=30")
if "error" not in articles:
    total = articles.get("total", 0)
    items = articles.get("articles", [])
    print(f"  近30天文章: {total} 篇 (本页{len(items)}篇)")
    if items:
        classified = sum(1 for a in items if a.get("classification"))
        with_score = sum(1 for a in items if a.get("score"))
        with_summary = sum(1 for a in items if a.get("one_line_summary"))
        print(f"  已AI分类: {classified}/{len(items)} ({classified*100//max(len(items),1)}%)")
        print(f"  已评分: {with_score}/{len(items)} ({with_score*100//max(len(items),1)}%)")
        print(f"  有摘要: {with_summary}/{len(items)} ({with_summary*100//max(len(items),1)}%)")
        types = Counter()
        for a in items:
            cls = a.get("classification", {})
            ct = cls.get("content_type", "未分类") if cls else "未分类"
            types[ct] += 1
        print(f"  内容类型分布: {dict(types)}")
        langs = Counter(a.get("language", "unknown") for a in items)
        print(f"  语言分布: {dict(langs)}")
else:
    print(f"  ERROR: {articles}")

# 4. AI Summary quality sample
print("\n[4. AI摘要质量抽样]")
recent = fetch("/api/articles?page=1&days=7")
if "error" not in recent:
    items = recent.get("articles", [])[:5]
    if items:
        for i, a in enumerate(items):
            title = a.get("title", "无标题")[:60]
            summary = a.get("one_line_summary", "")
            cls = a.get("classification", {})
            ctype = cls.get("content_type", "?") if cls else "?"
            tags = cls.get("tags", [])[:3] if cls else []
            score = a.get("score", {})
            total_s = score.get("total_score", 0) if score else 0
            print(f"  [{i+1}] {title}")
            print(f"      类型: {ctype} | 标签: {tags} | 评分: {total_s:.2f}")
            print(f"      摘要: {summary[:80] if summary else '(无)'}")
    else:
        print("  近7天无文章")
else:
    print(f"  ERROR: {recent}")

# 5. Trend data
print("\n[5. 趋势分析数据]")
article_count = fetch("/api/trends/article-count?days=30")
if isinstance(article_count, list):
    print(f"  文章数量趋势: {len(article_count)} 天数据")
    if article_count:
        total_30d = sum(d.get("count", 0) for d in article_count)
        avg_daily = total_30d / max(len(article_count), 1)
        print(f"  30天总采集: {total_30d} 篇, 日均: {avg_daily:.1f} 篇")
        latest = article_count[-1] if article_count else {}
        print(f"  最新日期: {latest.get('date', '?')} 数量: {latest.get('count', 0)}")
else:
    print(f"  ERROR: {article_count}")

topics = fetch("/api/trends/topics?days=30&top_n=5")
if "error" not in topics and isinstance(topics, dict):
    top_list = topics.get("topics", [])
    print(f"  热门主题: {top_list}")
else:
    print(f"  热门主题: {topics}")

emerging = fetch("/api/trends/emerging")
if isinstance(emerging, list):
    print(f"  新兴话题: {len(emerging)} 个")
    for e in emerging[:5]:
        topic = e.get("topic", "?")
        growth = e.get("growth_rate", 0)
        count = e.get("recent_count", 0)
        new = " [NEW]" if e.get("is_new") else ""
        print(f"    - {topic} (近期{count}次, +{growth*100:.0f}%){new}")
else:
    print(f"  ERROR: {emerging}")

risk = fetch("/api/trends/risk?days=30")
if isinstance(risk, list):
    print(f"  风险趋势: {len(risk)} 天数据")
else:
    print(f"  风险趋势: {risk}")

content_types = fetch("/api/trends/content-types?days=7")
if isinstance(content_types, list):
    print(f"  内容类型分布(7天): {content_types}")
else:
    print(f"  内容类型: {content_types}")

# 6. Briefings
print("\n[6. 简报生成情况]")
briefings = fetch("/api/briefings")
if isinstance(briefings, list):
    print(f"  简报总数: {len(briefings)}")
    if briefings:
        periods = Counter(b.get("period_type", "?") for b in briefings)
        print(f"  类型分布: {dict(periods)}")
        latest = briefings[0]
        print(f"  最新: {latest.get('period_type','?')} {latest.get('start_date','?')}")
        content = latest.get("content", "")
        print(f"  内容长度: {len(content)} 字符")
        print(f"  内容预览: {content[:150]}...")
else:
    print(f"  ERROR: {briefings}")

# 7. Scheduler
print("\n[7. 定时任务状态]")
sched = fetch("/api/v2/scheduler/status")
if "error" not in sched:
    print(f"  调度器: {'运行中' if sched.get('running') else '未启动'}")
    jobs = sched.get("jobs", [])
    if jobs:
        for j in jobs:
            print(f"    - {j.get('name','?')}: {j.get('trigger','?')} | 下次: {str(j.get('next_run','N/A'))[:19]}")
    else:
        print("    (无定时任务)")
else:
    print(f"  ERROR: {sched}")

# 8. Tracking/Entity data
print("\n[8. 观点追踪/实体排行]")
people = fetch("/api/tracking/people/leaderboard?days=14")
if isinstance(people, list):
    print(f"  人物提及排行(14天): {len(people)} 人")
    for p in people[:5]:
        print(f"    - {p.get('name','?')}: {p.get('count',0)} 次 [{p.get('category','?')}]")
else:
    print(f"  ERROR: {people}")

orgs = fetch("/api/tracking/organizations/leaderboard?days=14")
if isinstance(orgs, list):
    print(f"  机构提及排行(14天): {len(orgs)} 个")
    for o in orgs[:5]:
        print(f"    - {o.get('name','?')}: {o.get('count',0)} 次 [{o.get('type','?')}]")
else:
    print(f"  ERROR: {orgs}")

# 9. Alerts
print("\n[9. 预警系统]")
alerts = fetch("/api/v3/alerts")
if "error" not in alerts:
    alert_list = alerts.get("alerts", [])
    print(f"  活跃预警: {len(alert_list)} 条")
    if alert_list:
        severity = Counter(a.get("severity", "?") for a in alert_list)
        print(f"  严重度分布: {dict(severity)}")
else:
    print(f"  ERROR: {alerts}")

# 10. Narrative
print("\n[10. 叙事强度]")
narrative = fetch("/api/v3/narrative/leaderboard?days=14&top_n=10")
if "error" not in narrative:
    rankings = narrative.get("rankings", [])
    print(f"  叙事排行(14天): {len(rankings)} 个主题")
    for n in rankings[:5]:
        strength = n.get("strength", 0)
        print(f"    - {n.get('topic','?')}: {strength*100:.0f}%")
else:
    print(f"  ERROR: {narrative}")

print("\n" + "=" * 60)
print("审计完成")
print("=" * 60)

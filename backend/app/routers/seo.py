"""SEO/GEO pages: server-rendered article & briefing pages, about page, dynamic sitemap."""
import datetime
import html
import json
import re

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.database import get_db
from app.models import Article, Briefing

router = APIRouter(tags=["seo"])

BASE_URL = "https://huidao.cc"

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0d1017; color: #e8ebf2; line-height: 1.7; }
.wrap { max-width: 760px; margin: 0 auto; padding: 24px 20px 60px; }
a { color: #8b9cfa; text-decoration: none; }
a:hover { text-decoration: underline; }
.site-nav { display: flex; align-items: center; gap: 16px; padding: 12px 0; border-bottom: 1px solid #232b3b; margin-bottom: 28px; font-size: 0.9rem; }
.site-nav .logo { font-weight: 700; color: #e8ebf2; font-size: 1.05rem; }
.site-nav .logo span { color: #6e82f8; }
h1 { font-size: 1.6rem; line-height: 1.4; margin-bottom: 12px; }
h2 { font-size: 1.25rem; margin: 24px 0 10px; }
h3 { font-size: 1.05rem; margin: 18px 0 8px; }
.meta { color: #8b95a8; font-size: 0.85rem; margin-bottom: 20px; }
.meta .tag { display: inline-block; background: #131823; border: 1px solid #232b3b; border-radius: 12px; padding: 1px 10px; margin: 2px 4px 2px 0; font-size: 0.78rem; }
.card { background: #131823; border: 1px solid #232b3b; border-radius: 12px; padding: 20px 22px; margin-bottom: 20px; }
.card h2:first-child { margin-top: 0; }
.origin-link { display: inline-block; margin-top: 8px; font-size: 0.9rem; }
.list-item { padding: 12px 0; border-bottom: 1px solid #1a2230; }
.list-item .t { font-size: 1rem; }
.list-item .m { color: #8b95a8; font-size: 0.8rem; margin-top: 2px; }
.pager { display: flex; gap: 20px; margin-top: 24px; font-size: 0.9rem; }
.footer { border-top: 1px solid #232b3b; margin-top: 40px; padding-top: 16px; color: #626d80; font-size: 0.78rem; }
.footer a { color: #8b95a8; margin-right: 14px; }
.disclaimer { background: #131823; border: 1px solid #232b3b; border-left: 3px solid #6e82f8; border-radius: 8px; padding: 12px 16px; margin-top: 24px; font-size: 0.82rem; color: #8b95a8; }
.src-cat { margin: 10px 0; }
.src-cat b { color: #e8ebf2; }
.src-cat span { color: #8b95a8; font-size: 0.85rem; }
code { background: #131823; border: 1px solid #232b3b; border-radius: 6px; padding: 2px 6px; font-size: 0.85em; }
"""

_NAV = (
    '<nav class="site-nav">'
    f'<a class="logo" href="{BASE_URL}/"><span>huidao</span>.cc</a>'
    f'<a href="{BASE_URL}/a">文章</a>'
    f'<a href="{BASE_URL}/b">简报</a>'
    f'<a href="{BASE_URL}/about">关于</a>'
    f'<a href="{BASE_URL}/rss/briefing.xml">RSS</a>'
    '</nav>'
)

_FOOTER = (
    '<div class="footer">'
    f'<a href="{BASE_URL}/">首页</a>'
    f'<a href="{BASE_URL}/about">关于与方法论</a>'
    f'<a href="{BASE_URL}/rss/briefing.xml">RSS 简报</a>'
    f'<a href="{BASE_URL}/rss/alerts.xml">RSS 预警</a>'
    f'<a href="https://github.com/tanghuidao/huidao" target="_blank" rel="noopener">GitHub</a>'
    '<div style="margin-top:8px">&copy; 2026 huidao.cc - AI驱动的Web4全球智库 · CC BY 4.0</div>'
    '<div style="margin-top:6px">本站内容为 AI 自动聚合与分析结果，仅供研究参考，不构成任何投资建议。</div>'
    '</div>'
)


def _page(title: str, description: str, canonical: str, body: str, jsonld: dict = None) -> str:
    jsonld_tag = ""
    if jsonld:
        jsonld_tag = ('<script type="application/ld+json">'
                      + json.dumps(jsonld, ensure_ascii=False)
                      + '</script>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0d1017">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="huidao.cc">
<meta property="og:image" content="{BASE_URL}/static/og-banner.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(title)}">
<meta name="twitter:description" content="{html.escape(description)}">
<meta name="twitter:image" content="{BASE_URL}/static/og-banner.png">
{jsonld_tag}
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
{_NAV}
{body}
{_FOOTER}
</div>
</body>
</html>"""


def _fmt_date(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime.datetime):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


def _md_to_html(text: str) -> str:
    """Minimal markdown -> HTML (escape first; headings shifted so page keeps one h1)."""
    text = html.escape(text)
    text = re.sub(r'^### (.+)$', r'<h4>\1</h4>', text, flags=re.M)
    text = re.sub(r'^## (.+)$', r'<h3>\1</h3>', text, flags=re.M)
    text = re.sub(r'^# (.+)$', r'<h2>\1</h2>', text, flags=re.M)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return text.replace("\n", "<br>")


def _not_found(kind: str) -> HTMLResponse:
    body = f'<h1>404 - {kind}不存在</h1><p style="margin-top:12px"><a href="{BASE_URL}/">返回首页</a></p>'
    return HTMLResponse(
        _page(f"404 - {kind}不存在 - huidao.cc", "页面不存在", f"{BASE_URL}/", body),
        status_code=404,
    )


# ============ Article pages ============

@router.get("/a", response_class=HTMLResponse)
def article_index(page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    """Public HTML index of recent articles (crawlable entry point)."""
    page_size = 100
    q = (db.query(Article)
         .filter(Article.summary.isnot(None) | Article.one_line_summary.isnot(None))
         .order_by(desc(Article.published_at).nullslast())
         .offset((page - 1) * page_size)
         .limit(page_size + 1))
    rows = q.all()
    has_next = len(rows) > page_size
    rows = rows[:page_size]

    items = []
    for a in rows:
        d = _fmt_date(a.published_at)
        items.append(
            f'<div class="list-item"><a class="t" href="{BASE_URL}/a/{a.id}">{html.escape(a.title)}</a>'
            f'<div class="m">{d}</div></div>'
        )
    pager = '<div class="pager">'
    if page > 1:
        pager += f'<a href="{BASE_URL}/a?page={page - 1}">&larr; 上一页</a>'
    if has_next:
        pager += f'<a href="{BASE_URL}/a?page={page + 1}">下一页 &rarr;</a>'
    pager += '</div>'

    body = (f'<h1>文章库</h1>'
            f'<p class="meta">huidao.cc 从 60+ 全球信息源采集并经 AI 摘要的公开文章,第 {page} 页</p>'
            + "".join(items) + pager)
    canonical = f"{BASE_URL}/a" if page == 1 else f"{BASE_URL}/a?page={page}"
    return HTMLResponse(_page(
        f"文章库 第{page}页 - huidao.cc" if page > 1 else "文章库 - huidao.cc",
        "AI摘要的全球AI/Crypto/Web3/Web4文章库,来自60+信息源,每日更新。",
        canonical, body))


@router.get("/a/{article_id}", response_class=HTMLResponse)
def article_page(article_id: int, db: Session = Depends(get_db)):
    a = (db.query(Article)
         .options(joinedload(Article.classification), joinedload(Article.source))
         .filter(Article.id == article_id).first())
    if not a:
        return _not_found("文章")

    canonical = f"{BASE_URL}/a/{a.id}"
    title = a.title
    desc_text = (a.one_line_summary or (a.summary or "")[:150] or a.title).strip()
    source_name = a.source.name if a.source else "未知来源"
    pub = _fmt_date(a.published_at) or _fmt_date(a.fetched_at)

    tags_html = ""
    if a.classification and a.classification.tags:
        tags = a.classification.tags if isinstance(a.classification.tags, list) else []
        tags_html = "".join(f'<span class="tag">{html.escape(str(t))}</span>' for t in tags[:6])

    summary_html = ""
    if a.summary:
        summary_html = f'<div class="card"><h2>AI 摘要</h2><p>{html.escape(a.summary)}</p></div>'
    elif a.one_line_summary:
        summary_html = f'<div class="card"><h2>AI 摘要</h2><p>{html.escape(a.one_line_summary)}</p></div>'

    body = (
        f'<article><h1>{html.escape(title)}</h1>'
        f'<div class="meta">来源:{html.escape(source_name)} &middot; {pub}<br>{tags_html}</div>'
        f'{summary_html}'
        f'<a class="origin-link" href="{html.escape(a.url)}" rel="noopener nofollow" target="_blank">阅读原文 &rarr;</a>'
        f'</article>'
        f'<p style="margin-top:28px"><a href="{BASE_URL}/a">&larr; 更多文章</a></p>'
    )

    author_ld = ({"@type": "Person", "name": a.author} if a.author
                 else {"@type": "Organization", "name": source_name})
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc_text,
        "url": canonical,
        "mainEntityOfPage": canonical,
        "datePublished": (a.published_at or a.fetched_at).isoformat() if (a.published_at or a.fetched_at) else None,
        "dateModified": a.fetched_at.isoformat() if a.fetched_at else None,
        "author": author_ld,
        "publisher": {"@id": f"{BASE_URL}/#organization", "@type": "Organization",
                      "name": "huidao.cc", "url": BASE_URL},
        "isBasedOn": a.url,
        "inLanguage": a.language or "en",
    }
    jsonld = {k: v for k, v in jsonld.items() if v is not None}

    return HTMLResponse(_page(f"{title} - huidao.cc", desc_text, canonical, body, jsonld))


# ============ Briefing pages ============

@router.get("/b", response_class=HTMLResponse)
def briefing_index(db: Session = Depends(get_db)):
    rows = db.query(Briefing).order_by(desc(Briefing.created_at)).limit(200).all()
    label = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
    items = []
    for b in rows:
        items.append(
            f'<div class="list-item"><a class="t" href="{BASE_URL}/b/{b.id}">{html.escape(b.title)}</a>'
            f'<div class="m">{label.get(b.period_type, b.period_type)} &middot; {_fmt_date(b.created_at)}</div></div>'
        )
    body = ('<h1>智能简报</h1>'
            '<p class="meta">AI 基于全球信息源自动生成的每日/每周简报</p>'
            + "".join(items))
    return HTMLResponse(_page(
        "智能简报 - huidao.cc",
        "AI自动生成的AI/Crypto/Web3/Web4每日与每周简报,汇总全球60+信息源的关键动态。",
        f"{BASE_URL}/b", body))


@router.get("/b/{briefing_id}", response_class=HTMLResponse)
def briefing_page(briefing_id: int, db: Session = Depends(get_db)):
    b = db.query(Briefing).filter(Briefing.id == briefing_id).first()
    if not b:
        return _not_found("简报")

    canonical = f"{BASE_URL}/b/{b.id}"
    desc_text = f"huidao.cc AI简报:{b.title},覆盖 {b.start_date} 至 {b.end_date} 的全球AI/Crypto/Web3动态。"
    body = (
        f'<article><h1>{html.escape(b.title)}</h1>'
        f'<div class="meta">{_fmt_date(b.start_date)} ~ {_fmt_date(b.end_date)} &middot; 生成于 {_fmt_date(b.created_at)}</div>'
        f'<div class="card">{_md_to_html(b.content)}</div>'
        f'</article>'
        f'<p style="margin-top:28px"><a href="{BASE_URL}/b">&larr; 更多简报</a></p>'
    )
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": b.title,
        "description": desc_text,
        "url": canonical,
        "mainEntityOfPage": canonical,
        "datePublished": b.created_at.isoformat() if b.created_at else None,
        "author": {"@id": f"{BASE_URL}/#organization", "@type": "Organization",
                   "name": "huidao.cc", "url": BASE_URL},
        "publisher": {"@id": f"{BASE_URL}/#organization", "@type": "Organization",
                      "name": "huidao.cc", "url": BASE_URL},
        "inLanguage": "zh-CN",
    }
    jsonld = {k: v for k, v in jsonld.items() if v is not None}
    return HTMLResponse(_page(f"{b.title} - huidao.cc", desc_text, canonical, body, jsonld))


# ============ About page ============

@router.get("/about", response_class=HTMLResponse)
def about_page(db: Session = Depends(get_db)):
    from app.models import Source

    sources = db.query(Source).filter(Source.enabled == True).all()  # noqa: E712
    total_sources = len(sources)
    by_cat = {}
    for s in sources:
        by_cat.setdefault(s.category or "other", []).append(s.name)
    cat_html = "".join(
        f'<div class="src-cat"><b>{html.escape(cat)}</b> ({len(names)})：<span>'
        + html.escape(" · ".join(names)) + "</span></div>"
        for cat, names in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))
    )

    body = f"""
<h1>关于 huidao.cc</h1>
<p class="meta">AI 驱动的 Web4.0 时代全球智库</p>

<div class="card">
<h2>我们做什么</h2>
<p>huidao.cc 持续监控全球 {total_sources}+ 公开信息源(主流媒体、Crypto/AI 垂直媒体、研究机构、企业与关键人物),
聚焦 AI、Crypto、Web3 与 Web4.0 领域,用 AI 完成信息的采集、分类、评分与提炼,
帮助读者在噪音中捕捉真正重要的信号。</p>
</div>

<div class="card">
<h2>方法论</h2>
<h3>1. 采集与去重</h3>
<p>通过 RSS、网页抓取与 API 定时采集(默认每 60 分钟一轮),按内容指纹去重,保留原文链接与出处。</p>
<h3>2. AI 分类与标注</h3>
<p>对每篇内容判定类型(新闻/观点/研报/融资/监管/产品发布/市场信号等),提取主题标签与实体(人物、公司、项目)。融资类判定采用"金额锚定"规则(如 raised $X / Series A / 完成X亿融资),避免把一般价格新闻误判为融资。</p>
<h3>3. 监管风险评分 (0-100%)</h3>
<p>采用连续评分模型:命中监管类标签、软性监管词汇(审查/合规/听证等)、硬性监管词汇(禁令/罚款/起诉等)与监管机构名称,分别按权重累加,再经平方根阻尼函数压缩,使结果落在一个连续、可比的 0-1 区间,避免单一关键词导致分数饱和。</p>
<h3>4. 炒作识别 (0-100%)</h3>
<p>基于收紧后的炒作词库(moonshot/革命性/稳赚 等强承诺词汇),需要命中 2 个及以上关键词才计分,并过滤播客/视频类 URL,以降低误报。</p>
<h3>5. 多维总分</h3>
<p>从可信度、影响力、执行力、资本信号、叙事强度、风险六个维度加权合成总分,用于排序与筛选。</p>
<h3>6. 预警与追踪</h3>
<p>识别高风险监管与疑似炒作内容并生成预警;追踪关键人物与机构的观点变化;计算话题的叙事强度与新兴话题增速。</p>
<h3>7. 简报生成</h3>
<p>AI 每日 08:00 (UTC) 生成日报,每周一 09:00 (UTC) 生成周报,自动汇总关键动态。</p>
</div>

<div class="card">
<h2>免责声明</h2>
<p><strong>1.</strong> 本站内容来源于第三方公开信息聚合,版权归原始出处所有,聚合与转载不代表本站立场;<br>
<strong>2.</strong> 风险评分与炒作评分为算法自动生成的量化指标,并非专业金融意见,可能存在误判;<br>
<strong>3.</strong> 用户需自行判断信息准确性并承担相应决策风险。本站所有内容仅供研究参考,不构成任何投资建议。</p>
</div>

<div class="card">
<h2>数据源 ({total_sources} 个,按类别)</h2>
<p style="color:#8b95a8;font-size:0.85rem;margin-bottom:8px">当前监控的全部启用信息源,便于您自行判断信息覆盖面:</p>
{cat_html}
</div>

<div class="card">
<h2>数据出口</h2>
<p>RSS 订阅:<a href="{BASE_URL}/rss/briefing.xml">简报 feed</a> · <a href="{BASE_URL}/rss/alerts.xml">风险预警 feed</a></p>
<p style="margin-top:6px">公开 JSON API(限流 60 次/分钟/IP):<br>
<code>GET {BASE_URL}/api/v1/articles?category=regulation&amp;date_from=2026-08-01&amp;limit=20</code></p>
</div>

<div class="card">
<h2>更新频率与运行状态</h2>
<p>信息源每 60 分钟自动采集一次,AI 分类/摘要随采集批处理;日报每日 08:00 (UTC)、周报每周一 09:00 (UTC) 自动生成。站点自 2026 年上线以来持续运行,由作者独立维护。</p>
</div>

<div class="card">
<h2>如何引用</h2>
<p>本站文章页(/a/编号)与简报页(/b/编号)均为固定链接,欢迎引用;引用时请注明"huidao.cc"并保留链接。
文章的 AI 摘要基于原文生成,重要决策请以原文为准——每篇文章页都附有原文链接。</p>
</div>

<div class="card">
<h2>联系我们</h2>
<p>GitHub 仓库:<a href="https://github.com/tanghuidao/huidao" target="_blank" rel="noopener">github.com/tanghuidao/huidao</a>(通过 Issue / PR 反馈,公开可追溯)</p>
</div>

<div class="disclaimer">本站内容为 AI 自动聚合与分析结果,仅供研究参考,不构成任何投资建议。风险/炒作评分由算法自动生成,可能存在误判,请勿作为投资决策依据。</div>
"""
    jsonld = {
        "@context": "https://schema.org",
        "@type": "AboutPage",
        "name": "关于与方法论 - huidao.cc",
        "url": f"{BASE_URL}/about",
        "mainEntity": {"@id": f"{BASE_URL}/#organization"},
        "inLanguage": "zh-CN",
    }
    return HTMLResponse(_page(
        "关于与方法论 - huidao.cc",
        f"huidao.cc 是 AI 驱动的 Web4.0 全球智库:监控{total_sources}+全球信息源,以采集-分类-评分-预警-简报的流水线提炼AI/Crypto/Web3关键信号。内容仅供研究参考,不构成投资建议。",
        f"{BASE_URL}/about", body, jsonld))


# ============ Dynamic sitemap ============

@router.get("/sitemap.xml")
def sitemap_xml(db: Session = Depends(get_db)):
    today = datetime.date.today().isoformat()
    urls = [
        (f"{BASE_URL}/", today, "daily", "1.0"),
        (f"{BASE_URL}/a", today, "daily", "0.9"),
        (f"{BASE_URL}/b", today, "daily", "0.9"),
        (f"{BASE_URL}/about", "2026-07-03", "monthly", "0.5"),
    ]

    briefings = db.query(Briefing).order_by(desc(Briefing.created_at)).limit(500).all()
    for b in briefings:
        urls.append((f"{BASE_URL}/b/{b.id}", _fmt_date(b.created_at) or today, "monthly", "0.7"))

    articles = (db.query(Article.id, Article.published_at, Article.fetched_at)
                .filter(Article.summary.isnot(None) | Article.one_line_summary.isnot(None))
                .order_by(desc(Article.published_at).nullslast())
                .limit(2000).all())
    for aid, pub, fetched in articles:
        lastmod = _fmt_date(pub) or _fmt_date(fetched) or today
        urls.append((f"{BASE_URL}/a/{aid}", lastmod, "monthly", "0.6"))

    entries = "".join(
        f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod>"
        f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for loc, lastmod, freq, prio in urls
    )
    content = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + entries + '</urlset>')
    return Response(content=content, media_type="application/xml")

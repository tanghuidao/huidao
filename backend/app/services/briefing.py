"""Briefing generation service."""
import datetime
import logging
from typing import Optional
from collections import Counter

from openai import OpenAI
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.models import Article, Classification, Score, Briefing, Source

logger = logging.getLogger(__name__)


BRIEFING_PROMPT = """你是一名资深的AI+Crypto/Web3行业分析师。请根据以下信息生成一份专业的中文简报。

时间范围: {start_date} 至 {end_date}
文章总数: {total_articles}

以下是本期间的重要文章摘要：

{articles_summary}

---

热门主题: {hot_topics}
高频实体: {top_entities}
高风险监管动态数: {regulation_count}
疑似炒作内容数: {hype_count}

---

请按照以下格式生成简报：

# AI + Crypto / Web3 /4全球动态简报

**时间范围**：{start_date} 至 {end_date}

**核心结论**：（3-5句话概括本期最重要的趋势和信号）

## 一、最重要的5条动态

（选出影响最大、最有价值的5条信息，每条包含：事件、意义、来源）

## 二、主流媒体关注点

（主流媒体在报道什么主题？关注度有什么变化？）

## 三、机构/企业报告与观点

（机构发布了什么重要报告？核心观点是什么？）

## 四、关键人物观点

（有哪些重要人物发表了什么观点？）

## 五、项目与公司进展

（哪些项目有实质性进展？哪些只是公告？）

## 六、监管与政策变化

（各司法辖区有什么新的监管动态？）

## 七、值得继续跟踪的信号

（未来30-90天应该关注什么？）

## 八、噪音或疑似炒作

（哪些内容可能是营销或炒作？依据是什么？）
"""


def get_llm_client() -> Optional[OpenAI]:
    """Get OpenAI client."""
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def generate_briefing(
    db: Session,
    period_type: str = "daily",
    start_date: datetime.date = None,
    end_date: datetime.date = None,
) -> Briefing:
    """Generate a briefing for the given period."""

    # Default date ranges
    today = datetime.date.today()
    if not end_date:
        end_date = today
    if not start_date:
        if period_type == "daily":
            start_date = end_date - datetime.timedelta(days=1)
        elif period_type == "weekly":
            start_date = end_date - datetime.timedelta(days=7)
        else:  # monthly
            start_date = end_date - datetime.timedelta(days=30)

    # Query articles in the period
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)

    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
        joinedload(Article.source),
    ).filter(
        Article.fetched_at >= start_dt,
        Article.fetched_at <= end_dt,
    ).order_by(desc(Article.published_at)).all()

    if not articles:
        # Create empty briefing
        briefing = Briefing(
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            title=f"AI + Crypto / Web3 /4全球动态简报 ({start_date} ~ {end_date})",
            content=f"本期间（{start_date} 至 {end_date}）暂无采集到的内容。请检查信息源配置和采集状态。",
        )
        db.add(briefing)
        db.commit()
        db.refresh(briefing)
        return briefing

    # Prepare summary data
    articles_summary = _prepare_articles_summary(articles)
    hot_topics = _get_hot_topics(articles)
    top_entities = _get_top_entities(articles)
    regulation_count = sum(
        1 for a in articles
        if a.classification and a.classification.content_type == "regulation"
    )
    hype_count = sum(
        1 for a in articles
        if a.classification and a.classification.hype_risk > 0.5
    )

    # Generate with LLM or fallback
    client = get_llm_client()
    if client:
        content = _generate_with_llm(
            client, start_date, end_date, len(articles),
            articles_summary, hot_topics, top_entities,
            regulation_count, hype_count,
        )
    else:
        content = _generate_fallback(
            start_date, end_date, articles,
            hot_topics, top_entities,
            regulation_count, hype_count,
        )

    # Save briefing
    briefing = Briefing(
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        title=f"AI + Crypto / Web3 全球动态简报 ({start_date} ~ {end_date})",
        content=content,
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    return briefing


def _prepare_articles_summary(articles: list[Article], max_articles: int = 30) -> str:
    """Prepare article summaries for the briefing prompt."""
    # Sort by score if available
    scored = [(a, a.score.total_score if a.score else 0.0) for a in articles]
    scored.sort(key=lambda x: x[1], reverse=True)

    lines = []
    for article, score in scored[:max_articles]:
        source_name = article.source.name if article.source else "Unknown"
        summary = article.one_line_summary or article.summary or article.title
        content_type = article.classification.content_type if article.classification else "unknown"
        tags = ", ".join(article.classification.tags[:3]) if article.classification and article.classification.tags else ""

        lines.append(
            f"- [{content_type}] {article.title}\n"
            f"  来源: {source_name} | 评分: {score:.2f} | 标签: {tags}\n"
            f"  摘要: {summary[:200]}"
        )

    return "\n\n".join(lines)


def _get_hot_topics(articles: list[Article]) -> str:
    """Get hot topics from article tags."""
    tag_counter = Counter()
    for article in articles:
        if article.classification and article.classification.tags:
            for tag in article.classification.tags:
                tag_counter[tag] += 1

    top_10 = tag_counter.most_common(10)
    return ", ".join(f"{tag}({count})" for tag, count in top_10)


def _get_top_entities(articles: list[Article]) -> str:
    """Get most mentioned entities."""
    entity_counter = Counter()
    for article in articles:
        if article.classification and article.classification.entities:
            for entity in article.classification.entities:
                name = entity.get("name", "")
                if name:
                    entity_counter[name] += 1

    top_10 = entity_counter.most_common(10)
    return ", ".join(f"{name}({count})" for name, count in top_10)


def _generate_with_llm(
    client: OpenAI,
    start_date, end_date, total_articles,
    articles_summary, hot_topics, top_entities,
    regulation_count, hype_count,
) -> str:
    """Generate briefing content using LLM."""
    try:
        prompt = BRIEFING_PROMPT.format(
            start_date=start_date,
            end_date=end_date,
            total_articles=total_articles,
            articles_summary=articles_summary,
            hot_topics=hot_topics,
            top_entities=top_entities,
            regulation_count=regulation_count,
            hype_count=hype_count,
        )

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一名资深AI+Crypto/Web3行业分析师，擅长将大量信息整合为有洞察力的中文简报。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=3000,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"LLM briefing generation error: {e}")
        return _generate_fallback(
            start_date, end_date, [],
            hot_topics, top_entities,
            regulation_count, hype_count,
        )


def _generate_fallback(
    start_date, end_date, articles,
    hot_topics, top_entities,
    regulation_count, hype_count,
) -> str:
    """Generate a simple briefing without LLM."""
    content = f"""# AI + Crypto / Web3 /4全球动态简报

**时间范围**：{start_date} 至 {end_date}

**核心结论**：本期共采集 {len(articles)} 条信息。以下为自动生成的摘要（LLM未配置，使用规则摘要）。

## 一、热门主题

{hot_topics or "暂无数据"}

## 二、高频实体

{top_entities or "暂无数据"}

## 三、监管动态

本期发现 {regulation_count} 条监管相关内容。

## 四、疑似炒作

本期发现 {hype_count} 条疑似炒作内容。

## 五、重要文章列表

"""
    # Add top articles
    scored = [(a, a.score.total_score if a.score else 0.0) for a in articles]
    scored.sort(key=lambda x: x[1], reverse=True)

    for i, (article, score) in enumerate(scored[:10], 1):
        content += f"{i}. {article.title} (评分: {score:.2f})\n   链接: {article.url}\n\n"

    content += "\n---\n*注：配置 OPENAI_API_KEY 后可获得 AI 生成的深度分析简报。*"
    return content

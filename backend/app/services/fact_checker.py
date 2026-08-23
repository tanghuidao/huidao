"""Cross-source fact verification service."""
import datetime
import logging
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.models import Article, Classification, FactCheck
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)


def find_related_articles(db: Session, article: Article, days: int = 7, limit: int = 20) -> list[Article]:
    """Find articles that discuss similar topics to the given article."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    if not article.classification or not article.classification.entities:
        return []

    # Search by shared entities
    entity_names = [e.get("name", "") for e in (article.classification.entities or [])]
    if not entity_names:
        return []

    # Find articles mentioning the same entities
    related = []
    candidates = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.source),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Article.id != article.id,
    ).order_by(desc(Article.published_at)).limit(200).all()

    for candidate in candidates:
        if not candidate.classification or not candidate.classification.entities:
            continue
        candidate_entities = [e.get("name", "") for e in (candidate.classification.entities or [])]
        # Calculate entity overlap
        overlap = len(set(entity_names) & set(candidate_entities))
        if overlap > 0:
            related.append((candidate, overlap))

    # Sort by overlap and return top N
    related.sort(key=lambda x: x[1], reverse=True)
    return [a for a, _ in related[:limit]]


def verify_claim_rule_based(article: Article, related_articles: list[Article]) -> dict:
    """Rule-based fact verification by cross-referencing sources."""
    if not related_articles:
        return {
            "status": "unverified",
            "confidence": 0.3,
            "supporting": [],
            "contradicting": [],
            "analysis": "No related articles found for cross-verification.",
        }

    supporting = []
    contradicting = []

    # Check title similarity and content alignment
    article_keywords = set(
        (article.title or "").lower().split() +
        (article.classification.tags if article.classification and article.classification.tags else [])
    )

    for related in related_articles:
        related_keywords = set(
            (related.title or "").lower().split() +
            (related.classification.tags if related.classification and related.classification.tags else [])
        )
        overlap_ratio = len(article_keywords & related_keywords) / max(len(article_keywords | related_keywords), 1)

        # Check content type compatibility
        a_type = article.classification.content_type if article.classification else ""
        r_type = related.classification.content_type if related.classification else ""

        # Different sources reporting same thing = supporting
        if overlap_ratio > 0.2 and article.source_id != related.source_id:
            if related.classification and related.classification.hype_risk < 0.5:
                supporting.append(related.id)
            elif related.classification and related.classification.hype_risk > 0.7:
                contradicting.append(related.id)
            else:
                supporting.append(related.id)

    # Determine verification status
    support_count = len(supporting)
    contradict_count = len(contradicting)
    total = support_count + contradict_count

    if total == 0:
        status = "unverified"
        confidence = 0.3
    elif contradict_count == 0 and support_count >= 3:
        status = "confirmed"
        confidence = min(0.6 + support_count * 0.05, 0.95)
    elif support_count == 0 and contradict_count >= 2:
        status = "contradicted"
        confidence = min(0.5 + contradict_count * 0.1, 0.9)
    elif support_count > contradict_count * 2:
        status = "partially_confirmed"
        confidence = 0.5 + (support_count - contradict_count) * 0.05
    else:
        status = "unverified"
        confidence = 0.4

    return {
        "status": status,
        "confidence": round(min(confidence, 1.0), 2),
        "supporting": supporting,
        "contradicting": contradicting,
        "analysis": f"Found {support_count} supporting and {contradict_count} contradicting sources.",
    }


def verify_with_llm(article: Article, related_articles: list[Article]) -> Optional[dict]:
    """Use LLM for deeper fact verification."""
    if not OPENAI_API_KEY:
        return None

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # Prepare context
    related_summaries = []
    for r in related_articles[:8]:
        source_name = r.source.name if r.source else "Unknown"
        summary = r.one_line_summary or r.title
        related_summaries.append(f"- [{source_name}] {summary}")

    prompt = f"""请对以下文章的核心声明进行事实验证分析：

原文标题: {article.title}
原文来源: {article.source.name if article.source else 'Unknown'}
原文内容摘要: {(article.raw_content or article.title)[:800]}

以下是相关报道:
{chr(10).join(related_summaries)}

请输出（中文）:
1. 核心声明提取: (这篇文章的核心事实声明是什么)
2. 验证结论: (已证实/部分证实/未证实/存疑/相互矛盾)
3. 置信度: (0-1的数字)
4. 分析理由: (为什么做出这个判断)
5. 需要关注: (是否有需要进一步跟踪的点)
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一位专业的事实核查分析师，擅长AI和Crypto领域的信息验证。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return {"llm_analysis": response.choices[0].message.content}
    except Exception as e:
        logger.error(f"LLM verification error: {e}")
        return None


def verify_article(db: Session, article_id: int) -> dict:
    """Full verification pipeline for an article."""
    article = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.source),
    ).filter(Article.id == article_id).first()

    if not article:
        return {"error": "Article not found"}

    # Find related articles
    related = find_related_articles(db, article)

    # Rule-based verification
    result = verify_claim_rule_based(article, related)

    # LLM verification (if available)
    llm_result = verify_with_llm(article, related)
    if llm_result:
        result["llm_analysis"] = llm_result.get("llm_analysis", "")

    # Save to DB
    fact_check = FactCheck(
        claim=article.title,
        source_article_id=article.id,
        supporting_articles=result["supporting"],
        contradicting_articles=result["contradicting"],
        verification_status=result["status"],
        confidence=result["confidence"],
        analysis=result.get("llm_analysis", result["analysis"]),
    )
    db.add(fact_check)
    db.commit()
    db.refresh(fact_check)

    result["fact_check_id"] = fact_check.id
    result["article_title"] = article.title
    return result


def batch_verify(db: Session, days: int = 3, limit: int = 20) -> list[dict]:
    """Verify recent high-impact articles."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    # Get high-scored articles without existing fact checks
    checked_ids = [fc.source_article_id for fc in db.query(FactCheck).all()]

    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).filter(
        Article.fetched_at >= since,
        ~Article.id.in_(checked_ids) if checked_ids else True,
    ).order_by(desc(Article.fetched_at)).limit(limit).all()

    results = []
    for article in articles:
        try:
            result = verify_article(db, article.id)
            results.append(result)
        except Exception as e:
            logger.error(f"Verification error for article {article.id}: {e}")

    return results

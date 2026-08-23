"""Narrative strength model - quantifies how strong a narrative/topic is growing."""
import datetime
import logging
import math
from collections import Counter, defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import String
from sqlalchemy import desc

from app.models import Article, Classification, Score, Source
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)


# Narrative strength factors and their weights
NARRATIVE_WEIGHTS = {
    "volume_growth": 0.20,       # How quickly mention volume is growing
    "source_diversity": 0.15,    # Covered by how many different source types
    "credibility_avg": 0.15,     # Average credibility of covering sources
    "entity_density": 0.10,      # How many entities are involved
    "capital_signals": 0.15,     # Funding/market signals present
    "media_tier_coverage": 0.15, # Coverage by mainstream media
    "recency_momentum": 0.10,    # Most mentions are recent
}


def compute_volume_growth(daily_counts: list[int], window: int = 7) -> float:
    """Compute volume growth rate over a time window."""
    if len(daily_counts) < 2:
        return 0.0

    recent = daily_counts[-window:] if len(daily_counts) >= window else daily_counts
    older = daily_counts[:-window] if len(daily_counts) > window else [0]

    recent_avg = sum(recent) / max(len(recent), 1)
    older_avg = sum(older) / max(len(older), 1)

    if older_avg == 0:
        return min(recent_avg, 1.0)

    growth = (recent_avg - older_avg) / older_avg
    # Normalize to 0-1 range (log scale for large growth)
    if growth <= 0:
        return 0.0
    return min(math.log1p(growth) / 3.0, 1.0)


def compute_source_diversity(source_categories: list[str]) -> float:
    """How many different source categories cover this topic."""
    unique_cats = set(source_categories)
    all_categories = {"mainstream_media", "crypto_media", "ai_media", "institution", "enterprise", "regulation"}
    return len(unique_cats) / len(all_categories)


def compute_media_tier_coverage(source_categories: list[str]) -> float:
    """Proportion of high-tier media covering this topic."""
    high_tier = {"mainstream_media", "institution"}
    if not source_categories:
        return 0.0
    high_count = sum(1 for c in source_categories if c in high_tier)
    return high_count / len(source_categories)


def compute_recency_momentum(article_dates: list[datetime.datetime], total_days: int = 30) -> float:
    """How recent are the mentions (more recent = higher momentum)."""
    if not article_dates:
        return 0.0

    now = datetime.datetime.utcnow()
    # Weight recent articles more heavily
    total_weight = 0
    for date in article_dates:
        age_days = (now - date).days
        if age_days <= total_days:
            weight = 1.0 - (age_days / total_days)
            total_weight += weight

    # Normalize
    return min(total_weight / max(len(article_dates), 1), 1.0)


def analyze_narrative_strength(db: Session, topic: str, days: int = 30) -> dict:
    """Comprehensive narrative strength analysis for a topic/tag."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    # Get all articles with this tag
    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
        joinedload(Article.source),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.tags.cast(String).like(f'%"{topic}"%'),
    ).order_by(Article.published_at).all()

    if not articles:
        return {
            "topic": topic, "strength": 0.0, "level": "dormant",
            "factors": {}, "article_count": 0,
        }

    # Compute daily counts
    daily_counts_map = defaultdict(int)
    for a in articles:
        day = (a.published_at or a.fetched_at).strftime("%Y-%m-%d")
        daily_counts_map[day] += 1

    # Fill in missing days
    all_days = []
    current = since.date()
    end = datetime.date.today()
    while current <= end:
        all_days.append(daily_counts_map.get(current.strftime("%Y-%m-%d"), 0))
        current += datetime.timedelta(days=1)

    # Compute factors
    source_categories = [a.source.category for a in articles if a.source]
    article_dates = [a.published_at or a.fetched_at for a in articles]

    volume_growth = compute_volume_growth(all_days)
    source_diversity = compute_source_diversity(source_categories)
    credibility_avg = sum(a.source.credibility_score for a in articles if a.source) / max(len(articles), 1)
    entity_density = sum(
        len(a.classification.entities or []) for a in articles if a.classification
    ) / max(len(articles), 1)
    entity_density_norm = min(entity_density / 5.0, 1.0)

    capital_signals = sum(
        1 for a in articles
        if a.classification and a.classification.content_type in ("funding", "market_signal")
    ) / max(len(articles), 1)

    media_tier = compute_media_tier_coverage(source_categories)
    recency = compute_recency_momentum(article_dates, days)

    # Weighted total
    factors = {
        "volume_growth": round(volume_growth, 3),
        "source_diversity": round(source_diversity, 3),
        "credibility_avg": round(credibility_avg, 3),
        "entity_density": round(entity_density_norm, 3),
        "capital_signals": round(capital_signals, 3),
        "media_tier_coverage": round(media_tier, 3),
        "recency_momentum": round(recency, 3),
    }

    total_strength = sum(
        factors[k] * NARRATIVE_WEIGHTS[k] for k in NARRATIVE_WEIGHTS
    )

    # Classify strength level
    if total_strength >= 0.7:
        level = "explosive"
    elif total_strength >= 0.5:
        level = "strong"
    elif total_strength >= 0.3:
        level = "moderate"
    elif total_strength >= 0.15:
        level = "emerging"
    else:
        level = "weak"

    return {
        "topic": topic,
        "strength": round(total_strength, 3),
        "level": level,
        "factors": factors,
        "article_count": len(articles),
        "days_analyzed": days,
        "top_sources": Counter(source_categories).most_common(5),
        "daily_volume": all_days[-7:],  # last 7 days
    }


def get_narrative_leaderboard(db: Session, days: int = 14, top_n: int = 20) -> list[dict]:
    """Get all topics ranked by narrative strength."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    # Get all tags from recent articles
    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(Article.fetched_at >= since).all()

    tag_counter = Counter()
    for a in articles:
        if a.classification and a.classification.tags:
            for tag in a.classification.tags:
                tag_counter[tag] += 1

    # Only analyze tags with sufficient mentions
    results = []
    for tag, count in tag_counter.most_common(top_n * 2):
        if count < 3:
            continue
        strength_data = analyze_narrative_strength(db, tag, days=days)
        results.append(strength_data)

    # Sort by strength
    results.sort(key=lambda x: x["strength"], reverse=True)
    return results[:top_n]


def get_llm_narrative_analysis(db: Session, topic: str, days: int = 14) -> Optional[str]:
    """Use LLM to provide qualitative narrative analysis."""
    if not OPENAI_API_KEY:
        return None

    strength_data = analyze_narrative_strength(db, topic, days=days)

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    prompt = f"""分析以下话题的叙事强度数据，给出定性分析：

话题: {topic}
综合强度: {strength_data['strength']} ({strength_data['level']})
文章数: {strength_data['article_count']}
分析周期: {days}天

各因子得分:
- 提及量增长: {strength_data['factors'].get('volume_growth', 0)}
- 来源多样性: {strength_data['factors'].get('source_diversity', 0)}
- 来源可信度: {strength_data['factors'].get('credibility_avg', 0)}
- 实体密度: {strength_data['factors'].get('entity_density', 0)}
- 资本信号: {strength_data['factors'].get('capital_signals', 0)}
- 主流媒体覆盖: {strength_data['factors'].get('media_tier_coverage', 0)}
- 时效动量: {strength_data['factors'].get('recency_momentum', 0)}

请用中文输出:
1. 当前叙事阶段判断（早期概念/快速扩散/主流认知/过热/消退）
2. 推动叙事的关键力量
3. 潜在风险（是否有炒作嫌疑）
4. 未来30天预判
"""
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一位资深的 AI+Crypto 行业分析师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=600,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM narrative analysis error: {e}")
        return None

"""Rule-based scoring system."""
import logging
from sqlalchemy.orm import Session

from app.models import Article, Source, Classification, Score

logger = logging.getLogger(__name__)

# Scoring weights (configurable)
WEIGHTS = {
    "credibility": 0.20,
    "impact": 0.25,
    "execution": 0.15,
    "capital_signal": 0.15,
    "narrative_strength": 0.15,
    "risk": 0.10,
}


def score_credibility(article: Article, source: Source, classification: Classification) -> float:
    """
    Credibility: How trustworthy is this information?
    Based on: source credibility, content type, number of entities mentioned.
    """
    score = source.credibility_score  # Base from source (0-1)

    # Reports and official announcements are more credible
    if classification.content_type in ("report", "product_launch"):
        score = min(score + 0.1, 1.0)

    # Suspected hype reduces credibility
    if classification.hype_risk > 0.5:
        score = max(score - 0.3, 0.1)

    return round(score, 2)


def score_impact(article: Article, classification: Classification) -> float:
    """
    Impact: How wide-reaching is this news?
    Based on: content type, entities involved, regulation risk.
    """
    score = 0.4  # Base

    # High-impact content types
    high_impact = {"regulation", "funding", "partnership", "product_launch"}
    if classification.content_type in high_impact:
        score += 0.2

    # More entities = wider impact
    entities = classification.entities or []
    entity_bonus = min(len(entities) * 0.05, 0.2)
    score += entity_bonus

    # Regulation events have inherently higher impact
    if classification.regulation_risk > 0.5:
        score += 0.15

    return round(min(score, 1.0), 2)


def score_execution(article: Article, classification: Classification) -> float:
    """
    Execution/Groundedness: Is there real progress or just talk?
    Based on: content type, presence of concrete actions.
    """
    score = 0.4  # Base

    # Product launches and partnerships indicate execution
    execution_types = {"product_launch", "partnership", "funding"}
    if classification.content_type in execution_types:
        score += 0.3

    # Opinions and suspected hype indicate less execution
    talk_types = {"opinion", "suspected_hype", "person_speech"}
    if classification.content_type in talk_types:
        score -= 0.15

    # High hype risk = less execution
    score -= classification.hype_risk * 0.2

    return round(max(min(score, 1.0), 0.0), 2)


def score_capital_signal(article: Article, classification: Classification) -> float:
    """
    Capital Signal: Is money moving here?
    Based on: funding mentions, market signals, institutional involvement.
    """
    score = 0.3  # Base

    if classification.content_type == "funding":
        score += 0.4

    if classification.content_type == "market_signal":
        score += 0.2

    # Check for institutional entities
    entities = classification.entities or []
    institutional = ["a16z", "Grayscale", "VanEck", "Ark Invest", "Coinbase", "Binance"]
    if any(e.get("name") in institutional for e in entities):
        score += 0.15

    return round(min(score, 1.0), 2)


def score_narrative_strength(article: Article, classification: Classification) -> float:
    """
    Narrative Strength: How much attention is this topic getting?
    Based on: number of tags, content type, hype indicators.
    """
    score = 0.3  # Base

    tags = classification.tags or []
    tag_bonus = min(len(tags) * 0.08, 0.3)
    score += tag_bonus

    # Hype can indicate strong narrative (not necessarily good)
    score += classification.hype_risk * 0.2

    # Reports and opinions drive narrative
    if classification.content_type in ("report", "opinion", "person_speech"):
        score += 0.1

    return round(min(score, 1.0), 2)


def score_risk(article: Article, classification: Classification) -> float:
    """
    Risk: Potential negative outcomes or uncertainty.
    Based on: regulation risk, hype risk, content type.
    """
    score = 0.2  # Base

    score += classification.regulation_risk * 0.4
    score += classification.hype_risk * 0.3

    if classification.content_type == "regulation":
        score += 0.1

    return round(min(score, 1.0), 2)


def score_article(article: Article, db: Session) -> Score:
    """Calculate and save scores for an article."""
    source = db.query(Source).filter(Source.id == article.source_id).first()
    classification = article.classification

    if not classification:
        raise ValueError(f"Article {article.id} has no classification")

    credibility = score_credibility(article, source, classification)
    impact = score_impact(article, classification)
    execution = score_execution(article, classification)
    capital_signal = score_capital_signal(article, classification)
    narrative_strength = score_narrative_strength(article, classification)
    risk = score_risk(article, classification)

    # Weighted total
    total = (
        credibility * WEIGHTS["credibility"] +
        impact * WEIGHTS["impact"] +
        execution * WEIGHTS["execution"] +
        capital_signal * WEIGHTS["capital_signal"] +
        narrative_strength * WEIGHTS["narrative_strength"] +
        (1 - risk) * WEIGHTS["risk"]  # Lower risk contributes positively
    )

    score = Score(
        article_id=article.id,
        credibility=credibility,
        impact=impact,
        execution=execution,
        capital_signal=capital_signal,
        narrative_strength=narrative_strength,
        risk=risk,
        total_score=round(total, 2),
    )

    db.add(score)
    db.commit()
    db.refresh(score)
    return score


def score_unscored(db: Session) -> int:
    """Score all articles that have classification but no score yet."""
    articles = db.query(Article).filter(
        Article.id.in_(
            db.query(Classification.article_id)
        ),
        ~Article.id.in_(
            db.query(Score.article_id)
        )
    ).all()

    count = 0
    for article in articles:
        try:
            # Need to load classification
            article.classification = db.query(Classification).filter(
                Classification.article_id == article.id
            ).first()
            score_article(article, db)
            count += 1
        except Exception as e:
            logger.error(f"Scoring error for article {article.id}: {e}")
    return count

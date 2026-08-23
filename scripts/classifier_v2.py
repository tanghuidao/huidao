"""Content classification and tagging service (rule-based with word boundary matching)."""
import re
import logging
from sqlalchemy.orm import Session

from app.models import Article, Classification

logger = logging.getLogger(__name__)

# --- Tag Rules V2 ---
# Each rule: (tag_name, [exact_phrases], [word_boundary_keywords])
# exact_phrases: safe substring match for multi-word phrases
# word_boundary_keywords: matched with \b for short/ambiguous words
TAG_RULES = [
    ("AI Agent", ["ai agent", "autonomous agent", "agent protocol", "agent framework"], []),
    ("Agent Wallet", ["agent wallet", "ai wallet", "autonomous wallet"], []),
    ("Agent Payment", ["agent payment", "machine payment", "ai payment"], []),
    ("Decentralized Compute", ["decentralized compute", "distributed compute", "compute network", "gpu network"], []),
    ("DePIN", ["depin", "decentralized physical infrastructure"], []),
    ("Bittensor", ["bittensor"], ["tao", "$tao"]),
    ("Render", ["render network", "render token"], ["rndr", "$rndr"]),
    ("Akash", [], ["akash", "akt", "$akt"]),
    ("Worldcoin", ["worldcoin", "world coin"], ["world_id", "worldid", "$wld"]),
    ("Near AI", ["near ai", "near protocol ai", "near foundation"], []),
    ("Fetch.ai", ["fetch.ai", "fetch ai", "asi alliance"], ["$fet"]),
    ("Ritual", ["ritual net", "ritual protocol"], []),
    ("Gensyn", ["gensyn"], []),
    ("Web3", [], ["web3", "web 3"]),
    ("Web4.0", ["web4", "web 4.0", "web4.0"], []),
    ("Regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement action"], ["sec", "cftc", "mifid", "mica"]),
    ("Stablecoin", ["stablecoin"], ["usdt", "usdc", "tether", "circle"]),
    ("Identity", ["decentralized identity", "self-sovereign", "verifiable credential", "digital identity"], ["did", "ssi"]),
    ("Data Ownership", ["data ownership", "data sovereignty", "data rights", "personal data"], []),
    ("ZK", ["zero knowledge", "zero-knowledge", "zk-proof", "zkp", "zk rollup", "zkml"], []),
    ("Privacy", ["privacy", "confidential computing", "homomorphic"], ["fhe"]),
    ("Tokenomics", ["tokenomics", "token economics", "token model", "token design"], []),
    ("NFT", [], ["nft", "non-fungible"]),
    ("DeFi", ["decentralized finance", "lending protocol", "liquidity pool"], ["defi", "amm"]),
    ("Ethereum", ["ethereum"], ["$eth", "erc-20", "erc-721"]),
    ("Solana", ["solana"], ["$sol"]),
    ("Bitcoin", ["bitcoin"], ["btc", "$btc"]),
    ("OpenAI", ["openai", "chatgpt", "gpt-4", "gpt-5", "sam altman"], []),
    ("Anthropic", [], ["anthropic", "claude"]),
    ("Google AI", ["deepmind", "google ai", "gemini"], []),
    ("Nvidia", [], ["nvidia", "jensen huang", "cuda"]),
]

# --- Content Type Rules V2 ---
CONTENT_TYPE_RULES = [
    ("funding", ["raised", "funding round", "series a", "series b", "series c", "seed round", "venture capital", "investment round", "valuation"], []),
    ("regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement"], ["sec", "cftc"]),
    ("product_launch", ["launch", "release", "announce", "unveil", "debut", "mainnet", "testnet"], []),
    ("partnership", ["partner", "collaboration", "integrate", "alliance", "join force", "team up"], []),
    ("report", ["report", "research", "analysis", "whitepaper", "white paper", "study finds"], []),
    ("market_signal", ["price", "market cap", "trading volume", "all-time high", "rally"], ["ath", "bull", "bear"]),
    ("person_speech", ["said", "told", "according to", "believes", "predicts", "argues", "interview"], []),
    ("opinion", ["opinion", "editorial", "commentary", "perspective"], []),
    ("suspected_hype", ["revolutionary", "game-changing", "100x", "1000x", "to the moon", "guaranteed", "next big"], []),
    ("news", [], []),
]

# --- Hype Indicators ---
HYPE_INDICATORS = [
    "revolutionary", "game-changing", "disruptive", "100x", "1000x",
    "moon", "to the moon", "guaranteed", "next big thing", "massive gains",
    "don't miss", "hurry", "limited time", "exclusive", "secret",
    "infinity", "unstoppable", "inevitable",
]


def _match_rule(text_lower: str, exact_phrases: list, word_keywords: list) -> bool:
    """Check if text matches a rule using appropriate matching strategy."""
    for phrase in exact_phrases:
        if phrase in text_lower:
            return True
    for kw in word_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            return True
    return False


def classify_content_type(text: str) -> str:
    """Classify content type based on keywords."""
    text_lower = text.lower()
    for content_type, exact_phrases, word_keywords in CONTENT_TYPE_RULES:
        if _match_rule(text_lower, exact_phrases, word_keywords):
            return content_type
    return "news"


def extract_tags(text: str) -> list[str]:
    """Extract topic tags from text using word boundary matching."""
    text_lower = text.lower()
    tags = []
    for tag_name, exact_phrases, word_keywords in TAG_RULES:
        if _match_rule(text_lower, exact_phrases, word_keywords):
            tags.append(tag_name)
    return tags


def calculate_hype_risk(text: str) -> float:
    """Calculate hype risk score (0-1)."""
    text_lower = text.lower()
    matches = sum(1 for indicator in HYPE_INDICATORS if indicator in text_lower)
    return min(matches / 3.0, 1.0)


def calculate_regulation_risk(text: str, tags: list[str]) -> float:
    """Calculate regulation risk (0-1)."""
    score = 0.0
    text_lower = text.lower()

    if "Regulation" in tags:
        score += 0.4

    risk_words = ["ban", "enforcement", "lawsuit", "fine", "penalty", "crackdown", "illegal", "fraud"]
    matches = sum(1 for w in risk_words if w in text_lower)
    score += min(matches * 0.2, 0.6)

    return min(score, 1.0)


KNOWN_ENTITIES = {
    # People
    "Sam Altman": "person", "Vitalik Buterin": "person",
    "Jensen Huang": "person", "Brian Armstrong": "person",
    "Demis Hassabis": "person", "Yann LeCun": "person",
    "Balaji Srinivasan": "person", "Chris Dixon": "person",
    "Cathie Wood": "person", "Satya Nadella": "person",
    "Marc Andreessen": "person", "Arthur Hayes": "person",
    "Anatoly Yakovenko": "person", "Andrew Ng": "person",
    # Companies/Projects
    "OpenAI": "company", "Anthropic": "company",
    "Google": "company", "Microsoft": "company",
    "Nvidia": "company", "Meta": "company",
    "Coinbase": "company", "Binance": "company",
    "Circle": "company", "Tether": "company",
    "Bittensor": "project", "Render": "project",
    "Akash": "project", "Worldcoin": "project",
    "Fetch.ai": "project", "Gensyn": "project",
    "Ritual": "project", "Near": "project",
    "Near Protocol": "project",
    # Organizations
    "a16z": "organization", "Grayscale": "organization",
    "VanEck": "organization", "Ark Invest": "organization",
    "SEC": "organization", "CFTC": "organization",
    "Ethereum Foundation": "organization",
    "Solana Foundation": "organization",
}


def extract_entities(text: str) -> list[dict]:
    """Simple entity extraction based on known names."""
    found = []
    for name, entity_type in KNOWN_ENTITIES.items():
        if name.lower() in text.lower():
            found.append({"name": name, "type": entity_type})
    return found


def classify_article(article: Article, db: Session) -> Classification:
    """Classify a single article and save to DB."""
    text = f"{article.title} {article.raw_content or ''}"

    content_type = classify_content_type(text)
    tags = extract_tags(text)
    entities = extract_entities(text)
    hype_risk = calculate_hype_risk(text)
    regulation_risk = calculate_regulation_risk(text, tags)

    topics = tags[:5] if tags else ["General"]

    classification = Classification(
        article_id=article.id,
        content_type=content_type,
        tags=tags,
        entities=entities,
        topics=topics,
        hype_risk=hype_risk,
        regulation_risk=regulation_risk,
    )

    db.add(classification)
    db.commit()
    db.refresh(classification)
    return classification


def classify_unclassified(db: Session) -> int:
    """Classify all articles that don't have a classification yet."""
    articles = db.query(Article).filter(
        ~Article.id.in_(
            db.query(Classification.article_id)
        )
    ).all()

    count = 0
    for article in articles:
        try:
            classify_article(article, db)
            count += 1
        except Exception as e:
            logger.error(f"Classification error for article {article.id}: {e}")
    return count


def retag_recent_articles(db: Session, days: int = 7, limit: int = 2000) -> int:
    """Re-tag recent articles with improved classifier."""
    import datetime
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    articles = db.query(Article).join(Classification).filter(
        Classification.article_id == Article.id,
        Article.fetched_at >= since,
    ).limit(limit).all()

    updated = 0
    for article in articles:
        text = f"{article.title} {article.raw_content or ''}"
        new_tags = extract_tags(text)
        new_type = classify_content_type(text)
        new_entities = extract_entities(text)

        c = article.classification
        if c:
            old_tags = set(c.tags or [])
            new_tags_set = set(new_tags)
            if old_tags != new_tags_set or c.content_type != new_type:
                c.tags = new_tags
                c.content_type = new_type
                c.topics = new_tags[:5] if new_tags else ["General"]
                c.entities = new_entities
                c.hype_risk = calculate_hype_risk(text)
                c.regulation_risk = calculate_regulation_risk(text, new_tags)
                updated += 1

    db.commit()
    return updated

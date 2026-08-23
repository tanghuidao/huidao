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
    ("AI Agent", ["ai agent", "autonomous agent", "agent protocol", "agent framework", "智能体", "ai代理"], []),
    ("Agent Wallet", ["agent wallet", "ai wallet", "autonomous wallet"], []),
    ("Agent Payment", ["agent payment", "machine payment", "ai payment"], []),
    ("Decentralized Compute", ["decentralized compute", "distributed compute", "compute network", "gpu network", "去中心化算力", "分布式计算"], []),
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
    ("Regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement action",
                    "监管", "合规", "立法", "执法", "证监会", "金融监管"], ["sec", "cftc", "mifid", "mica", "esma", "fca"]),
    ("Stablecoin", ["stablecoin", "稳定币"], ["usdt", "usdc", "tether", "circle"]),
    ("Identity", ["decentralized identity", "self-sovereign", "verifiable credential", "digital identity", "去中心化身份"], ["did", "ssi"]),
    ("Data Ownership", ["data ownership", "data sovereignty", "data rights", "personal data", "数据主权", "数据确权"], []),
    ("ZK", ["zero knowledge", "zero-knowledge", "zk-proof", "zkp", "zk rollup", "zkml", "零知识证明"], []),
    ("Privacy", ["privacy", "confidential computing", "homomorphic", "隐私计算", "全同态加密"], ["fhe"]),
    ("Tokenomics", ["tokenomics", "token economics", "token model", "token design", "代币经济"], []),
    ("NFT", ["数字藏品", "nft"], ["non-fungible"]),
    ("DeFi", ["decentralized finance", "lending protocol", "liquidity pool", "去中心化金融", "流动性池"], ["defi", "amm"]),
    ("Ethereum", ["ethereum", "以太坊"], ["$eth", "erc-20", "erc-721"]),
    ("Solana", ["solana", "索拉纳"], ["$sol"]),
    ("Bitcoin", ["bitcoin", "比特币"], ["btc", "$btc"]),
    ("OpenAI", ["openai", "chatgpt", "gpt-4", "gpt-5", "sam altman"], []),
    ("Anthropic", [], ["anthropic", "claude"]),
    ("Google AI", ["deepmind", "google ai", "gemini"], []),
    ("Nvidia", ["英伟达"], ["nvidia", "jensen huang", "cuda"]),
]

# --- Content Type Rules V2 ---
# Order matters: more specific rules first
CONTENT_TYPE_RULES = [
    ("regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement",
                    "监管", "合规", "立法", "执法行动", "罚款", "处罚", "禁令", "证监会", "金融监管"],
                   ["sec", "cftc", "esma", "fca", "mifid", "mica"]),
    ("funding", ["funding round", "seed round", "venture capital", "investment round",
                 "融资", "投资轮", "募资"], ["ipo"]),
    # NOTE: bare "raised"/"valuation" removed (matched "prices raised", "valuation remains
    # high" in politics/macro news). Amount-anchored funding patterns live in
    # FUNDING_PATTERNS below and are checked inside classify_content_type().
    ("product_launch", ["launch", "release", "unveil", "debut", "mainnet", "testnet",
                        "上线", "发布", "推出", "主网"], []),
    ("partnership", ["partner", "collaboration", "integrate", "alliance", "join force", "team up",
                     "合作", "战略伙伴", "集成", "联盟"], []),
    ("report", ["report", "research", "analysis", "whitepaper", "white paper", "study finds",
                "报告", "研报", "白皮书", "分析"], []),
    ("market_signal", ["price", "market cap", "trading volume", "all-time high", "rally",
                       "价格", "市值", "成交量", "新高", "暴涨", "暴跌", "涨幅", "跌幅"],
                      ["ath", "bull", "bear"]),
    ("person_speech", ["said", "told", "according to", "believes", "predicts", "argues", "interview",
                       "表示", "认为", "预测", "称", "接受采访"], []),
    ("opinion", ["opinion", "editorial", "commentary", "perspective", "观点", "评论", "社论"], []),
    ("suspected_hype", ["100x", "1000x", "to the moon", "梭哈", "稳赚", "零风险",
                        "一夜暴富", "财富自由", "百倍", "千倍", "万倍"],
     ["ponzi", "rug pull", "shill", "mooning", "lambo"]),
    ("news", [], []),
]

# --- Hype Indicators (EN + ZH) ---
# Phrase indicators: strong crypto/Ponzi language only. Generic words like
# "exclusive", "secret", "moon", "breakthrough", "inevitable", "explosive" were
# removed because they matched normal journalism (podcast descriptions, space
# articles, book reviews) and polluted the suspected-hype panel.
HYPE_INDICATORS = [
    # English
    "100x", "1000x", "to the moon", "guaranteed returns", "get rich quick",
    "financial freedom", "don't miss out", "limited time offer", "overnight riches",
    # Chinese
    "百倍", "千倍", "万倍", "一夜暴富", "财富自由", "稳赚", "保本", "零风险",
    "无风险", "暴涨", "疯涨", "梭哈", "无脑冲", "躺赚", "错过后悔",
    "内幕消息", "王炸", "核弹级", "史诗级",
]

# Word-boundary indicators (short/ambiguous English words that must not match
# inside longer words, e.g. "mooning" but never "moon landing")
HYPE_WORD_KEYWORDS = ["ponzi", "rug pull", "shill", "mooning", "lambo", "diamond hands"]


# --- Funding amount patterns (regex, amount-anchored) ---
# Only treat "raise/valuation" language as funding when tied to a concrete
# amount, so "prices raised concerns" / "valuation remains high" no longer
# misclassify politics and macro news as funding.
FUNDING_PATTERNS = [
    # raised $100M / raises over $100 billion; but NOT "raises tariffs/taxes/
    # prices/rates on $50 billion" (trade-war and pricing news)
    r"\brais(e|es|ed|ing)\b(?!\s+(tariff|tariffs|tax|taxes|duty|duties|price|prices|"
    r"rate|rates|interest|concern|concerns|question|questions|alarm|alarms|doubt|doubts))"
    r"(?:\s+\w+){0,3}?\s+(\$|£|€|¥)?\s*\d",
    r"\b(secur|securing|secures|secured)\s+(\$|£|€|¥)?\s*\d",     # secures $25M
    r"\b(nets?|netted)\s+(\$|£|€|¥)?\s*\d",                       # nets $30M round
    r"\bvalued at\s+(\$|£|€|¥)?\s*\d",                            # valued at $2 trillion
    r"\bvaluation of\s+(\$|£|€|¥)?\s*\d",
    r"\bseries\s+[abc]\b",                                         # series A/B/C
    r"\bipo\b",                                                     # IPO event
    r"完成[^。；，]{0,15}融资",                                      # 完成2.5亿美元融资
    r"获得[^。；，]{0,12}(融资|投资)",
    r"(领投|参投|跟投)",
    r"(种子轮|天使轮|新一轮融资|pre-?[ABC]轮|[ABC]轮融资)",
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


def _matches_funding_pattern(text_lower: str) -> bool:
    """Check if text contains an amount-anchored funding pattern."""
    return any(re.search(p, text_lower) for p in FUNDING_PATTERNS)


def classify_content_type(text: str) -> str:
    """Classify content type based on keywords."""
    text_lower = text.lower()
    for content_type, exact_phrases, word_keywords in CONTENT_TYPE_RULES:
        if content_type == "funding":
            # Funding matches either a strong rule phrase (funding round, 融资,
            # IPO, ...) or an amount-anchored pattern (raised $30M, valued at
            # $2T, 完成X亿美元融资, ...).
            if _match_rule(text_lower, exact_phrases, word_keywords) or \
                    _matches_funding_pattern(text_lower):
                return content_type
            continue
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
    """Calculate hype risk score (0-1), continuous scoring.

    Requires at least 2 distinct hype indicators to produce a non-zero score,
    so a single generic word can no longer push an article into the
    suspected-hype panel.
    """
    text_lower = text.lower()
    matches = sum(1 for indicator in HYPE_INDICATORS if indicator in text_lower)
    matches += sum(1 for kw in HYPE_WORD_KEYWORDS
                   if re.search(r'\b' + re.escape(kw) + r'\b', text_lower))
    if matches < 2:
        return 0.0
    # 2 matches=0.4, 3=0.6, 4=0.8, 5+=1.0
    return round(min(matches * 0.2, 1.0), 3)


# Regulation risk keywords - soft signals (substring-safe phrases only).
# NOTE: "ban" and "fine" moved to word-boundary list: as substrings they matched
# "bank"/"banking"/"finance"/"defined" and inflated scores on ordinary news.
REGULATION_RISK_WORDS = [
    # English - crypto regulation
    "enforcement", "lawsuit", "penalty", "crackdown", "illegal", "fraud", "sanction",
    "subpoena", "investigation",
    # English - traditional finance regulation
    "securities violation", "insider trading", "market manipulation",
    "unregistered securities", "cease and desist", "regulatory action",
    "compliance failure",
    # Chinese - crypto/finance regulation
    "禁止", "处罚", "罚款", "违规", "违法", "调查", "制裁",
    "监管处罚", "行政处罚", "整改", "约谈", "叫停",
]

# Short/ambiguous soft words that need word-boundary matching
REGULATION_RISK_BOUNDARY_WORDS = ["ban", "bans", "banned", "fine", "fined"]

# Hard signals - strongly indicative of enforcement/criminal proceedings.
# Weighted higher than soft words.
REGULATION_HARD_WORDS = [
    "indictment", "prosecution", "ponzi",
    "非法集资", "传销", "洗钱", "内幕交易", "操纵市场", "刑事", "立案", "起诉",
]

# Regulatory bodies (word-boundary matched)
REGULATORY_BODIES = [
    "sec", "cftc", "esma", "fca", "finra", "occ", "fdic", "fed",
    "证监会", "银保监会", "央行", "金融监管总局", "外管局",
    "sfc", "mas", "fsa", "baFin", "amf",
]


def calculate_regulation_risk(text: str, tags: list[str]) -> float:
    """Calculate regulation risk (0-1) with continuous, non-saturating scoring.

    Uses square-root dampening on each signal group so scores spread across a
    wide range instead of piling up at a single saturated value (the old
    0.3+0.45+0.2 cap made every high-risk article score exactly 0.95).
    Theoretical max: 0.25 (tag) + 0.40 (soft) + 0.20 (hard) + 0.15 (bodies) = 1.0
    """
    text_lower = text.lower()
    score = 0.0

    # Tag-based signal
    if "Regulation" in tags:
        score += 0.25

    # Soft keyword matches (sqrt dampening: 1→0.20, 2→0.28, 4→0.40 cap)
    soft = sum(1 for w in REGULATION_RISK_WORDS if w in text_lower)
    soft += sum(1 for w in REGULATION_RISK_BOUNDARY_WORDS
                if re.search(r'\b' + re.escape(w) + r'\b', text_lower))
    score += min(0.20 * (soft ** 0.5), 0.40)

    # Hard signals (sqrt dampening: 1→0.15, 2→0.20 cap)
    hard = sum(1 for w in REGULATION_HARD_WORDS if w in text_lower)
    score += min(0.15 * (hard ** 0.5), 0.20)

    # Regulatory body mention (sqrt dampening: 1→0.12, 2→0.15 cap)
    body_matches = sum(1 for b in REGULATORY_BODIES
                       if re.search(r'\b' + re.escape(b) + r'\b', text_lower))
    score += min(0.12 * (body_matches ** 0.5), 0.15)

    return round(min(score, 1.0), 3)


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
    # Organizations (short names use word boundary)
    "a16z": "organization", "Grayscale": "organization",
    "VanEck": "organization", "Ark Invest": "organization",
    "SEC": "organization", "CFTC": "organization",
    "ESMA": "organization", "FCA": "organization",
    "Ethereum Foundation": "organization",
    "Solana Foundation": "organization",
}

# Entities with short/ambiguous names that need word-boundary matching
_BOUNDARY_ENTITIES = {"SEC", "CFTC", "ESMA", "FCA", "Meta", "Near", "a16z"}


def extract_entities(text: str) -> list[dict]:
    """Entity extraction with word-boundary matching for short names."""
    found = []
    text_lower = text.lower()
    for name, entity_type in KNOWN_ENTITIES.items():
        if name in _BOUNDARY_ENTITIES:
            # Use word boundary to avoid false positives (secret, sector, second, etc.)
            if re.search(r'\b' + re.escape(name.lower()) + r'\b', text_lower):
                found.append({"name": name, "type": entity_type})
        else:
            if name.lower() in text_lower:
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
    ).order_by(Article.id.desc()).limit(limit).all()

    updated = 0
    for article in articles:
        text = f"{article.title} {article.raw_content or ''}"
        new_tags = extract_tags(text)
        new_type = classify_content_type(text)
        new_entities = extract_entities(text)
        new_hype = calculate_hype_risk(text)
        new_reg = calculate_regulation_risk(text, new_tags)

        c = article.classification
        if c:
            c.tags = new_tags
            c.content_type = new_type
            c.topics = new_tags[:5] if new_tags else ["General"]
            c.entities = new_entities
            c.hype_risk = new_hype
            c.regulation_risk = new_reg
            updated += 1

    db.commit()
    return updated

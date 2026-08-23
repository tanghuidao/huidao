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
    ("funding", ["raised", "funding round", "series a", "series b", "series c", "seed round",
                 "venture capital", "investment round", "valuation", "融资", "估值", "投资轮"], []),
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
    ("suspected_hype", ["revolutionary", "game-changing", "100x", "1000x", "to the moon",
                        "guaranteed", "next big", "颠覆性", "百倍", "千倍", "暴涨", "稳赚"], []),
    ("news", [], []),
]

# --- Hype Indicators (EN + ZH) ---
HYPE_INDICATORS = [
    # English
    "revolutionary", "game-changing", "disruptive", "100x", "1000x",
    "moon", "to the moon", "guaranteed", "next big thing", "massive gains",
    "don't miss", "hurry", "limited time", "exclusive", "secret",
    "infinity", "unstoppable", "inevitable", "breakthrough", "explosive",
    "once in a lifetime", "get rich", "financial freedom",
    # Chinese
    "颠覆性", "革命性", "百倍币", "千倍币", "万倍", "暴涨", "飙升", "疯涨",
    "稳赚", "保本", "零风险", "错过后悔", "限时", "独家", "内幕",
    "财富自由", "一夜暴富", "躺赚", "无脑冲", "all in", "梭哈",
    "史诗级", "现象级", "王炸", "核弹级", "破天荒",
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
    """Calculate hype risk score (0-1), continuous scoring."""
    text_lower = text.lower()
    matches = sum(1 for indicator in HYPE_INDICATORS if indicator in text_lower)
    # Continuous: each match adds 0.12, cap at 1.0
    # 1 match=0.12, 3=0.36, 5=0.60, 8+=1.0
    return min(matches * 0.12, 1.0)


# Regulation risk keywords (EN + ZH + traditional finance)
REGULATION_RISK_WORDS = [
    # English - crypto regulation
    "ban", "enforcement", "lawsuit", "fine", "penalty", "crackdown", "illegal", "fraud",
    "sanction", "prosecution", "indictment", "subpoena", "investigation",
    # English - traditional finance regulation
    "securities violation", "insider trading", "market manipulation", "unregistered securities",
    "cease and desist", "regulatory action", "compliance failure",
    # Chinese - crypto/finance regulation
    "禁止", "处罚", "罚款", "违规", "违法", "调查", "起诉", "制裁",
    "监管处罚", "行政处罚", "刑事", "立案", "整改", "约谈", "叫停",
    "非法集资", "传销", "洗钱", "内幕交易", "操纵市场",
]

# Regulatory bodies (word-boundary matched)
REGULATORY_BODIES = [
    "sec", "cftc", "esma", "fca", "finra", "occ", "fdic", "fed",
    "证监会", "银保监会", "央行", "金融监管总局", "外管局",
    "sfc", "mas", "fsa", "baFin", "amf",
]


def calculate_regulation_risk(text: str, tags: list[str]) -> float:
    """Calculate regulation risk (0-1) across all sources."""
    score = 0.0
    text_lower = text.lower()

    # Tag-based signal
    if "Regulation" in tags:
        score += 0.3

    # Keyword matches (continuous)
    matches = sum(1 for w in REGULATION_RISK_WORDS if w in text_lower)
    score += min(matches * 0.15, 0.45)

    # Regulatory body mention (word boundary)
    body_matches = sum(1 for b in REGULATORY_BODIES
                       if re.search(r'\b' + re.escape(b) + r'\b', text_lower))
    score += min(body_matches * 0.1, 0.25)

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

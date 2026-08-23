"""Fix classifier.py - use word boundary matching for short keywords."""
import sys
sys.path.insert(0, '/app')

import re
import logging
from typing import Optional
from collections import Counter
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Source, Article, Classification

logger = logging.getLogger(__name__)

# --- Improved Tag Rules ---
# Each rule: (tag_name, [exact_phrases], [word_boundary_keywords])
# exact_phrases: matched as substring (safe for multi-word phrases)
# word_boundary_keywords: matched with \b word boundaries (for short/ambiguous words)
TAG_RULES_V2 = [
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
    ("Web3", [], ["web3", "web 3", "decentralized web"]),
    ("Web4.0", ["web4", "web 4.0", "web4.0"], []),
    ("Regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement action"], ["sec", "cftc", "mifid", "mica"]),
    ("Stablecoin", ["stablecoin"], ["usdt", "usdc", "tether", "circle", "$dai"]),
    ("Identity", ["decentralized identity", "self-sovereign", "verifiable credential", "digital identity"], ["did", "ssi"]),
    ("Data Ownership", ["data ownership", "data sovereignty", "data rights", "personal data"], []),
    ("ZK", ["zero knowledge", "zero-knowledge", "zk-proof", "zkp", "zk rollup", "zkml"], []),
    ("Privacy", ["privacy", "confidential computing", "homomorphic"], ["fhe"]),
    ("Tokenomics", ["tokenomics", "token economics", "token model", "token design"], []),
    ("NFT", [], ["nft", "non-fungible"]),
    ("DeFi", ["decentralized finance", "lending protocol", "liquidity pool"], ["defi", "amm"]),
    ("Ethereum", [], ["ethereum", "$eth", "erc-20", "erc-721"]),
    ("Solana", [], ["solana", "$sol"]),
    ("Bitcoin", [], ["bitcoin", "btc", "$btc"]),
    ("OpenAI", ["openai", "chatgpt", "gpt-4", "gpt-5", "sam altman"], []),
    ("Anthropic", [], ["anthropic", "claude"]),
    ("Google AI", ["deepmind", "google ai", "gemini"], []),
    ("Nvidia", [], ["nvidia", "jensen huang", "cuda"]),
]


def _match_rule(text_lower: str, exact_phrases: list[str], word_keywords: list[str]) -> bool:
    """Check if text matches a tag rule.

    - exact_phrases: simple substring match (safe for multi-word phrases)
    - word_keywords: word boundary match (prevents 'did' matching 'did something')
    """
    for phrase in exact_phrases:
        if phrase in text_lower:
            return True
    for kw in word_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            return True
    return False


def extract_tags_v2(text: str) -> list[str]:
    """Extract topic tags using improved matching."""
    text_lower = text.lower()
    tags = []
    for tag_name, exact_phrases, word_keywords in TAG_RULES_V2:
        if _match_rule(text_lower, exact_phrases, word_keywords):
            tags.append(tag_name)
    return tags


# --- Content Type Rules (also tightened) ---
CONTENT_TYPE_RULES_V2 = [
    ("funding", ["raised", "funding round", "series a", "series b", "series c", "seed round", "venture capital", "investment round", "valuation"], []),
    ("regulation", ["regulation", "regulatory", "compliance", "legislation", "enforcement", "approved"], ["sec", "cftc"]),
    ("product_launch", ["launch", "release", "announce", "unveil", "debut", "mainnet", "testnet"], []),
    ("partnership", ["partner", "collaboration", "integrate", "alliance", "join force", "team up"], []),
    ("report", ["report", "research", "analysis", "whitepaper", "white paper", "study finds"], []),
    ("market_signal", ["price", "market cap", "trading volume", "all-time high", "rally"], ["ath", "bull", "bear"]),
    ("person_speech", ["said", "told", "according to", "believes", "predicts", "argues", "interview"], []),
    ("opinion", ["opinion", "editorial", "commentary", "perspective"], []),
    ("suspected_hype", ["revolutionary", "game-changing", "100x", "1000x", "to the moon", "guaranteed", "next big"], []),
    ("news", [], []),
]


def classify_content_type_v2(text: str) -> str:
    """Classify content type using improved matching."""
    text_lower = text.lower()
    for content_type, exact_phrases, word_keywords in CONTENT_TYPE_RULES_V2:
        if _match_rule(text_lower, exact_phrases, word_keywords):
            return content_type
    return "news"


# --- Test the fix ---
print("=== 测试新分类器 ===\n")

# Test on the problematic articles
problematic_ids = [8594, 8593, 8591, 8589, 8585, 8584]
db = SessionLocal()

for aid in problematic_ids:
    a = db.query(Article).filter(Article.id == aid).first()
    if a:
        text = f"{a.title} {a.raw_content or ''}"
        old_tags = a.classification.tags if a.classification else []
        new_tags = extract_tags_v2(text)
        old_type = a.classification.content_type if a.classification else "?"
        new_type = classify_content_type_v2(text)
        print(f"  [{aid}] {a.title[:60]}")
        print(f"    旧标签: {old_tags}")
        print(f"    新标签: {new_tags}")
        print(f"    旧类型: {old_type} -> 新类型: {new_type}")
        print()

# Test on a larger sample to compare tag distribution
print("=== 新旧标签分布对比 (最近500篇) ===\n")
recent_articles = db.query(Article).order_by(Article.fetched_at.desc()).limit(500).all()

old_tag_counts = Counter()
new_tag_counts = Counter()

for a in recent_articles:
    text = f"{a.title} {a.raw_content or ''}"
    if a.classification and a.classification.tags:
        for t in a.classification.tags:
            old_tag_counts[t] += 1
    new_tags = extract_tags_v2(text)
    for t in new_tags:
        new_tag_counts[t] += 1

print(f"{'标签':<20} {'旧(500篇)':<12} {'新(500篇)':<12} {'变化'}")
print("-" * 60)
all_tags = set(list(old_tag_counts.keys()) + list(new_tag_counts.keys()))
for tag in sorted(all_tags, key=lambda x: old_tag_counts.get(x, 0) + new_tag_counts.get(x, 0), reverse=True):
    old_c = old_tag_counts.get(tag, 0)
    new_c = new_tag_counts.get(tag, 0)
    diff = new_c - old_c
    sign = "+" if diff > 0 else ""
    print(f"  {tag:<18} {old_c:<12} {new_c:<12} {sign}{diff}")

db.close()

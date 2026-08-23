"""LLM-based summarization service."""
import logging
import re
from typing import Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.models import Article

logger = logging.getLogger(__name__)


def get_llm_client() -> Optional[OpenAI]:
    """Get OpenAI client if API key is configured."""
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured, LLM features disabled")
        return None
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


SUMMARY_PROMPT = """你是一个专业的AI+Crypto/Web3行业分析师。请对以下文章进行分析摘要。

文章标题: {title}
文章内容: {content}

请严格按以下格式输出（不要使用markdown标题符#或**，直接输出纯文本）：

一句话摘要: [用一句话概括文章核心信息，不超过50字，不要用括号]
关键事实: [列出2-3个关键事实点，用逗号分隔]
涉及主体: [提及的公司、项目、人物，用逗号分隔]
可能影响: [对行业的潜在影响，1-2句话]
是否值得继续跟踪: [是/否，并说明原因]
噪音/炒作风险: [低/中/高，并说明判断依据]
"""


def _extract_one_line_summary(summary: str) -> Optional[str]:
    """Robustly extract one-line summary from LLM output.

    Handles multiple formats:
    - "一句话摘要: 内容" or "一句话摘要：内容"
    - "### 一句话摘要\\n内容" (header + next line)
    - "**一句话摘要** 内容"
    """
    lines = summary.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Strip markdown formatting
        stripped = re.sub(r'^[#*\s]+', '', stripped).strip()

        if "一句话摘要" in stripped:
            # Case 1: "一句话摘要: 内容" on the same line
            for sep in [":", "："]:
                if sep in stripped:
                    after_sep = stripped.split(sep, 1)[-1].strip()
                    # Remove any remaining markdown formatting
                    after_sep = re.sub(r'[*#\[\]]+', '', after_sep).strip()
                    if after_sep and len(after_sep) > 3:
                        return after_sep[:200]

            # Case 2: Header only, content on next line
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                next_line = re.sub(r'^[#*\s\[\]]+', '', next_line).strip()
                next_line = re.sub(r'[#\*\[\]]+', '', next_line).strip()
                if next_line and len(next_line) > 3 and "关键事实" not in next_line:
                    return next_line[:200]

    return None


def summarize_article(article: Article, db: Session) -> str:
    """Generate LLM summary for an article."""
    client = get_llm_client()
    if not client:
        return _fallback_summary(article)

    content = article.raw_content or article.title
    # Truncate very long content
    if len(content) > 4000:
        content = content[:4000] + "..."

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的AI+Crypto/Web3行业分析师，擅长从海量信息中提取关键洞察。请用纯文本输出，不要使用markdown格式符号。"},
                {"role": "user", "content": SUMMARY_PROMPT.format(
                    title=article.title,
                    content=content,
                )}
            ],
            temperature=0.3,
            max_tokens=800,
        )

        summary = response.choices[0].message.content
        article.summary = summary

        # Robust one-line summary extraction
        one_line = _extract_one_line_summary(summary)
        if one_line:
            article.one_line_summary = one_line
        else:
            # Fallback: use first 80 chars of content as summary
            logger.warning(f"Could not extract one-line summary for article {article.id}, using fallback")
            article.one_line_summary = (article.title or content[:80]).strip()

        db.commit()
        return summary

    except Exception as e:
        logger.error(f"LLM summarization error for article {article.id}: {e}")
        return _fallback_summary(article)


def _fallback_summary(article: Article) -> str:
    """Simple fallback when LLM is not available."""
    content = article.raw_content or ""
    # Take first 200 chars as summary
    summary = content[:200].strip()
    if len(content) > 200:
        summary += "..."
    return summary


def summarize_batch(db: Session, article_ids: list[int] = None, limit: int = 20) -> int:
    """Summarize multiple articles."""
    query = db.query(Article).filter(Article.summary.is_(None)).order_by(Article.id.desc())
    if article_ids:
        query = query.filter(Article.id.in_(article_ids))

    articles = query.limit(limit).all()
    count = 0

    for article in articles:
        try:
            summarize_article(article, db)
            count += 1
        except Exception as e:
            logger.error(f"Batch summarize error for article {article.id}: {e}")

    return count


def fix_bad_summaries(db: Session, limit: int = 100) -> dict:
    """Find and fix articles with bad/empty one_line_summary.

    Bad summaries include: empty, just markdown symbols, too short, etc.
    """
    bad_patterns = [
        r'^[#*\s]*$',           # Only markdown symbols or whitespace
        r'^\*+$',               # Just asterisks
        r'^#+$',                # Just hash marks
        r'^\[.*\]$',            # Just brackets
        r'^一句话摘要',          # The header itself
    ]

    # Find articles with potentially bad one_line_summary
    articles_to_fix = db.query(Article).filter(
        (Article.one_line_summary.is_(None)) |
        (Article.one_line_summary == '') |
        (Article.one_line_summary.like('###%')) |
        (Article.one_line_summary.like('**%')) |
        (Article.one_line_summary.like('['))
    ).limit(limit).all()

    fixed = 0
    skipped = 0

    for article in articles_to_fix:
        ols = article.one_line_summary or ''

        # Check if it matches any bad pattern
        is_bad = False
        if not ols or len(ols.strip()) < 4:
            is_bad = True
        else:
            for pattern in bad_patterns:
                if re.match(pattern, ols.strip()):
                    is_bad = True
                    break

        if not is_bad:
            skipped += 1
            continue

        # Try to re-extract from existing summary
        if article.summary:
            one_line = _extract_one_line_summary(article.summary)
            if one_line:
                article.one_line_summary = one_line
                fixed += 1
                continue

        # Fallback to title
        article.one_line_summary = article.title or 'No summary available'
        fixed += 1

    db.commit()
    return {"found": len(articles_to_fix), "fixed": fixed, "skipped": skipped}

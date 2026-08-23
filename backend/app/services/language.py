"""Multi-language content processing: detection and translation."""
import logging
import re
from typing import Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from app.models import Article

logger = logging.getLogger(__name__)


def _has_cjk(text: str) -> bool:
    """Quick check if text contains significant CJK characters."""
    if not text:
        return False
    cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text[:500]))
    return cjk_count > len(text[:500]) * 0.1


def detect_language(text: str) -> str:
    """Detect the language of a text. Uses CJK heuristic first, then langdetect."""
    if not text or len(text.strip()) < 10:
        return "en"  # Default fallback

    # Fast CJK heuristic (no external dependency)
    if _has_cjk(text):
        return "zh-cn"

    try:
        from langdetect import detect
        lang = detect(text[:2000])
        return lang
    except Exception:
        return "en"


def get_llm_client() -> Optional[OpenAI]:
    """Get OpenAI client."""
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


TRANSLATE_PROMPT = """请将以下{source_lang}文本翻译为{target_lang}。保持原文的专业术语和语义准确性。
只输出翻译结果，不要添加任何解释。

原文：
{text}
"""


def translate_text(text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
    """Translate text using LLM."""
    client = get_llm_client()
    if not client:
        return text  # Return original if no LLM

    lang_names = {
        "en": "英文", "zh": "中文", "zh-cn": "中文", "ja": "日文",
        "ko": "韩文", "fr": "法文", "de": "德文", "es": "西班牙文",
    }
    source_name = lang_names.get(source_lang, source_lang)
    target_name = lang_names.get(target_lang, target_lang)

    try:
        # Truncate very long text
        if len(text) > 5000:
            text = text[:5000] + "..."

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业翻译，擅长AI、Crypto和Web3领域的术语翻译。"},
                {"role": "user", "content": TRANSLATE_PROMPT.format(
                    source_lang=source_name,
                    target_lang=target_name,
                    text=text,
                )}
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text


def process_article_language(article: Article, db: Session) -> None:
    """Detect language and translate if needed."""
    text = f"{article.title} {article.raw_content or ''}"

    # Detect language
    detected_lang = detect_language(text)
    article.language = detected_lang

    # If not Chinese, add Chinese translation to summary context
    if detected_lang not in ("zh-cn", "zh-tw", "zh"):
        # Translate title for better searchability
        translated_title = translate_text(article.title, source_lang=detected_lang, target_lang="zh")
        # Store translated title in one_line_summary if not yet set
        if not article.one_line_summary:
            article.one_line_summary = translated_title

    db.commit()


def batch_detect_languages(db: Session, limit: int = 100) -> int:
    """Detect languages for articles that still have the default 'en' language.
    
    Fixed: no longer requires raw_content — uses title for detection when
    raw_content is missing. This ensures Chinese articles without raw_content
    (e.g. from RSS feeds that only provide title) get correctly detected.
    """
    articles = db.query(Article).filter(
        Article.language == "en",
    ).order_by(Article.id.desc()).limit(limit).all()

    count = 0
    for article in articles:
        try:
            # Use title + raw_content if available, title alone otherwise
            text = article.title or ""
            if article.raw_content:
                text = f"{text} {article.raw_content}"

            if not text.strip():
                continue

            detected = detect_language(text)
            if detected != article.language:
                article.language = detected
                count += 1
        except Exception as e:
            logger.error(f"Language detection error for article {article.id}: {e}")

    db.commit()
    return count


def batch_translate_titles(db: Session, limit: int = 50) -> int:
    """Translate non-Chinese article titles for better accessibility."""
    articles = db.query(Article).filter(
        Article.language != "zh-cn",
        Article.language != "zh-tw",
        Article.language != "zh",
        Article.one_line_summary.is_(None),
        Article.title.isnot(None),
    ).limit(limit).all()

    count = 0
    for article in articles:
        try:
            translated = translate_text(article.title, source_lang=article.language, target_lang="zh")
            if translated and translated != article.title:
                article.one_line_summary = translated
                count += 1
        except Exception as e:
            logger.error(f"Translation error for article {article.id}: {e}")

    db.commit()
    return count

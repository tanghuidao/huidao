"""PDF report parsing service."""
import datetime
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Article, Source
from app.config import DATA_DIR

logger = logging.getLogger(__name__)


def parse_pdf_content(pdf_path: str) -> Optional[dict]:
    """Extract text content from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        pages_text = []
        metadata = doc.metadata

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            if text.strip():
                pages_text.append(text)

        doc.close()

        full_text = "\n\n".join(pages_text)

        return {
            "title": metadata.get("title", "") or Path(pdf_path).stem,
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "creation_date": metadata.get("creationDate", ""),
            "page_count": len(pages_text),
            "content": full_text,
        }

    except ImportError:
        logger.error("PyMuPDF (fitz) not installed. Install with: pip install pymupdf")
        return None
    except Exception as e:
        logger.error(f"PDF parsing error for {pdf_path}: {e}")
        return None


def parse_pdf_from_url(url: str) -> Optional[dict]:
    """Download and parse a PDF from URL."""
    import httpx

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (AI-Crypto-Monitor/2.0)"
            })
            response.raise_for_status()

            # Save to temp file
            suffix = ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=str(DATA_DIR)) as f:
                f.write(response.content)
                temp_path = f.name

            result = parse_pdf_content(temp_path)

            # Cleanup temp file
            try:
                Path(temp_path).unlink()
            except Exception:
                pass

            return result

    except Exception as e:
        logger.error(f"PDF download/parse error for {url}: {e}")
        return None


def import_pdf_as_article(
    db: Session,
    pdf_path: str = None,
    pdf_url: str = None,
    source_name: str = "Manual PDF Import",
) -> Optional[Article]:
    """Import a PDF file as an article in the system."""
    # Parse PDF
    if pdf_path:
        parsed = parse_pdf_content(pdf_path)
        url = f"file://{pdf_path}"
    elif pdf_url:
        parsed = parse_pdf_from_url(pdf_url)
        url = pdf_url
    else:
        return None

    if not parsed:
        return None

    title = parsed["title"] or "Untitled PDF"
    content = parsed["content"]

    # Deduplication
    content_hash = hashlib.sha256(f"{title}|{url}".encode()).hexdigest()
    existing = db.query(Article).filter(Article.content_hash == content_hash).first()
    if existing:
        logger.info(f"PDF already imported: {title}")
        return existing

    # Find or create source
    source = db.query(Source).filter(Source.name == source_name).first()
    if not source:
        source = Source(
            name=source_name,
            category="institution",
            region="global",
            credibility_score=0.8,
            url=f"pdf://{source_name}",
            source_type="manual",
            enabled=True,
            health_status="healthy",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

    # Create article
    article = Article(
        source_id=source.id,
        title=title,
        url=url,
        author=parsed.get("author", None),
        published_at=datetime.datetime.utcnow(),
        raw_content=content[:50000],  # Limit content size
        language="en",
        content_hash=content_hash,
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    logger.info(f"PDF imported as article {article.id}: {title} ({parsed['page_count']} pages)")
    return article


def batch_import_pdf_urls(db: Session, urls: list[str], source_name: str = "Research Reports") -> list[dict]:
    """Import multiple PDFs from URLs."""
    results = []
    for url in urls:
        try:
            article = import_pdf_as_article(db, pdf_url=url, source_name=source_name)
            if article:
                results.append({
                    "url": url,
                    "status": "success",
                    "article_id": article.id,
                    "title": article.title,
                })
            else:
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": "Parse failed",
                })
        except Exception as e:
            results.append({
                "url": url,
                "status": "error",
                "error": str(e),
            })
    return results

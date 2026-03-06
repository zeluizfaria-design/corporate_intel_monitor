"""Normalização e scoring de artigos."""
import re
from datetime import datetime


def normalize_article(article_dict: dict) -> dict:
    """Normaliza campos de um artigo antes de persistir."""
    if "title" in article_dict and article_dict["title"]:
        article_dict["title"] = _clean_text(article_dict["title"])

    if "content" in article_dict and article_dict["content"]:
        article_dict["content"] = _clean_text(article_dict["content"])

    if "company_ticker" in article_dict and article_dict["company_ticker"]:
        article_dict["company_ticker"] = article_dict["company_ticker"].upper().strip()

    return article_dict


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()

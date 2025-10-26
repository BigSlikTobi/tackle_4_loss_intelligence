"""Validate translated article structure against expectations."""

from __future__ import annotations

from ..contracts.translated_article import TranslatedArticle, TranslationRequest


def validate_structure(
    article: TranslatedArticle,
    *,
    reference: TranslationRequest | None = None,
) -> TranslatedArticle:
    """Ensure translation retains structure and preserved terms."""

    if article.error:
        return article

    missing_fields = [
        field
        for field, value in (
            ("headline", article.headline.strip()),
            ("sub_header", article.sub_header.strip()),
            ("introduction_paragraph", article.introduction_paragraph.strip()),
        )
        if not value
    ]
    if missing_fields:
        article.error = f"Missing translated fields: {', '.join(missing_fields)}"
        return article

    if reference:
        if len(article.content) != len(reference.content):
            article.error = (
                "Translated article must contain the same number of paragraphs as the source"
            )
            return article
        missing_terms = [
            term for term in reference.preserve_terms if term not in " ".join(article.content)
        ]
        if missing_terms:
            article.error = f"Preserved terms missing from translation: {', '.join(missing_terms[:5])}"
            return article
        article.preserved_terms = reference.preserve_terms
        article.source_article_id = reference.article_id

    return article.compute_word_count()

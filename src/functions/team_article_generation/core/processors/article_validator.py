"""Validation helpers for generated team articles."""

from __future__ import annotations

from ..contracts.team_article import GeneratedArticle, SummaryBundle


def validate_article(article: GeneratedArticle, bundle: SummaryBundle | None = None) -> GeneratedArticle:
    """Ensure required fields are present and the tone stays on target."""

    if article.error:
        return article

    missing_fields: list[str] = []
    for field, raw_value in (
        ("headline", article.headline),
        ("sub_header", article.sub_header),
        ("introduction_paragraph", article.introduction_paragraph),
    ):
        if not (raw_value and raw_value.strip()):
            missing_fields.append(field)
    if missing_fields:
        article.error = f"Missing required fields: {', '.join(missing_fields)}"
        return article

    if not article.content:
        article.error = "Article must include at least one body paragraph"
        return article

    if any(len(paragraph.split()) < 10 for paragraph in article.content):
        article.error = "Article paragraphs must contain at least 10 words"
        return article

    if bundle and bundle.team_name:
        team_name = bundle.team_name.strip()
        if team_name and team_name not in article.headline:
            article.error = f"Headline must mention {team_name}"
            return article

    return article

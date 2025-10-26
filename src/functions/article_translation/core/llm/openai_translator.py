"""OpenAI GPT-5-mini client placeholder for translation."""

from ..contracts.translated_article import TranslatedArticle, TranslationRequest


class OpenAITranslationClient:
    """Wraps GPT-5-mini interactions (implementation pending)."""

    def __init__(self, *, model: str = "gpt-5-mini-flex") -> None:
        self.model = model

    def translate(self, request: TranslationRequest) -> TranslatedArticle:
        """Return a placeholder translation pending Task 8."""
        return TranslatedArticle(
            language=request.language,
            headline=request.headline,
            sub_header=request.sub_header,
            introduction_paragraph=request.introduction_paragraph,
            content=request.content,
            error="Article translation not implemented",
        )

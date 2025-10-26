"""OpenAI GPT-5 client placeholder for article generation."""

from ..contracts.team_article import GeneratedArticle, SummaryBundle


class OpenAIGenerationClient:
    """Wraps GPT-5 interactions (implementation pending)."""

    def __init__(self, *, model: str = "gpt-5-flex") -> None:
        self.model = model

    def generate(self, bundle: SummaryBundle) -> GeneratedArticle:
        """Return a placeholder article pending Task 6."""
        return GeneratedArticle(
            headline="",
            sub_header="",
            introduction_paragraph="",
            content=[],
            error="Article generation not implemented",
        )

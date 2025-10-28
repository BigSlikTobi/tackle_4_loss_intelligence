"""Tests for Playwright extractor HTML parsing helpers."""

from __future__ import annotations

from src.functions.url_content_extraction.core.extractors.playwright_extractor import PlaywrightExtractor
from src.functions.url_content_extraction.core.processors.content_cleaner import clean_content


def test_parse_html_handles_espn_like_markup() -> None:
    extractor = PlaywrightExtractor()
    html = """
    <html lang="en">
      <head>
        <title>Falcons stay the course after Dolphins loss</title>
        <meta property="article:published_time" content="2025-10-28T12:00:00Z" />
      </head>
      <body>
        <main>
          <div data-testid="story-container">
            <section data-testid="StoryBody">
              <div data-testid="Paragraph">
                Atlanta Falcons coach Raheem Morris explained that no major coaching staff
                changes are planned despite the road loss to the Miami Dolphins on Sunday afternoon.
              </div>
              <div data-testid="Paragraph">
                Morris pointed to the team&apos;s steady improvements on defense and said the
                group needs consistency rather than more turnover heading into the next slate of games.
              </div>
              <p>Quarterback Kirk Cousins added that the locker room remains confident in the current plan.</p>
            </section>
          </div>
        </main>
        <blockquote>"We believe in what we&apos;re building," Morris said.</blockquote>
      </body>
    </html>
    """

    content = extractor._parse_html(html, "https://www.espn.com/nfl/story/_/id/123456/example")  # noqa: SLF001
    cleaned = clean_content(content)

    assert cleaned.title == "Falcons stay the course after Dolphins loss"
    assert len(cleaned.paragraphs) == 3
    assert cleaned.paragraphs[0].startswith("Atlanta Falcons coach Raheem Morris")
    assert cleaned.quotes == ['"We believe in what we\'re building," Morris said.']

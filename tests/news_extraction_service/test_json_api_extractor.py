from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.functions.news_extraction_service.core.extraction.config import (
    SourceConfig,
    load_feed_config,
)
from src.functions.news_extraction_service.core.extraction.extractors import (
    JsonApiExtractor,
    get_extractor,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        return _FakeResponse(self.payload)


def _espn_source() -> SourceConfig:
    return SourceConfig(
        name="ESPN",
        type="json_api",
        publisher="ESPN",
        url="https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        nfl_only=True,
    )


def test_json_api_extractor_keeps_only_supported_nfl_articles():
    now = datetime.now(timezone.utc)
    payload = {
        "articles": [
            {
                "type": "Story",
                "headline": "Lead story",
                "description": "A",
                "published": now.isoformat(),
                "byline": "Reporter",
                "links": {
                    "web": {
                        "href": "https://www.espn.com/nfl/story/_/id/1/lead-story"
                    }
                },
                "categories": [{"description": "NFL"}, {"description": "Draft"}],
            },
            {
                "type": "HeadlineNews",
                "headline": "Headline item",
                "description": "B",
                "lastModified": (now - timedelta(hours=1)).isoformat(),
                "links": {
                    "web": {
                        "href": "https://www.espn.com/nfl/story/_/id/2/headline-item"
                    }
                },
                "categories": [{"description": "NFL"}],
            },
            {
                "type": "Media",
                "headline": "Video clip",
                "published": now.isoformat(),
                "links": {"web": {"href": "https://www.espn.com/video/clip?id=3"}},
            },
            {
                "type": "Story",
                "headline": "Golf crossover",
                "published": now.isoformat(),
                "links": {
                    "web": {
                        "href": "https://www.espn.com/golf/story/_/id/4/biggest-nfl-fan"
                    }
                },
            },
            {
                "type": "Story",
                "headline": "Old story",
                "published": (now - timedelta(days=10)).isoformat(),
                "links": {
                    "web": {
                        "href": "https://www.espn.com/nfl/story/_/id/5/old-story"
                    }
                },
            },
        ]
    }
    http_client = _RecordingHttpClient(payload)
    extractor = JsonApiExtractor(http_client)

    items = extractor.extract(_espn_source(), max_articles=10, days_back=7)

    assert [item.url for item in items] == [
        "https://www.espn.com/nfl/story/_/id/1/lead-story",
        "https://www.espn.com/nfl/story/_/id/2/headline-item",
    ]
    assert items[0].tags == ["NFL", "Draft"]
    assert items[0].author == "Reporter"
    assert http_client.calls[0]["url"].endswith("?limit=10")
    assert (
        http_client.calls[0]["kwargs"]["headers"]["Accept"]
        == "application/json,text/plain;q=0.9,*/*;q=0.8"
    )


def test_get_extractor_supports_json_api():
    extractor = get_extractor("json_api", _RecordingHttpClient({"articles": []}))
    assert isinstance(extractor, JsonApiExtractor)


def test_feed_config_uses_json_api_for_espn():
    config = load_feed_config()
    espn = config.get_source_by_name("ESPN")
    assert espn is not None
    assert espn.type == "json_api"
    assert espn.url == "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"

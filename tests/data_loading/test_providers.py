import json

import pytest

from src.functions.data_loading.core.providers.base import DataProvider
from src.functions.data_loading.core.providers.registry import (
    get_provider,
    list_providers,
)


class DummyPipeline:
    def __init__(self, records):
        self._records = records
        self.params = None

    def prepare(self, **params):
        self.params = params
        filtered = self._records
        for key, value in params.items():
            filtered = [record for record in filtered if record.get(key) == value]
        return list(filtered)


@pytest.fixture
def sample_records():
    return [
        {
            "season": 2023,
            "week": 1,
            "team": "NE",
            "positions": ["WR", "KR"],
            "player": "Player A",
        },
        {
            "season": 2023,
            "week": 1,
            "team": "BUF",
            "positions": ["QB"],
            "player": "Player B",
        },
        {
            "season": 2022,
            "week": 18,
            "team": "NE",
            "positions": ["TE"],
            "player": "Player C",
        },
    ]


def test_data_provider_filters_iterables(sample_records):
    pipeline = DummyPipeline(sample_records)
    provider = DataProvider(name="dummy", pipeline=pipeline, fetch_keys=("season", "week"))

    result = provider.get(season=2023, week=1, team="NE", positions=["WR", "TE"])

    assert pipeline.params == {"season": 2023, "week": 1}
    assert len(result) == 1
    assert result[0]["player"] == "Player A"


def test_data_provider_serialises_to_json(sample_records):
    pipeline = DummyPipeline(sample_records)
    provider = DataProvider(name="dummy", pipeline=pipeline, fetch_keys=())

    json_output = provider.get(output="json")

    parsed = json.loads(json_output)
    assert isinstance(parsed, list)
    assert parsed[0]["player"] == "Player A"


def test_get_provider_registry_exposes_known_providers():
    providers = list_providers()

    assert "pfr" in providers
    assert callable(providers["pfr"])

    provider = get_provider("pfr")
    from src.functions.data_loading.core.providers.pfr import PfrPlayerSeasonProvider

    assert isinstance(provider, PfrPlayerSeasonProvider)


def test_get_provider_unknown_name_raises_meaningful_error():
    with pytest.raises(KeyError) as exc:
        get_provider("unknown")

    assert "Unknown provider" in str(exc.value)

"""
Test data normalization and merging services.

Tests edge cases including:
- NaN and Infinity values
- Empty strings in ID fields
- Null values in various formats
- Nested structures
- Data conflicts and merging
"""

import pytest
import math
import sys
import types
from src.functions.game_analysis_package.core.processing import (
    DataNormalizer,
    DataMerger,
    NormalizedData
)
from src.functions.game_analysis_package.core.contracts.game_package import (
    GamePackageInput,
    PlayData
)
from src.functions.game_analysis_package.core.fetching.data_fetcher import FetchResult, DataFetcher
from src.functions.game_analysis_package.core.bundling.request_builder import CombinedDataRequest


class TestDataNormalizer:
    """Test the DataNormalizer class."""
    
    def test_normalize_nan_values(self):
        """Test that NaN values are replaced with None."""
        normalizer = DataNormalizer()
        
        # Create fetch result with NaN values
        fetch_result = FetchResult(
            play_by_play=[
                {"play_id": "1", "yards_gained": float('nan'), "score": 10},
                {"play_id": "2", "yards_gained": 5.0, "score": float('nan')},
            ]
        )
        
        result = normalizer.normalize(fetch_result)
        
        # Check that NaN values are replaced with None
        assert result.play_by_play[0]["yards_gained"] is None
        assert result.play_by_play[0]["score"] == 10
        assert result.play_by_play[1]["yards_gained"] == 5.0
        assert result.play_by_play[1]["score"] is None
        
        # Check that normalization count is tracked
        assert normalizer._normalization_count == 2
    
    def test_normalize_infinity_values(self):
        """Test that Infinity values are replaced with None."""
        normalizer = DataNormalizer()
        
        fetch_result = FetchResult(
            play_by_play=[
                {"play_id": "1", "value": float('inf')},
                {"play_id": "2", "value": float('-inf')},
                {"play_id": "3", "value": 10.5},
            ]
        )
        
        result = normalizer.normalize(fetch_result)
        
        assert result.play_by_play[0]["value"] is None
        assert result.play_by_play[1]["value"] is None
        assert result.play_by_play[2]["value"] == 10.5
    
    def test_normalize_empty_string_ids(self):
        """Test that empty strings in ID fields are replaced with None."""
        normalizer = DataNormalizer()
        
        fetch_result = FetchResult(
            ngs_data={
                "passing": [
                    {"player_id": "00-0012345", "yards": 250},
                    {"player_id": "", "yards": 100},
                    {"player_id": "  ", "yards": 150},
                ]
            }
        )
        
        result = normalizer.normalize(fetch_result)
        
        assert result.ngs_data["passing"][0]["player_id"] == "00-0012345"
        assert result.ngs_data["passing"][1]["player_id"] is None
        assert result.ngs_data["passing"][2]["player_id"] is None
    
    def test_normalize_null_strings(self):
        """Test that 'null' strings are replaced with None."""
        normalizer = DataNormalizer()
        
        fetch_result = FetchResult(
            play_by_play=[
                {"play_id": "1", "status": "null"},
                {"play_id": "2", "status": "NULL"},
                {"play_id": "3", "status": "active"},
            ]
        )
        
        result = normalizer.normalize(fetch_result)
        
        assert result.play_by_play[0]["status"] is None
        assert result.play_by_play[1]["status"] is None
        assert result.play_by_play[2]["status"] == "active"
    
    def test_normalize_nested_structures(self):
        """Test that nested dicts and lists are normalized recursively."""
        normalizer = DataNormalizer()
        
        fetch_result = FetchResult(
            team_context={
                "team": "SF",
                "stats": {
                    "passing_yards": 300,
                    "rushing_yards": float('nan'),
                },
                "players": [
                    {"player_id": "00-0012345", "yards": float('inf')},
                    {"player_id": "", "yards": 100},
                ]
            }
        )
        
        result = normalizer.normalize(fetch_result)
        
        assert result.team_context["stats"]["passing_yards"] == 300
        assert result.team_context["stats"]["rushing_yards"] is None
        assert result.team_context["players"][0]["yards"] is None
        assert result.team_context["players"][1]["player_id"] is None
    
    def test_normalize_preserves_valid_data(self):
        """Test that valid data is preserved unchanged."""
        normalizer = DataNormalizer()
        
        fetch_result = FetchResult(
            ngs_data={
                "rushing": [
                    {
                        "player_id": "00-0012345",
                        "yards": 100,
                        "attempts": 20,
                        "avg": 5.0,
                        "touchdowns": 2,
                    }
                ]
            }
        )
        
        result = normalizer.normalize(fetch_result)
        
        record = result.ngs_data["rushing"][0]
        assert record["player_id"] == "00-0012345"
        assert record["yards"] == 100
        assert record["attempts"] == 20
        assert record["avg"] == 5.0
        assert record["touchdowns"] == 2
    
    def test_normalize_tracks_issues(self):
        """Test that normalization issues are tracked."""
        normalizer = DataNormalizer()
        
        # Create data that will cause an error in normalization
        fetch_result = FetchResult(
            play_by_play=[
                {"play_id": "1", "valid": True},
            ]
        )
        
        result = normalizer.normalize(fetch_result)
        
        # Should have processed record successfully
        assert result.records_processed["play_by_play"] == 1
        assert len(result.issues_found) == 0


class TestDataMerger:
    """Test the DataMerger class."""
    
    def test_merge_basic_structure(self):
        """Test basic merge creates correct structure."""
        merger = DataMerger()
        
        # Create minimal game package
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1",
                    game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345",
                    receiver_player_id="00-0067890",
                )
            ]
        )
        
        # Create normalized data
        normalized = NormalizedData(
            play_by_play=[],
            snap_counts=[],
            team_context={},
            ngs_data={}
        )
        
        result = merger.merge(package, normalized)
        
        # Check basic structure
        assert result.season == 2024
        assert result.week == 5
        assert result.game_id == "2024_05_SF_KC"
        assert len(result.plays) == 1
        assert result.plays[0]["play_id"] == "1"
    
    def test_merge_initializes_player_data(self):
        """Test that all players from plays are initialized in player_data."""
        merger = DataMerger()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1",
                    game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345",
                    receiver_player_id="00-0067890",
                    tackler_player_ids=["00-0011111", "00-0022222"],
                )
            ]
        )
        
        normalized = NormalizedData()
        result = merger.merge(package, normalized)
        
        # Check all players are in player_data
        assert "00-0012345" in result.player_data
        assert "00-0067890" in result.player_data
        assert "00-0011111" in result.player_data
        assert "00-0022222" in result.player_data
        assert len(result.player_data) == 4
    
    def test_merge_ngs_data(self):
        """Test that NGS data is merged into player_data."""
        merger = DataMerger()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(play_id="1", game_id="2024_05_SF_KC", passer_player_id="00-0012345")
            ]
        )
        
        normalized = NormalizedData(
            ngs_data={
                "passing": [
                    {
                        "player_gsis_id": "00-0012345",
                        "completions": 25,
                        "attempts": 35,
                        "yards": 300,
                    }
                ],
                "rushing": [
                    {
                        "player_gsis_id": "00-0067890",
                        "attempts": 15,
                        "yards": 75,
                    }
                ]
            }
        )
        
        result = merger.merge(package, normalized)
        
        # Check NGS data is in player_data
        assert "ngs_stats" in result.player_data["00-0012345"]
        assert "passing" in result.player_data["00-0012345"]["ngs_stats"]
        assert result.player_data["00-0012345"]["ngs_stats"]["passing"]["yards"] == 300
        
        assert "ngs_stats" in result.player_data["00-0067890"]
        assert "rushing" in result.player_data["00-0067890"]["ngs_stats"]
        assert result.player_data["00-0067890"]["ngs_stats"]["rushing"]["yards"] == 75
    
    def test_merge_tracks_enrichment(self):
        """Test that merge tracks enrichment counts."""
        merger = DataMerger()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(play_id="1", game_id="2024_05_SF_KC", passer_player_id="00-0012345")
            ]
        )
        
        normalized = NormalizedData(
            ngs_data={
                "passing": [
                    {"player_gsis_id": "00-0012345", "yards": 300},
                    {"player_gsis_id": "00-0067890", "yards": 250},
                ]
            }
        )
        
        result = merger.merge(package, normalized)
        
        # Check enrichment counts
        assert result.players_enriched == 2
        assert result.teams_enriched == 0
    
    def test_merge_to_dict(self):
        """Test that merged data can be serialized to dict."""
        merger = DataMerger()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(play_id="1", game_id="2024_05_SF_KC", passer_player_id="00-0012345")
            ]
        )
        
        normalized = NormalizedData()
        result = merger.merge(package, normalized)
        
        # Convert to dict
        result_dict = result.to_dict()
        
        # Check structure
        assert "game_info" in result_dict
        assert result_dict["game_info"]["game_id"] == "2024_05_SF_KC"
        assert "plays" in result_dict
        assert "player_data" in result_dict
        assert "metadata" in result_dict


class TestDataFetcherSnapCounts:
    """Tests for real snap count fetching."""

    def test_fetch_snap_counts_filters_players(self, monkeypatch):
        """Snap counts fetch populates payload for relevant players."""

        fake_snap_data = [
            {
                "season": 2024,
                "week": 1,
                "game_id": "2024_01_BUF_NYJ",
                "team": "BUF",
                "opponent": "NYJ",
                "player": "Offense Player",
                "pfr_player_id": "PFR12345",
                "offense_snaps": 60,
                "offense_pct": 82.0,
                "st_snaps": 6,
                "st_pct": 12.0,
            },
            {
                "season": 2024,
                "week": 1,
                "game_id": "2024_01_BUF_NYJ",
                "team": "NYJ",
                "opponent": "BUF",
                "player": "Other Player",
                "pfr_player_id": "PFR99999",
                "offense_snaps": 5,
                "offense_pct": 10.0,
            },
        ]

        fake_module = types.ModuleType("nflreadpy")

        def _fake_load_snap_counts(seasons):
            assert seasons == [2024]
            return fake_snap_data

        def _fake_load_rosters(seasons):
            assert seasons == [2024]
            return [
                {"pfr_id": "PFR12345", "gsis_id": "00-0012345"},
                {"pfr_id": "PFR99999", "gsis_id": "00-0099999"},
            ]

        fake_module.load_snap_counts = _fake_load_snap_counts  # type: ignore[attr-defined]
        fake_module.load_rosters = _fake_load_rosters  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nflreadpy", fake_module)

        fetcher = DataFetcher()
        request = CombinedDataRequest(
            season=2024,
            week=1,
            game_id="2024_01_BUF_NYJ",
            home_team="NYJ",
            away_team="BUF",
            include_play_by_play=False,
            include_snap_counts=True,
            include_team_context=False,
        )
        request.player_ids = {"00-0012345"}

        result = FetchResult()
        fetcher._fetch_snap_counts(request, result)

        assert "snap_counts" in result.provenance
        assert "snap_counts" in result.sources_succeeded
        assert len(result.snap_counts) == 1

        payload = result.snap_counts[0]
        assert payload["player_id"] == "00-0012345"
        assert payload["snaps"] == 66  # 60 offense + 6 special teams
        assert payload["snap_pct"] == pytest.approx(82.0)
        assert payload["team"] == "BUF"

    def test_fetch_snap_counts_id_normalization(self, monkeypatch):
        """Snap count fetch handles varied GSIS ID formats."""

        fake_snap_data = [
            {
                "season": 2023,
                "week": 9,
                "game_id": "2023_09_KC_MIA",
                "team": "KC",
                "opponent": "MIA",
                "player": "Quarterback",
                "pfr_player_id": "MAHOMPA00",
                "offense_snaps": 65,
                "offense_pct": 98.0,
            }
        ]

        fake_module = types.ModuleType("nflreadpy")

        def _fake_load_snap_counts(seasons):
            assert seasons == [2023]
            return fake_snap_data

        def _fake_load_rosters(seasons):
            assert seasons == [2023]
            return [
                {"pfr_id": "MAHOMPA00", "gsis_id": "000033873"},
            ]

        fake_module.load_snap_counts = _fake_load_snap_counts  # type: ignore[attr-defined]
        fake_module.load_rosters = _fake_load_rosters  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nflreadpy", fake_module)

        fetcher = DataFetcher()
        request = CombinedDataRequest(
            season=2023,
            week=9,
            game_id="2023_09_KC_MIA",
            home_team="KC",
            away_team="MIA",
            include_play_by_play=False,
            include_snap_counts=True,
            include_team_context=False,
        )
        request.player_ids = {"00-0033873"}

        result = FetchResult()
        fetcher._fetch_snap_counts(request, result)

        assert len(result.snap_counts) == 1
        payload = result.snap_counts[0]
        assert payload["player_id"] == "00-0033873"
        assert payload["snaps"] == 65
        assert payload["snap_pct"] == pytest.approx(98.0)

    def test_fetch_snap_counts_sets_game_context_when_missing(self, monkeypatch):
        """Snap count fetch backfills game/season/week when missing in source."""

        fake_snap_data = [
            {
                "season": 2024,
                "week": 1,
                "team": "BUF",
                "opponent": "NYJ",
                "player": "Quarterback",
                "pfr_player_id": "PFR12345",
                "offense_snaps": 60,
                "offense_pct": 82.0,
            }
        ]

        fake_module = types.ModuleType("nflreadpy")

        def _fake_load_snap_counts(seasons):
            assert seasons == [2024]
            return fake_snap_data

        def _fake_load_rosters(seasons):
            assert seasons == [2024]
            return [
                {"pfr_id": "PFR12345", "gsis_id": "00-0012345"},
            ]

        fake_module.load_snap_counts = _fake_load_snap_counts  # type: ignore[attr-defined]
        fake_module.load_rosters = _fake_load_rosters  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nflreadpy", fake_module)

        fetcher = DataFetcher()
        request = CombinedDataRequest(
            season=2024,
            week=1,
            game_id="2024_01_BUF_NYJ",
            home_team="NYJ",
            away_team="BUF",
            include_play_by_play=False,
            include_snap_counts=True,
            include_team_context=False,
        )
        request.player_ids = {"00-0012345"}

        result = FetchResult()
        fetcher._fetch_snap_counts(request, result)

        assert len(result.snap_counts) == 1
        payload = result.snap_counts[0]
        assert payload["game_id"] == "2024_01_BUF_NYJ"
        assert payload["season"] == 2024
        assert payload["week"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

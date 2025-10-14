"""
Test game summarization service.

Tests team and player summary calculations to ensure accuracy
and consistency with underlying play-by-play data.
"""

import pytest
from src.functions.game_analysis_package.core.processing import (
    GameSummarizer,
    GameSummaries,
    TeamSummary,
    PlayerSummary
)
from src.functions.game_analysis_package.core.processing.data_merger import MergedData
from src.functions.game_analysis_package.core.contracts.game_package import (
    GamePackageInput,
    PlayData
)


class TestTeamSummaries:
    """Test team-level summary calculations."""
    
    def test_team_summary_play_counts(self):
        """Test that team play counts are calculated correctly."""
        summarizer = GameSummarizer()
        
        # Create test package with plays for two teams
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(play_id="1", game_id="2024_05_SF_KC", posteam="SF", defteam="KC"),
                PlayData(play_id="2", game_id="2024_05_SF_KC", posteam="SF", defteam="KC"),
                PlayData(play_id="3", game_id="2024_05_SF_KC", posteam="KC", defteam="SF"),
                PlayData(play_id="4", game_id="2024_05_SF_KC", posteam="KC", defteam="SF"),
                PlayData(play_id="5", game_id="2024_05_SF_KC", posteam="KC", defteam="SF"),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {"play_id": p.play_id, "game_id": p.game_id, "posteam": p.posteam,
                 "defteam": p.defteam, "yards_gained": 0}
                for p in package.plays
            ],
            player_data={}
        )
        
        result = summarizer.summarize(merged)
        
        # Check SF stats
        assert "SF" in result.team_summaries
        sf = result.team_summaries["SF"]
        assert sf.total_plays == 5  # 2 offensive + 3 defensive
        assert sf.offensive_plays == 2
        assert sf.defensive_plays == 3
        
        # Check KC stats
        assert "KC" in result.team_summaries
        kc = result.team_summaries["KC"]
        assert kc.total_plays == 5  # 3 offensive + 2 defensive
        assert kc.offensive_plays == 3
        assert kc.defensive_plays == 2
    
    def test_team_summary_yardage(self):
        """Test that team yardage is calculated correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    posteam="SF", defteam="KC",
                    play_type="pass", yards_gained=15.0
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    posteam="SF", defteam="KC",
                    play_type="run", yards_gained=5.0
                ),
                PlayData(
                    play_id="3", game_id="2024_05_SF_KC",
                    posteam="KC", defteam="SF",
                    play_type="pass", yards_gained=20.0
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "posteam": p.posteam, "defteam": p.defteam,
                    "play_type": p.play_type, "yards_gained": p.yards_gained
                }
                for p in package.plays
            ],
            player_data={}
        )
        
        result = summarizer.summarize(merged)
        
        # Check SF stats
        sf = result.team_summaries["SF"]
        assert sf.total_yards == 20.0
        assert sf.passing_yards == 15.0
        assert sf.rushing_yards == 5.0
        assert sf.yards_per_play == 10.0  # 20 yards / 2 plays
        
        # Check KC stats
        kc = result.team_summaries["KC"]
        assert kc.total_yards == 20.0
        assert kc.passing_yards == 20.0
        assert kc.rushing_yards == 0.0
        assert kc.yards_per_play == 20.0  # 20 yards / 1 play
    
    def test_team_summary_touchdowns(self):
        """Test that touchdowns are counted correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    posteam="SF", touchdown=1
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    posteam="SF", touchdown=0
                ),
                PlayData(
                    play_id="3", game_id="2024_05_SF_KC",
                    posteam="KC", touchdown=1
                ),
                PlayData(
                    play_id="4", game_id="2024_05_SF_KC",
                    posteam="KC", touchdown=1
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "posteam": p.posteam, "touchdown": p.touchdown,
                    "yards_gained": 0
                }
                for p in package.plays
            ],
            player_data={}
        )
        
        result = summarizer.summarize(merged)
        
        # Check SF stats
        sf = result.team_summaries["SF"]
        assert sf.touchdowns == 1
        assert sf.points_scored == 6
        
        # Check KC stats
        kc = result.team_summaries["KC"]
        assert kc.touchdowns == 2
        assert kc.points_scored == 12


class TestPlayerSummaries:
    """Test player-level summary calculations."""
    
    def test_player_summary_passing(self):
        """Test that passing stats are calculated correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345",
                    receiver_player_id="00-0067890",
                    yards_gained=15.0
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345",
                    receiver_player_id="00-0067890",
                    yards_gained=20.0,
                    touchdown=1
                ),
                PlayData(
                    play_id="3", game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345",
                    # No receiver = incomplete
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "passer_player_id": p.passer_player_id,
                    "receiver_player_id": p.receiver_player_id,
                    "yards_gained": p.yards_gained or 0,
                    "touchdown": p.touchdown or 0
                }
                for p in package.plays
            ],
            player_data={"00-0012345": {}, "00-0067890": {}}
        )
        
        result = summarizer.summarize(merged)
        
        # Check passer stats
        passer = result.player_summaries["00-0012345"]
        assert passer.pass_attempts == 3
        assert passer.completions == 2
        assert passer.completion_pct == pytest.approx(66.67, abs=0.1)
        assert passer.passing_yards == 35.0
        assert passer.passing_tds == 1
        assert passer.plays_involved == 3
    
    def test_player_summary_receiving(self):
        """Test that receiving stats are calculated correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    receiver_player_id="00-0067890",
                    yards_gained=15.0
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    receiver_player_id="00-0067890",
                    yards_gained=25.0,
                    touchdown=1
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "receiver_player_id": p.receiver_player_id,
                    "yards_gained": p.yards_gained,
                    "touchdown": p.touchdown or 0
                }
                for p in package.plays
            ],
            player_data={"00-0067890": {}}
        )
        
        result = summarizer.summarize(merged)
        
        # Check receiver stats
        receiver = result.player_summaries["00-0067890"]
        assert receiver.receptions == 2
        assert receiver.targets == 2
        assert receiver.receiving_yards == 40.0
        assert receiver.receiving_tds == 1
        assert receiver.touches == 2
        assert receiver.plays_involved == 2
    
    def test_player_summary_rushing(self):
        """Test that rushing stats are calculated correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    rusher_player_id="00-0033553",
                    yards_gained=5.0
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    rusher_player_id="00-0033553",
                    yards_gained=15.0,
                    touchdown=1
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "rusher_player_id": p.rusher_player_id,
                    "yards_gained": p.yards_gained,
                    "touchdown": p.touchdown or 0
                }
                for p in package.plays
            ],
            player_data={"00-0033553": {}}
        )
        
        result = summarizer.summarize(merged)
        
        # Check rusher stats
        rusher = result.player_summaries["00-0033553"]
        assert rusher.rushing_attempts == 2
        assert rusher.rushing_yards == 20.0
        assert rusher.rushing_tds == 1
        assert rusher.touches == 2
        assert rusher.plays_involved == 2
    
    def test_player_summary_defense(self):
        """Test that defensive stats are calculated correctly."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    tackler_player_ids=["00-0011111"],
                ),
                PlayData(
                    play_id="2", game_id="2024_05_SF_KC",
                    tackler_player_ids=["00-0011111"],
                    assist_tackler_player_ids=["00-0022222"],
                ),
                PlayData(
                    play_id="3", game_id="2024_05_SF_KC",
                    sack_player_ids=["00-0011111"],
                ),
                PlayData(
                    play_id="4", game_id="2024_05_SF_KC",
                    interception_player_id="00-0033333",
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "tackler_player_ids": p.tackler_player_ids,
                    "assist_tackler_player_ids": p.assist_tackler_player_ids,
                    "sack_player_ids": p.sack_player_ids,
                    "interception_player_id": p.interception_player_id,
                    "yards_gained": 0
                }
                for p in package.plays
            ],
            player_data={"00-0011111": {}, "00-0022222": {}, "00-0033333": {}}
        )
        
        result = summarizer.summarize(merged)
        
        # Check primary tackler
        tackler = result.player_summaries["00-0011111"]
        assert tackler.tackles == 2.0  # 2 solo tackles
        assert tackler.sacks == 1.0
        assert tackler.plays_involved == 3
        
        # Check assist tackler
        assist = result.player_summaries["00-0022222"]
        assert assist.tackles == 0.5  # 1 assisted tackle
        
        # Check interceptor
        interceptor = result.player_summaries["00-0033333"]
        assert interceptor.interceptions_caught == 1
    
    def test_player_notable_events(self):
        """Test that notable events are identified correctly."""
        summarizer = GameSummarizer()
        
        # Create player with 100+ rushing yards
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id=f"{i}", game_id="2024_05_SF_KC",
                    rusher_player_id="00-0033553",
                    yards_gained=20.0
                )
                for i in range(6)  # 6 carries * 20 yards = 120 yards
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": p.play_id, "game_id": p.game_id,
                    "rusher_player_id": p.rusher_player_id,
                    "yards_gained": p.yards_gained
                }
                for p in package.plays
            ],
            player_data={"00-0033553": {}}
        )
        
        result = summarizer.summarize(merged)
        
        # Check notable events
        rusher = result.player_summaries["00-0033553"]
        assert "120 rush yds" in rusher.notable_events
    
    def test_player_summary_with_ngs_data(self):
        """Test that NGS data enriches player summaries."""
        summarizer = GameSummarizer()
        
        package = GamePackageInput(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                PlayData(
                    play_id="1", game_id="2024_05_SF_KC",
                    passer_player_id="00-0012345"
                ),
            ]
        )
        
        merged = MergedData(
            season=2024,
            week=5,
            game_id="2024_05_SF_KC",
            plays=[
                {
                    "play_id": "1", "game_id": "2024_05_SF_KC",
                    "passer_player_id": "00-0012345", "yards_gained": 0
                }
            ],
            player_data={
                "00-0012345": {
                    "ngs_stats": {
                        "passing": {
                            "player_display_name": "Patrick Mahomes",
                            "player_position": "QB",
                            "team_abbr": "KC",
                        }
                    }
                }
            }
        )
        
        result = summarizer.summarize(merged)
        
        # Check that NGS data was added
        passer = result.player_summaries["00-0012345"]
        assert passer.player_name == "Patrick Mahomes"
        assert passer.position == "QB"
        assert passer.team == "KC"


class TestGameSummaries:
    """Test GameSummaries container."""
    
    def test_game_summaries_to_dict(self):
        """Test that GameSummaries can be serialized to dict."""
        summaries = GameSummaries(
            game_id="2024_05_SF_KC",
            season=2024,
            week=5
        )
        
        summaries.team_summaries["SF"] = TeamSummary(team="SF")
        summaries.player_summaries["00-0012345"] = PlayerSummary(player_id="00-0012345")
        
        result_dict = summaries.to_dict()
        
        # Check structure
        assert "game_info" in result_dict
        assert result_dict["game_info"]["game_id"] == "2024_05_SF_KC"
        assert "team_summaries" in result_dict
        assert "SF" in result_dict["team_summaries"]
        assert "player_summaries" in result_dict
        assert "00-0012345" in result_dict["player_summaries"]
        assert "metadata" in result_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

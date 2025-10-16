"""
Package validation service for comprehensive game package validation.

This module provides enhanced validation beyond the basic contract validation,
including data quality checks, consistency validation, and detailed error reporting.
"""

from typing import Dict, List, Optional, Set, Any, Tuple
import logging
import math
from dataclasses import dataclass

from ..utils.json_safe import clean_nan_values

from ..contracts.game_package import (
    GamePackageInput,
    PlayData,
    ValidationError
)

logger = logging.getLogger(__name__)


def _format_value_safe(value: Any) -> str:
    """Format a value for display in error/warning messages."""
    cleaned = clean_nan_values(value)
    if cleaned is None:
        return "null"
    if isinstance(cleaned, float) and math.isinf(cleaned):
        return "infinity"
    return str(cleaned)


@dataclass
class ValidationIssue:
    """
    Represents a validation issue found during package validation.
    
    Can be a warning (non-fatal) or an error (fatal).
    """
    level: str  # 'error' or 'warning'
    field: str
    message: str
    play_id: Optional[str] = None
    
    def __str__(self) -> str:
        """Format validation issue as string."""
        if self.play_id:
            return f"[{self.level.upper()}] {self.field} in play {self.play_id}: {self.message}"
        return f"[{self.level.upper()}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    """
    Result of package validation.
    
    Contains both errors (fatal) and warnings (non-fatal) found during validation.
    """
    is_valid: bool
    errors: List[ValidationIssue]
    warnings: List[ValidationIssue]
    stats: Dict[str, Any]
    
    def has_errors(self) -> bool:
        """Check if validation found any errors."""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Check if validation found any warnings."""
        return len(self.warnings) > 0
    
    def get_summary(self) -> str:
        """Get a summary of validation results."""
        if self.is_valid and not self.has_warnings():
            return "✓ Package is valid with no issues"
        elif self.is_valid and self.has_warnings():
            return f"✓ Package is valid with {len(self.warnings)} warning(s)"
        else:
            return f"✗ Package is invalid with {len(self.errors)} error(s) and {len(self.warnings)} warning(s)"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation result to dictionary."""
        return clean_nan_values({
            'is_valid': self.is_valid,
            'summary': self.get_summary(),
            'errors': [str(e) for e in self.errors],
            'warnings': [str(w) for w in self.warnings],
            'stats': self.stats
        })


class PackageValidator:
    """
    Comprehensive package validator for game packages.
    
    Performs multi-level validation:
    1. Structural validation (via contracts)
    2. Data quality validation
    3. Consistency validation
    4. Statistical validation
    """
    
    def __init__(self, strict: bool = False):
        """
        Initialize the package validator.
        
        Args:
            strict: If True, treat warnings as errors
        """
        self.strict = strict
        self.errors: List[ValidationIssue] = []
        self.warnings: List[ValidationIssue] = []
    
    def validate(self, package: GamePackageInput) -> ValidationResult:
        """
        Perform comprehensive validation on a game package.
        
        Args:
            package: Game package to validate
            
        Returns:
            ValidationResult with errors, warnings, and statistics
        """
        # Reset validation state
        self.errors = []
        self.warnings = []
        
        logger.info(f"Validating game package {package.game_id}")
        
        # Collect statistics
        stats = self._collect_statistics(package)
        
        # Perform validation checks
        self._validate_game_info(package)
        self._validate_plays_collection(package)
        self._validate_play_quality(package)
        self._validate_play_consistency(package)
        self._validate_player_references(package)
        
        # Determine if valid
        is_valid = len(self.errors) == 0
        if self.strict and len(self.warnings) > 0:
            # In strict mode, warnings become errors
            is_valid = False
        
        result = ValidationResult(
            is_valid=is_valid,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            stats=stats
        )
        
        logger.info(result.get_summary())
        if result.has_errors():
            for error in result.errors:
                logger.error(str(error))
        if result.has_warnings():
            for warning in result.warnings:
                logger.warning(str(warning))
        
        return result
    
    def _collect_statistics(self, package: GamePackageInput) -> Dict[str, Any]:
        """Collect statistics about the package."""
        stats = {
            'game_id': package.game_id,
            'season': package.season,
            'week': package.week,
            'total_plays': len(package.plays),
            'quarters': set(),
            'play_types': {},
            'teams': set(),
            'unique_players': set()
        }
        
        for play in package.plays:
            # Collect quarters
            if play.quarter:
                stats['quarters'].add(play.quarter)
            
            # Collect play types
            if play.play_type:
                stats['play_types'][play.play_type] = stats['play_types'].get(play.play_type, 0) + 1
            
            # Collect teams
            if play.posteam:
                stats['teams'].add(play.posteam)
            if play.defteam:
                stats['teams'].add(play.defteam)
            
            # Collect player IDs
            self._collect_players_from_play(play, stats['unique_players'])
        
        # Convert sets to sorted lists for JSON serialization
        stats['quarters'] = sorted(list(stats['quarters']))
        stats['teams'] = sorted(list(stats['teams']))
        stats['unique_players_count'] = len(stats['unique_players'])
        del stats['unique_players']  # Don't include the full set
        
        return stats
    
    def _collect_players_from_play(self, play: PlayData, player_set: Set[str]):
        """Helper to collect all player IDs from a play."""
        # Single player fields
        for field in ['passer_player_id', 'receiver_player_id', 'rusher_player_id',
                      'kicker_player_id', 'punter_player_id', 'returner_player_id',
                      'interception_player_id', 'fumble_recovery_player_id', 
                      'forced_fumble_player_id']:
            value = getattr(play, field, None)
            if value:
                player_set.add(value)
        
        # List player fields
        for field in ['tackler_player_ids', 'assist_tackler_player_ids', 'sack_player_ids']:
            value = getattr(play, field, None)
            if value and isinstance(value, list):
                player_set.update(value)
    
    def _validate_game_info(self, package: GamePackageInput):
        """Validate game-level information."""
        # Check for reasonable play count
        # NOTE: Empty plays array (0 plays) is now allowed for dynamic fetching
        # The pipeline will automatically fetch plays from database before validation
        if len(package.plays) == 0:
            # Empty array is OK - will be fetched dynamically
            pass
        elif len(package.plays) < 50:
            self._add_warning('plays', f'Unusually low play count: {len(package.plays)} (typical game has 120-180 plays)')
        elif len(package.plays) > 250:
            self._add_warning('plays', f'Unusually high play count: {len(package.plays)} (typical game has 120-180 plays)')
        
        # Validate correlation_id format if present
        if package.correlation_id:
            if len(package.correlation_id) > 255:
                self._add_warning('correlation_id', 'Correlation ID is very long (>255 chars)')
    
    def _validate_plays_collection(self, package: GamePackageInput):
        """Validate the plays collection as a whole."""
        # Check for duplicate play IDs
        play_ids = [play.play_id for play in package.plays]
        duplicates = [pid for pid in set(play_ids) if play_ids.count(pid) > 1]
        if duplicates:
            self._add_error('plays', f'Duplicate play IDs found: {duplicates[:5]}')
        
        # Check for sequential ordering (play IDs should generally increase)
        # This is a warning, not an error, as plays might not always be perfectly sequential
        non_sequential = []
        for i in range(1, len(package.plays)):
            if package.plays[i].play_id < package.plays[i-1].play_id:
                non_sequential.append(package.plays[i].play_id)
        
        if non_sequential and len(non_sequential) > len(package.plays) * 0.1:
            self._add_warning('plays', f'Many plays appear out of sequence: {len(non_sequential)} of {len(package.plays)}')
    
    def _validate_play_quality(self, package: GamePackageInput):
        """Validate individual play data quality."""
        plays_missing_quarter = 0
        plays_missing_down = 0
        plays_missing_yards_to_go = 0
        plays_missing_yardline = 0
        plays_missing_play_type = 0
        plays_missing_teams = 0
        
        for play in package.plays:
            # Check for missing critical fields
            if play.quarter is None:
                plays_missing_quarter += 1
            
            if play.down is None:
                plays_missing_down += 1
            
            if play.yards_to_go is None:
                plays_missing_yards_to_go += 1
            
            if play.yardline is None:
                plays_missing_yardline += 1
            
            if play.play_type is None:
                plays_missing_play_type += 1
            
            if not play.posteam or not play.defteam:
                plays_missing_teams += 1
            
            # Validate play-specific data
            self._validate_individual_play(play)
        
        # Report warnings for missing data
        total_plays = len(package.plays)
        threshold = 0.1  # Warn if >10% of plays missing data
        
        if plays_missing_quarter > total_plays * threshold:
            self._add_warning('plays', f'{plays_missing_quarter} plays missing quarter information')
        
        if plays_missing_down > total_plays * threshold:
            self._add_warning('plays', f'{plays_missing_down} plays missing down information')
        
        if plays_missing_yards_to_go > total_plays * threshold:
            self._add_warning('plays', f'{plays_missing_yards_to_go} plays missing yards_to_go information')
        
        if plays_missing_yardline > total_plays * threshold:
            self._add_warning('plays', f'{plays_missing_yardline} plays missing yardline information')
        
        if plays_missing_play_type > total_plays * threshold:
            self._add_warning('plays', f'{plays_missing_play_type} plays missing play_type information')
        
        # Changed from error to warning to support dynamically fetched plays with data quality issues
        if plays_missing_teams > 0:
            self._add_warning('plays', f'{plays_missing_teams} plays missing team information (posteam/defteam)')
    
    def _validate_individual_play(self, play: PlayData):
        """Validate an individual play's data."""
        # Validate down (1-4) - skip if NaN
        if play.down is not None and not (isinstance(play.down, float) and math.isnan(play.down)):
            if play.down < 1 or play.down > 4:
                self._add_error('down', f'Invalid down value: {_format_value_safe(play.down)}', play.play_id)
        
        # Validate quarter (1-5, where 5 is overtime) - skip if NaN
        if play.quarter is not None and not (isinstance(play.quarter, float) and math.isnan(play.quarter)):
            if play.quarter < 1 or play.quarter > 5:
                self._add_error('quarter', f'Invalid quarter value: {_format_value_safe(play.quarter)}', play.play_id)
        
        # Validate yards_to_go (0-99 is reasonable) - skip if NaN
        if play.yards_to_go is not None and not (isinstance(play.yards_to_go, float) and math.isnan(play.yards_to_go)):
            if play.yards_to_go < 0 or play.yards_to_go > 99:
                self._add_warning('yards_to_go', f'Unusual yards_to_go value: {_format_value_safe(play.yards_to_go)}', play.play_id)
        
        # Validate yards_gained (reasonable range: -99 to 99) - skip if NaN
        if play.yards_gained is not None and not (isinstance(play.yards_gained, float) and math.isnan(play.yards_gained)):
            if play.yards_gained < -99 or play.yards_gained > 99:
                self._add_warning('yards_gained', f'Unusual yards_gained value: {_format_value_safe(play.yards_gained)}', play.play_id)
        
        # Validate touchdown (0 or 1) - skip if NaN
        if play.touchdown is not None and not (isinstance(play.touchdown, float) and math.isnan(play.touchdown)):
            if play.touchdown not in [0, 1]:
                self._add_warning('touchdown', f'Unusual touchdown value: {_format_value_safe(play.touchdown)} (expected 0 or 1)', play.play_id)
        
        # Validate play type has a player associated
        if play.play_type == 'pass':
            if not play.passer_player_id:
                self._add_warning('passer_player_id', 'Pass play missing passer_player_id', play.play_id)
        
        if play.play_type == 'run':
            if not play.rusher_player_id:
                self._add_warning('rusher_player_id', 'Run play missing rusher_player_id', play.play_id)
    
    def _validate_play_consistency(self, package: GamePackageInput):
        """Validate consistency across plays."""
        # Check that teams are consistent
        teams = set()
        for play in package.plays:
            if play.posteam:
                teams.add(play.posteam)
            if play.defteam:
                teams.add(play.defteam)
        
        if len(teams) > 2:
            self._add_warning('teams', f'More than 2 teams found in game: {sorted(teams)}')
        elif len(teams) < 2:
            self._add_warning('teams', f'Less than 2 teams found in game: {sorted(teams)}')
        
        # Validate game_id in teams matches package game_id
        game_info = package.get_game_info()
        if game_info.home_team and game_info.away_team:
            expected_teams = {game_info.home_team, game_info.away_team}
            if teams and teams != expected_teams:
                self._add_warning('teams', f'Teams in plays {sorted(teams)} do not match game_id teams {sorted(expected_teams)}')
    
    def _validate_player_references(self, package: GamePackageInput):
        """Validate player ID references."""
        # Collect all player IDs
        player_ids = set()
        for play in package.plays:
            self._collect_players_from_play(play, player_ids)
        
        # Check for reasonable player count
        if len(player_ids) < 5:
            self._add_warning('players', f'Very few unique players found: {len(player_ids)} (typical game has 40-60)')
        elif len(player_ids) > 100:
            self._add_warning('players', f'Unusually high number of unique players: {len(player_ids)} (typical game has 40-60)')
        
        # Validate player ID format (should match pattern like 00-0012345)
        invalid_format_count = 0
        for player_id in player_ids:
            if not self._is_valid_player_id_format(player_id):
                invalid_format_count += 1
        
        if invalid_format_count > 0:
            self._add_warning('player_ids', f'{invalid_format_count} player IDs have non-standard format')
    
    def _is_valid_player_id_format(self, player_id: str) -> bool:
        """
        Check if player ID matches expected format.
        
        Common formats:
        - 00-0012345 (7-digit with prefix)
        - 00-0034567
        """
        if not player_id:
            return False
        
        # Check for common format: XX-XXXXXXX
        parts = player_id.split('-')
        if len(parts) == 2:
            return len(parts[0]) == 2 and len(parts[1]) == 7 and parts[1].isdigit()
        
        # Allow other formats as valid (might be test data or alternative sources)
        return True
    
    def _add_error(self, field: str, message: str, play_id: Optional[str] = None):
        """Add a validation error."""
        self.errors.append(ValidationIssue(
            level='error',
            field=field,
            message=message,
            play_id=play_id
        ))
    
    def _add_warning(self, field: str, message: str, play_id: Optional[str] = None):
        """Add a validation warning."""
        self.warnings.append(ValidationIssue(
            level='warning',
            field=field,
            message=message,
            play_id=play_id
        ))


def validate_package_with_details(
    package: GamePackageInput,
    strict: bool = False
) -> ValidationResult:
    """
    Convenience function to validate a package with detailed results.
    
    Args:
        package: Game package to validate
        strict: If True, treat warnings as errors
        
    Returns:
        ValidationResult with errors, warnings, and statistics
    """
    validator = PackageValidator(strict=strict)
    return validator.validate(package)
